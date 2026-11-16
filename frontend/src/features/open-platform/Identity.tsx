import {useEffect,useState} from 'react';
import {Alert,App,Button,Card,Form,Input,Modal,Pagination,Select,Space,Switch,Table,Tabs,Tag,Typography} from 'antd';
import {ArrowLeftOutlined,PlusOutlined,ReloadOutlined} from '@ant-design/icons';
import {t} from '../../i18n';
import {post,put} from '../../shared/api/client';
import {useAccess,useResource} from '../../shared/components/ui';
import {ssoLogin} from './SsoLogin';
import type {Application} from './OpenPlatformPage';

interface Provider {id:string;name:string;kind:string;config:Record<string,string>;enabled:boolean;workbench:boolean;revision:number;secret_configured:boolean}
interface User {id:string;name:string;enabled:boolean;role:string|null;revision:number;identities:{id:string;source:string;subject:string}[]}
const ROOT='/open-platform/identity';
const kinds=[{value:'oidc',label:'OpenID Connect'},{value:'wecom',label:'企业微信 / WeCom'},{value:'dingtalk',label:'钉钉 / DingTalk'},{value:'feishu',label:'飞书 / Feishu'}];
const errorOf=(e:unknown)=>e instanceof Error?e.message:String(e);

function ProviderEditor({value,close,saved}:{value:Provider|null;close:()=>void;saved:()=>void}) {
  const [form]=Form.useForm(),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const kind=Form.useWatch('kind',form)||value?.kind||'oidc';
  return <Modal open width={720} title={value?t('编辑身份提供方'):t('新增身份提供方')} onCancel={close} onOk={()=>form.submit()} confirmLoading={busy} destroyOnHidden>
    {error&&<Alert type="error" title={error}/>}
    <Form form={form} layout="vertical" initialValues={value?{...value,secret:undefined}:{kind:'oidc',enabled:false,workbench:false,config:{platform_origin:location.origin,token_auth:'client_secret_basic'}}} onFinish={async v=>{setBusy(true);setError('');try{const body={name:v.name,kind:v.kind,config:v.config,enabled:v.enabled,workbench:v.workbench,secret:v.secret||null,revision:value?.revision||0};if(value)await put(`${ROOT}/providers/${value.id}`,body);else await post(`${ROOT}/providers`,body);saved();}catch(e){setError(errorOf(e));}finally{setBusy(false);}}}>
      <Form.Item name="kind" hidden><Input/></Form.Item><div className="provider-choices" role="group" aria-label={t('身份提供方')}>{kinds.map(item=><button type="button" key={item.value} aria-pressed={kind===item.value} disabled={!!value} onClick={()=>form.setFieldValue('kind',item.value)}>{item.label}</button>)}</div><Form.Item name="name" label={t('显示名称')} rules={[{required:true}]}><Input maxLength={100}/></Form.Item>
      <Form.Item name={['config','platform_origin']} label={t('平台公开地址')} extra={t('填写用户访问平台的完整来源地址，例如 https://agent.company.com，不含路径。')} rules={[{required:true}]}><Input placeholder="https://agent.company.com"/></Form.Item>
      {kind==='oidc'&&<Form.Item name={['config','issuer']} label="Issuer URL" rules={[{required:true}]}><Input disabled={!!value}/></Form.Item>}
      {kind!=='wecom'&&<Form.Item name={['config','client_id']} label={kind==='dingtalk'?'AppKey / Client ID':kind==='feishu'?'App ID':'Client ID'} rules={[{required:true}]}><Input disabled={!!value}/></Form.Item>}
      {(kind==='wecom'||kind==='feishu')&&<Form.Item name={['config','organization']} label={kind==='wecom'?'Corp ID':'Tenant Key'} extra={t('用于校验企业归属，企业标识变更时请新建身份提供方。')} rules={[{required:true}]}><Input disabled={!!value}/></Form.Item>}
      {kind==='wecom'&&<Form.Item name={['config','agent_id']} label="Agent ID" rules={[{required:true}]}><Input disabled={!!value}/></Form.Item>}
      <Form.Item name="secret" label="Client Secret / App Secret" rules={value?[]:[{required:true}]} extra={value?t('已加密保存；留空保留原密钥。'):t('直接输入密钥，服务端加密保存。')}><Input.Password autoComplete="new-password"/></Form.Item>
      {kind==='oidc'&&<Form.Item name={['config','token_auth']} label={t('客户端认证方式')}><Select options={[{value:'client_secret_basic',label:'client_secret_basic'},{value:'client_secret_post',label:'client_secret_post'}]}/></Form.Item>}
      <Space size="large"><Form.Item name="enabled" label={t('启用')} valuePropName="checked"><Switch/></Form.Item><Form.Item name="workbench" label={t('允许工作台登录')} valuePropName="checked"><Switch/></Form.Item></Space>
      <Alert type="info" showIcon title={t('首次登录只登记身份，工作台角色由管理员分配。')} description={t('修改配置会使已有登录会话失效。嵌入聊天需要在应用中单独授权身份提供方。')}/>
      {value&&<Typography.Paragraph style={{marginTop:16}} copyable>{value.config.platform_origin}/api/v1/sso/callback/{value.id}</Typography.Paragraph>}
    </Form>
  </Modal>;
}

export function IdentityPage({back}:{back:()=>void}) {
  const {admin}=useAccess(),{message,modal}=App.useApp();
  const providers=useResource<Provider[]>(admin?`${ROOT}/providers`:null);
  const [page,setPage]=useState(1),[q,setQ]=useState('');
  const users=useResource<{items:User[];total:number}>(admin?`${ROOT}/users?page=${page}&q=${encodeURIComponent(q)}`:null);
  const [editing,setEditing]=useState<{value:Provider|null}|null>(null),[user,setUser]=useState<User|null>(null),[error,setError]=useState('');
  const [link,setLink]=useState<{id:string;subject:string}|null>(null),[target,setTarget]=useState(''),[busy,setBusy]=useState(false);
  const [form]=Form.useForm();
  if(!admin)return <Alert type="warning" title={t('仅管理员可管理企业身份')}/>;
  return <div className="op-workspace"><div className="op-heading"><Space><Button icon={<ArrowLeftOutlined/>} onClick={back}/><div><h2>{t('企业身份与 SSO')}</h2><p>{t('统一接入企业登录，管理账号映射与工作台权限。')}</p></div></Space><Button icon={<ReloadOutlined/>} onClick={()=>{providers.refresh();users.refresh();}}>{t('刷新')}</Button></div>
    {(error||providers.error||users.error)&&<Alert showIcon type="error" title={error||providers.error||users.error}/>}
    <Tabs items={[{key:'providers',label:t('身份提供方'),children:<><div className="op-toolbar"><Button aria-label={t('新增身份提供方')} type="primary" icon={<PlusOutlined/>} onClick={()=>setEditing({value:null})}>{t('新增身份提供方')}</Button></div><div className="op-grid">{(providers.data||[]).map(p=><Card key={p.id} title={p.name} extra={<Tag color={p.enabled?'success':'default'}>{p.enabled?t('已启用'):t('已停用')}</Tag>}><Tag>{kinds.find(k=>k.value===p.kind)?.label}</Tag><Tag>{p.workbench?t('工作台登录'):t('仅嵌入聊天')}</Tag><p className="op-muted">{t('回调地址')}</p><Typography.Paragraph copyable code>{p.config.platform_origin}/api/v1/sso/callback/{p.id}</Typography.Paragraph><Space><Button onClick={()=>setEditing({value:p})}>{t('编辑')}</Button><Button disabled={!p.enabled||!p.workbench} onClick={async()=>{try{const session=await ssoLogin({id:p.id,name:p.name,kind:p.kind,platform_origin:p.config.platform_origin});await fetch('/api/v1/sso/logout',{method:'POST',headers:{Authorization:'Bearer '+session.access_token}});message.success(t('登录验证成功'));}catch(e){setError(errorOf(e));}finally{users.refresh();}}}>{t('验证登录')}</Button></Space></Card>)}</div><Alert style={{marginTop:20}} showIcon type="info" title={t('接入配置指引')} description={t('创建后复制回调地址到企业身份平台。企业微信使用自建应用；钉钉需开通用户信息和 unionId 转企业用户权限；飞书需填写本企业 Tenant Key；OIDC 服务需支持授权码与 PKCE S256。')}/></>},
    {key:'users',label:t('企业用户映射'),children:<Card><Alert type="info" showIcon title={t('不同来源的账号不会按姓名或邮箱自动合并。')} description={t('确认属于同一人后，可将身份关联到目标用户 ID；旧会话会被撤销，历史聊天不会迁移。')}/><div className="op-toolbar"><Input.Search placeholder={t('搜索姓名或用户 ID')} onSearch={v=>{setQ(v);setPage(1);}} allowClear/></div><Table<User> rowKey="id" dataSource={users.data?.items||[]} loading={users.loading} pagination={false} expandable={{expandedRowRender:u=><Space direction="vertical">{u.identities.map(i=><Space key={i.id}><Tag>{providers.data?.find(p=>'provider:'+p.id===i.source)?.name||i.source}</Tag><code>{i.subject}</code><Button type="link" onClick={()=>{setLink(i);setTarget('');}}>{t('关联到已有用户')}</Button></Space>)}</Space>}} columns={[{title:t('用户'),render:(_,u)=><><strong>{u.name}</strong><br/><Typography.Text copyable type="secondary">{u.id}</Typography.Text></>},{title:t('工作台角色'),render:(_,u)=>u.role||t('未授权')},{title:t('状态'),render:(_,u)=><Tag color={u.enabled?'success':'default'}>{u.enabled?t('已启用'):t('已停用')}</Tag>},{title:t('操作'),render:(_,u)=><Button type="link" onClick={()=>{setUser(u);form.setFieldsValue(u);}}>{t('管理权限')}</Button>}]}/><Pagination total={users.data?.total||0} current={page} pageSize={20} onChange={setPage} showSizeChanger={false}/></Card>}]} />
    {editing&&<ProviderEditor value={editing.value} close={()=>setEditing(null)} saved={()=>{setEditing(null);providers.refresh();}}/>}
    <Modal open={!!user} destroyOnHidden title={t('管理权限')} onCancel={()=>setUser(null)} confirmLoading={busy} onOk={()=>form.submit()}><Form form={form} layout="vertical" onFinish={async values=>{setBusy(true);try{await put(`${ROOT}/users/${user!.id}`,{...values,role:values.role||null,revision:user!.revision});setUser(null);users.refresh();}catch(e){setError(errorOf(e));}finally{setBusy(false);}}}><Form.Item name="name" label={t('用户名称')} rules={[{required:true}]}><Input maxLength={100}/></Form.Item><Form.Item name="role" label={t('工作台角色')}><Select allowClear placeholder={t('未授权')} options={['viewer','operator','admin'].map(value=>({value,label:value}))}/></Form.Item><Form.Item name="enabled" label={t('启用')} valuePropName="checked"><Switch/></Form.Item></Form></Modal>
    <Modal open={!!link} title={t('关联到已有用户')} onCancel={()=>setLink(null)} onOk={()=>modal.confirm({title:t('确认变更身份归属？'),content:t('此身份下次登录将获得目标用户的权限。双方当前会话会被撤销。'),onOk:async()=>{await post(`${ROOT}/identities/${link!.id}/link`,{user_id:target.trim()});setLink(null);users.refresh();}})}><p>{link?.subject}</p><Input value={target} onChange={e=>setTarget(e.target.value)} placeholder={t('目标用户 ID')}/></Modal>
  </div>;
}

interface EmbedConfig {enabled:boolean;hosted:boolean;hosted_key:string|null;welcome:string;origins:string[];provider_ids:string[];title:string;color:string;revision:number}
/** Turn the documented error codes into something a person can act on. */
function embedError(e:unknown) {
  const raw=e instanceof Error?e.message:String(e),code=raw.replace(/^\d+\s·\s*/,'');
  const known:Record<string,string>={
    embed_origin_required:t('启用嵌入聊天时，至少填写一个允许的来源地址。'),
    embed_revision_conflict:t('配置已被其他人修改，请刷新页面后重试。'),
    embed_origin_not_allowed:t('该来源地址不在允许列表中。'),
  };
  if(known[code])return known[code];
  return raw.startsWith('422')?t('有配置项未通过校验，请检查来源地址等字段。'):raw;
}
export function EmbedSettings({app}:{app:Application}) {
  const {admin}=useAccess(),{message,modal}=App.useApp(),[form]=Form.useForm();
  const config=useResource<EmbedConfig|null>(admin?`/open-platform/applications/${app.id}/embed`:null),providers=useResource<Provider[]>(admin?`${ROOT}/providers`:null);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[draft,setDraft]=useState('');
  // The form mounts before the config request resolves (useResource starts
  // with loading=false), and a key-based remount does not re-apply
  // initialValues because the form store persists. Push server state in
  // explicitly whenever the config arrives or changes.
  useEffect(()=>{
    if(config.data){form.resetFields();form.setFieldsValue(config.data);}
  },[config.data,form]);
  if(!admin)return <Alert type="warning" title={t('仅管理员可管理企业身份')}/>;
  if(config.loading)return <Card loading/>;
  const snippet=`<script src="${location.origin}/embed.js"></script>\n<script>\n  const chat = NexusDeskChat.mount({\n    appId: "${app.id}",\n    baseUrl: "${location.origin}"\n  });\n</script>`;
  // The public link is derived, never stored on the client: rotating it in the
  // backend is the only way to hand out a new address.
  const link=config.data?.hosted_key?`${location.origin}/h/${config.data.hosted_key}`:'';
  // A tag typed but not confirmed with Enter never reaches the form value; it is
  // folded in before validation so saving does not silently drop it.
  const commitDraft=()=>{
    const text=draft.trim();
    if(!text)return;
    const current=(form.getFieldValue('origins')||[]) as string[];
    if(!current.includes(text))form.setFieldsValue({origins:[...current,text]});
    setDraft('');
  };
  return <Form form={form} key={config.data?.revision||0} layout="vertical" initialValues={config.data||{enabled:false,hosted:false,welcome:'',origins:[],provider_ids:[],title:app.name,color:'#6562ff'}} onFinish={async v=>{setBusy(true);setError('');try{await put(`/open-platform/applications/${app.id}/embed`,{...v,revision:config.data?.revision||0});setDraft('');config.refresh();message.success(t('已保存'));}catch(e){setError(embedError(e));}finally{setBusy(false);}}}>
    <div className="op-stack">
      {(error||config.error||providers.error)&&<Alert type="error" title={error||config.error||providers.error}/>}
      <Card title={t('嵌入聊天')}>
        <Alert showIcon type="info" title={t('将聊天助手嵌入企业网站，使用 SSO 或用户级短期凭据登录。')} description={t('不要将应用密钥放入网页。无 SSO 时，由企业服务端调用 /openapi/v1/chat/token 换取用户凭据。')}/>
        <Space size="large" wrap><Form.Item name="enabled" label={t('启用嵌入聊天')} valuePropName="checked"><Switch/></Form.Item><Form.Item name="title" label={t('聊天标题')} rules={[{required:true}]}><Input maxLength={80}/></Form.Item><Form.Item name="color" label={t('主题色')} rules={[{pattern:/^#[\da-fA-F]{6}$/,required:true}]}><Input type="color"/></Form.Item></Space>
        <Form.Item name="origins" label={t('允许嵌入的来源地址')} dependencies={['enabled']} extra={t('填写完整来源，需带协议且不带路径，不支持通配符，例如 https://oa.company.com；多个来源按回车逐个确认。')} rules={[({getFieldValue})=>({validator:async(_,value)=>{
          if(!getFieldValue('enabled')||(value||[]).length)return;
          throw new Error(t('启用嵌入聊天时，至少填写一个允许的来源地址。'));
        }})]}><Select mode="tags" tokenSeparators={[',',' ']} onSearch={setDraft} onBlur={commitDraft} placeholder="https://oa.company.com"/></Form.Item>
        <p className="op-muted">{t('只使用独立网页时，关闭「启用嵌入聊天」即可，无需填写来源地址。')}</p>
        <Form.Item name="provider_ids" label={t('允许的登录方式')}><Select mode="multiple" options={(providers.data||[]).map(p=>({value:p.id,label:p.name+(p.enabled?'':` (${t('已停用')})`)}))}/></Form.Item>
      </Card>
      <Card title={t('独立网页（Hosted Web）')}>
        <Alert showIcon type="info" title={t('无需嵌入，直接把公开链接发给访客。')} description={t('访客免登录，会话按浏览器隔离；访问计入本应用的每分钟请求配额。链接泄露时可重新生成。')}/>
        <Space size="large" wrap><Form.Item name="hosted" label={t('启用独立网页')} valuePropName="checked"><Switch/></Form.Item></Space>
        <Form.Item name="welcome" label={t('欢迎语')} extra={t('显示在开始对话之前，留空使用默认提示。')}><Input.TextArea rows={2} maxLength={500} showCount/></Form.Item>
        {link?<><p className="op-muted">{t('公开链接')}</p><Space wrap align="center"><Typography.Paragraph code copyable={{text:link,tooltips:[t('复制链接'),t('已复制')]}} style={{margin:0}}>{link}</Typography.Paragraph><Button danger onClick={()=>modal.confirm({title:t('重新生成公开链接？'),content:t('旧链接立即失效，已打开的页面需要重新进入。'),okText:t('重新生成'),cancelText:t('取消'),onOk:async()=>{try{await post(`/open-platform/applications/${app.id}/embed/hosted-key`);config.refresh();message.success(t('已重新生成'));}catch(e){setError(errorOf(e));}}})}>{t('重新生成链接')}</Button></Space></>:<p className="op-muted">{t('保存后生成公开链接；启用独立网页后即可分享。')}</p>}
      </Card>
      <Card title={t('嵌入代码')}>
        <Typography.Paragraph copyable={{text:snippet}}><pre style={{whiteSpace:'pre-wrap'}}>{snippet}</pre></Typography.Paragraph><p className="op-muted">{t('配置变更会使已有聊天凭据失效，用户需要重新登录。')}</p>
      </Card>
      <Space><Button type="primary" htmlType="submit" loading={busy} onClick={commitDraft}>{t('保存配置')}</Button></Space>
    </div>
  </Form>;
}
