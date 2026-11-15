import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Input,Select,Space,Spin} from 'antd';
import {SendOutlined,RobotOutlined,PlusOutlined} from '@ant-design/icons';
import {t} from '../../i18n';
import {roundAnswer,usePacedText} from '../../shared/components/ui';
import {ssoLogin,type LoginProvider} from './SsoLogin';
import './embed-chat.css';

interface Config {title:string;color:string;providers:LoginProvider[]}
interface ChatMessage {role:string;content:string}
interface Run {id:string;status:string;response?:string;output?:string;error_code?:string}
type Delivery = 'agent'|'service_application';

/** randomUUID needs a secure context; hosted pages are often plain HTTP. */
function uuid(): string {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0'));
    return hex.slice(0, 4).join('') + '-' + hex.slice(4, 6).join('') + '-' + hex.slice(6, 8).join('')
        + '-' + hex.slice(8, 10).join('') + '-' + hex.slice(10, 16).join('');
}

/** A hosted page opened inside an iframe reports its own height to the host. */
const FRAME_HEIGHT = 'nexusdesk.hosted.height';

function sessionStorageKey(link: string) { return 'nexusdesk.session.' + link; }

/**
 * The session segment of a hosted visitor, kept per link so a reload resumes the
 * conversation the backend already opened instead of starting a second one.
 *
 * StrictMode runs initialisers twice, so the first read must be cached: without
 * it the second run would see the key it just wrote and mistake a new visitor
 * for a returning one.
 */
const seedCache = new Map<string, { key: string; restored: boolean }>();

function seedSession(link: string): { key: string; restored: boolean } {
    const cached = seedCache.get(link);
    if (cached) return cached;
    let value: { key: string; restored: boolean };
    try {
        const saved = sessionStorage.getItem(sessionStorageKey(link));
        if (saved) {
            value = { key: saved, restored: true };
        } else {
            const created = uuid();
            sessionStorage.setItem(sessionStorageKey(link), created);
            value = { key: created, restored: false };
        }
    } catch {
        value = { key: uuid(), restored: false };
    }
    seedCache.set(link, value);
    return value;
}

/** Report content height so a host page can size the iframe to its content. */
function useFramedHeight() {
    const node = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const host = node.current;
        if (!host || window.parent === window) return;
        const root = document.documentElement;
        root.dataset.hostedFramed = '1';
        let last = 0;
        let frame = 0;
        const report = () => {
            frame = 0;
            const height = Math.ceil(host.getBoundingClientRect().height);
            // A repeated value would bounce between the host and this page.
            if (!height || height === last) return;
            last = height;
            window.parent.postMessage({ type: FRAME_HEIGHT, height }, '*');
        };
        const schedule = () => { if (!frame) frame = requestAnimationFrame(report); };
        const observer = new ResizeObserver(schedule);
        observer.observe(host);
        schedule();
        return () => {
            observer.disconnect();
            if (frame) cancelAnimationFrame(frame);
            delete root.dataset.hostedFramed;
        };
    }, []);
    return node;
}

/** Placeholder rows, so the first paint is not a blank column. */
function ChatSkeleton() {
    return <div className="embed-skeleton" aria-hidden="true">
        <span style={{width: '68%'}}/>
        <span style={{width: '86%'}} className="embed-skeleton-reply"/>
        <span style={{width: '54%'}}/>
    </div>;
}

/**
 * The conversation itself: one credential, one window's worth of state.
 *
 * Both delivery modes share it. A widget instance and a public hosted page
 * differ only in how the credential is obtained, so the chat logic must not
 * fork — otherwise the two surfaces drift apart on streaming and retries.
 */
function ChatWindow({credential,greeting,sessionKey='',restore=false,onExpired,onSignOut}:{credential:string;greeting:string;sessionKey?:string;restore?:boolean;onExpired:()=>void;onSignOut?:()=>void}) {
  const [agents,setAgents]=useState<{id:string;name:string}[]>([]),[agentId,setAgentId]=useState('');
  const [mode,setMode]=useState<Delivery|null>(null),[messages,setMessages]=useState<ChatMessage[]>([]),[input,setInput]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[live,setLive]=usePacedText(),[toolBusy,setToolBusy]=useState(false);
  const [restoring,setRestoring]=useState(restore);
  const conversation=useRef(''),generation=useRef(0),bottom=useRef<HTMLDivElement>(null),credentialRef=useRef(credential);
  const pending=useRef<{text:string;id:string}|null>(null),failed=useRef('');
  // The session segment identifies the conversation across reloads; a widget
  // without one still needs a stable value for the duration of this window.
  const fallbackSession=useRef('');
  if(!fallbackSession.current)fallbackSession.current=uuid();
  const sessionId=sessionKey||fallbackSession.current;
  // A remount (new conversation, new credential) must stop the previous window's
  // in-flight stream from writing into the new one.
  useEffect(()=>()=>{generation.current++;},[]);
  async function api<T>(path:string,body?:unknown,headers:Record<string,string>={}):Promise<T>{
    const r=await fetch('/openapi/v1'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+credentialRef.current,...(body===undefined?{}:{'Content-Type':'application/json'}),...headers},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await r.json();
    if(!r.ok){if(r.status===401)onExpired();throw new Error(data.error?.code||data.detail||'request_failed');}
    return data;
  }
  useEffect(()=>{credentialRef.current=credential;},[credential]);
  // The delivery subject decides the shape of every later call: an application
  // binding supplies the agent itself, so sending an agent id is an error.
  useEffect(()=>{let active=true;api<{mode:string}>('/targets').then(target=>{if(active)setMode(target.mode==='service_application'?'service_application':'agent');}).catch(()=>{if(active)setMode('agent');});return()=>{active=false;};},[]);
  useEffect(()=>{if(mode!=='agent')return;let active=true;api<{id:string;name:string}[]>('/agents').then(items=>{if(active){setAgents(items);setAgentId(old=>items.some(a=>a.id===old)?old:items[0]?.id||'');}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[mode]);
  // A reload resumes the conversation the stored session already owns: the
  // backend keys sessions by (application, visitor, session segment), so asking
  // for one again returns the original id and its history.
  useEffect(()=>{
    if(!restore)return;
    if(mode===null||(mode==='agent'&&!agentId))return;
    let active=true;
    const payload=mode==='service_application'?{external_session_id:sessionId}:{agent_id:agentId,external_session_id:sessionId};
    api<{conversation_id:string}>('/conversations',payload).then(async session=>{
      if(!active||conversation.current)return;
      conversation.current=session.conversation_id;
      const history=await api<{items:ChatMessage[]}>(`/conversations/${session.conversation_id}/messages?limit=200`);
      if(!active)return;
      const items=history.items.filter(m=>m.role==='user'||m.role==='assistant');
      if(items.length)setMessages(items);
    }).catch(()=>{/* An unsent session simply starts empty. */}).finally(()=>{if(active)setRestoring(false);});
    return ()=>{active=false;};
  },[mode,agentId,restore,sessionId]);
  useEffect(()=>{bottom.current?.scrollIntoView({behavior:'smooth'});},[messages,busy,live]);
  async function send(explicit?:string){
    const outgoing=(explicit??input).trim();
    if(busy||!outgoing)return;
    if(!mode||(mode==='agent'&&!agentId))return;
    const text=outgoing,stamp=generation.current;
    const attempt=pending.current?.text===text?pending.current:{text,id:uuid()};pending.current=attempt;
    setBusy(true);setError('');
    try{
      if(!conversation.current){
        const payload=mode==='service_application'?{external_session_id:sessionId}:{agent_id:agentId,external_session_id:sessionId};
        const session=await api<{conversation_id:string}>('/conversations',payload);
        if(stamp!==generation.current)return;
        conversation.current=session.conversation_id;
      }
      setMessages(old=>[...old,{role:'user',content:text}]);setInput('');setLive('');
      // Stream the answer so it appears as it is produced. Rounds that end in tool
      // calls were the model thinking out loud, so they are marked and only the
      // final ReAct round is shown.
      const response=await fetch(`/openapi/v1/conversations/${conversation.current}/messages`,{method:'POST',headers:{Authorization:'Bearer '+credentialRef.current,'Content-Type':'application/json','Idempotency-Key':attempt.id},body:JSON.stringify({message:text,stream:true})});
      if(!response.ok){const data=await response.json().catch(()=>({}));if(response.status===401)onExpired();throw new Error(data.error?.code||data.detail||'request_failed');}
      if(!response.body)throw new Error('stream_unavailable');
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';let runId='';let terminal:Run|null=null;
      // Rounds are marked, never deleted: a delta can arrive after its round's
      // boundary came through the event log, and deleting would let it reappear.
      const rounds=new Map<number,{text:string;toolCalls?:number}>();
      const liveAnswer=()=>roundAnswer([...rounds.values()]);
      while(true){
        const {done,value}=await reader.read();
        if(done)break;
        buffer+=decoder.decode(value,{stream:!done});
        let boundary:number;
        while((boundary=buffer.indexOf('\n\n'))>=0){
          const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
          const lines=block.split('\n');
          const type=lines.find(l=>l.startsWith('event:'))?.slice(6).trim();
          const raw=lines.filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');
          if(!type||!raw)continue;
          const data=JSON.parse(raw);
          if(data.run_id)runId=data.run_id;
          if(type==='model.delta'){if(data.text){const cur=rounds.get(data.round)||{text:''};rounds.set(data.round,{...cur,text:cur.text+data.text});setLive(liveAnswer());}continue;}
          if(type==='model.completed'){const cur=rounds.get(data.round)||{text:''};rounds.set(data.round,{...cur,toolCalls:data.tool_calls||0});setLive(liveAnswer());continue;}
          if(type==='error')throw new Error(data.code);
          // The tool boundary is a durable event, so the status a customer sees
          // reflects what the agent is actually doing instead of a guess.
          if(type==='tool.started')setToolBusy(true);
          if(type==='tool.completed')setToolBusy(false);
          if(['run.completed','run.failed','run.cancelled'].includes(type))terminal=data;
        }
        if(stamp!==generation.current)return;
      }
      if(stamp!==generation.current)return;
      if(!terminal&&runId)terminal=await api<Run>('/runs/'+runId);
      if(stamp!==generation.current)return;
      // Point the reveal at the authoritative answer so it finishes smoothly
      // instead of being cut short by the message list replacing it.
      setLive(terminal?.output||'');
      const history=await api<{items:ChatMessage[]}>(`/conversations/${conversation.current}/messages?limit=200`);
      if(stamp!==generation.current)return;
      setMessages(history.items.filter(m=>m.role==='user'||m.role==='assistant'));
      pending.current=null;
      if(terminal&&terminal.status!=='completed')setError(terminal.error_code||terminal.status);
    }catch(e){
      if(stamp===generation.current){
        // The draft is restored so a failed send costs a click, not retyping.
        failed.current=text;
        setError((e as Error).message);
        setInput(current=>current||text);
      }
    }finally{if(stamp===generation.current)setBusy(false);}
  }
  const picker=mode==='agent'&&agents.length>1;
  return <>
    {error&&<Alert showIcon type="error" title={error} closable onClose={()=>setError('')} action={failed.current?<Button size="small" type="link" disabled={busy} onClick={()=>{setInput('');void send(failed.current);}}>{t('重试')}</Button>:null}/>}
    {(picker||onSignOut)&&<div className="embed-controls">{picker&&<Select aria-label={t('选择 Agent')} value={agentId||undefined} disabled={busy||!!conversation.current} onChange={setAgentId} options={agents.map(a=>({value:a.id,label:a.name}))} style={{flex:1}}/>}{onSignOut&&<Button type="text" onClick={onSignOut}>{t('退出')}</Button>}</div>}
    <div className="embed-messages" role="log" aria-live="polite">
      {restoring?<ChatSkeleton/>:<>
        {!messages.length&&!live&&<div className="embed-empty"><RobotOutlined/><p>{greeting}</p></div>}
        {messages.map((m,i)=><div key={i} className={'embed-message '+m.role}>{m.role==='assistant'&&i===messages.length-1&&live?live:m.content}</div>)}
        {live&&messages[messages.length-1]?.role!=='assistant'&&<div className="embed-message assistant">{live}</div>}
        {busy&&!live&&<div className="embed-thinking"><Spin size="small"/> {toolBusy?t('正在查询资料…'):t('正在思考…')}</div>}
        <div ref={bottom}/>
      </>}
    </div>
    <div className="embed-composer"><Input.TextArea aria-label={t('输入消息')} placeholder={t('输入消息')} value={input} maxLength={8000} autoSize={{minRows:1,maxRows:4}} disabled={busy||!mode} onChange={e=>setInput(e.target.value)} onPressEnter={e=>{if(!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><Button type="primary" icon={<SendOutlined/>} aria-label={t('发送')} loading={busy} disabled={!mode||(mode==='agent'&&!agentId)||!input.trim()} onClick={()=>void send()}/></div>
  </>;
}

/** Embedded in a host page: the parent posts a credential over postMessage or we run SSO. */
export function EmbedChat() {
  const appId=location.pathname.split('/')[2],parentOrigin=new URLSearchParams(location.search).get('parent_origin')||'';
  const [config,setConfig]=useState<Config|null>(null),[error,setError]=useState(''),[credential,setCredential]=useState(''),[ready,setReady]=useState(false);
  const [loginBusy,setLoginBusy]=useState(false),[session,setSession]=useState(0);
  useEffect(()=>{
    if(window.parent===window||!/^https?:\/\//.test(parentOrigin)){setError(t('请通过企业页面中的嵌入组件打开聊天'));return;}
    let active=true;
    const receive=(event:MessageEvent)=>{
      if(event.source!==window.parent||event.origin!==parentOrigin)return;
      if(event.data?.type==='nexusdesk.init')setReady(true);
      if(event.data?.type==='nexusdesk.token'&&typeof event.data.token==='string'&&event.data.token.startsWith('chat_')){setSession(s=>s+1);setCredential(event.data.token);}
      if(event.data?.type==='nexusdesk.token-error')setError(t('获取登录凭据失败，请重试'));
    };
    window.addEventListener('message',receive);
    fetch(`/api/v1/sso/embed/${appId}?parent_origin=${encodeURIComponent(parentOrigin)}`).then(async r=>{const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'embed_origin_not_allowed');if(active){setConfig(data);window.parent.postMessage({type:'nexusdesk.ready'},parentOrigin);}}).catch(e=>{if(active)setError(e.message);});
    return ()=>{active=false;window.removeEventListener('message',receive);};
  },[appId,parentOrigin]);
  return <div className="embed-chat" style={{'--chat-color':config?.color||'#6562ff'} as React.CSSProperties}>
    <header><div className="embed-avatar"><RobotOutlined/></div><div><h1>{config?.title||t('企业助手')}</h1><small>{t('企业智能服务')}</small></div>{credential&&<Button type="text" icon={<PlusOutlined/>} onClick={()=>setSession(s=>s+1)} aria-label={t('新建会话')}/>}</header>
    {!config&&!error?<Spin/>:!ready?<div className="embed-empty">{t('正在连接企业页面')}</div>:!credential?<div className="embed-login"><RobotOutlined style={{fontSize:42,color:config?.color}}/><h2>{t('登录后开始对话')}</h2><p>{t('使用企业账号登录，继续你的专属会话。')}</p><Space direction="vertical" style={{width:'100%'}}>{config?.providers.map(p=><Button block key={p.id} disabled={loginBusy} onClick={async()=>{setLoginBusy(true);setError('');try{const result=await ssoLogin(p,appId,parentOrigin);setCredential(result.access_token);setSession(s=>s+1);}catch(e){setError((e as Error).message);}finally{setLoginBusy(false);}}}>{p.name}</Button>)}<Button block type="link" onClick={()=>window.parent.postMessage({type:'nexusdesk.refresh-token'},parentOrigin)}>{t('获取企业登录凭据')}</Button></Space></div>:<ChatWindow key={credential+':'+session} credential={credential} greeting={t('有什么可以帮你？')} onExpired={()=>{setCredential('');setSession(s=>s+1);}} onSignOut={async()=>{await fetch('/api/v1/sso/logout',{method:'POST',headers:{Authorization:'Bearer '+credential}});setCredential('');setSession(s=>s+1);}}/>}
    <footer>{t('AI 回答仅供参考，请核实重要信息。')}</footer>
  </div>;
}

interface HostedConfig {title:string;color:string;welcome:string;application:string}

/**
 * A public page: no host page, no sign-in. The visitor gets a short-lived
 * credential from the page's own link segment, so the tenant's API keys never
 * reach the browser and revoking the link is a single click.
 */
export function HostedChat() {
  const link=location.pathname.split('/')[2]||'';
  const tokenKey='nexusdesk.hosted.'+link,visitorKey='nexusdesk.visitor.'+link;
  const [config,setConfig]=useState<HostedConfig|null>(null),[error,setError]=useState(''),[credential,setCredential]=useState('');
  const [connecting,setConnecting]=useState(true),[session,setSession]=useState(0);
  const [seed,setSeed]=useState(()=>seedSession(link));
  const pendingMint=useRef<Promise<string>|null>(null);
  const frame=useFramedHeight();
  function stored(key:string){try{return sessionStorage.getItem(key)||'';}catch{return '';}}
  function remember(value:string){try{if(value)sessionStorage.setItem(tokenKey,value);else sessionStorage.removeItem(tokenKey);}catch{/* Storage can be disabled. */}}
  // The visitor id survives reloads, so a refresh continues the same customer
  // namespace instead of scattering one person across several profiles.
  function visitor(){try{const saved=localStorage.getItem(visitorKey);if(saved)return saved;const created=uuid().replaceAll('-','');localStorage.setItem(visitorKey,created);return created;}catch{return '';}}
  // One mint at a time: StrictMode and rapid renewals share the same promise
  // instead of racing two session requests for one visitor.
  function mint():Promise<string>{
    if(pendingMint.current)return pendingMint.current;
    pendingMint.current=(async()=>{
      try{
        const r=await fetch(`/api/v1/hosted/${encodeURIComponent(link)}/sessions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visitor_id:visitor()})});
        const data=await r.json().catch(()=>({}));
        if(!r.ok){setError(data.detail==='hosted_session_rate_limit'?t('访问过多，请稍后再试。'):t('当前对话入口暂不可用，请联系网站管理员。'));return '';}
        return typeof data.access_token==='string'?data.access_token:'';
      }catch{setError(t('网络异常，请稍后重试。'));return '';}
      finally{pendingMint.current=null;}
    })();
    return pendingMint.current;
  }
  useEffect(()=>{
    let active=true;
    fetch(`/api/v1/hosted/${encodeURIComponent(link)}`).then(async r=>{const data=await r.json();if(!r.ok)throw new Error('unavailable');if(active)setConfig(data);}).catch(()=>{if(active)setError(t('当前对话入口暂不可用，请联系网站管理员。'));});
    const saved=stored(tokenKey);
    (saved?Promise.resolve(saved):mint()).then(token=>{
      if(!active)return;
      if(token){remember(token);setCredential(token);}
      setConnecting(false);
    });
    return ()=>{active=false;};
  },[]);
  // An expired credential is normal here: sessions last hours, pages stay open
  // longer. Mint a replacement instead of showing a sign-in wall.
  async function renew(){remember('');setCredential('');setConnecting(true);const token=await mint();if(token){remember(token);setCredential(token);}setConnecting(false);}
  // A new conversation is a new session segment; the previous one stays behind
  // as its own record instead of being overwritten.
  function startNew(){
    const next=uuid();
    try{sessionStorage.setItem(sessionStorageKey(link),next);}catch{/* Storage can be disabled. */}
    seedCache.set(link,{key:next,restored:false});
    setSeed({key:next,restored:false});
    setSession(s=>s+1);
  }
  return <div ref={frame} className="embed-chat" style={{'--chat-color':config?.color||'#6562ff'} as React.CSSProperties}>
    <header><div className="embed-avatar"><RobotOutlined/></div><div><h1>{config?.title||t('企业助手')}</h1><small>{t('在线智能客服')}</small></div>{credential&&<Button type="text" icon={<PlusOutlined/>} onClick={startNew} aria-label={t('新建会话')}/>}</header>
    {error&&<Alert showIcon type="error" title={error} action={!credential?<Button size="small" type="link" disabled={connecting} onClick={()=>void renew()}>{t('重试')}</Button>:null}/>}
    {!credential?(<div className="embed-messages">{connecting?<ChatSkeleton/>:<div className="embed-empty"/>}</div>):<ChatWindow key={credential+':'+session} credential={credential} greeting={config?.welcome||t('有什么可以帮你？')} sessionKey={seed.key} restore={seed.restored} onExpired={()=>void renew()}/>}
    <footer>{t('AI 回答仅供参考，请核实重要信息。')}</footer>
  </div>;
}
