import {test,expect} from '@playwright/test';
const link='hosted-link-1234',conversation='55555555-5555-4555-8555-555555555555',run='66666666-6666-4666-8666-666666666666';

test('hosted page mints a visitor session and chats without a sign-in',async({page})=>{
 let visitor='';let minted=0;let createBody:any=null;const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/hosted/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname;
  if(path.endsWith('/sessions')){
   minted++;const body=JSON.parse(r.postData()||'{}');visitor=body.visitor_id;
   return route.fulfill({status:201,json:{access_token:'chat_visitor',token_type:'Bearer',expires_in:43200,external_user_id:'enterprise:77777777-7777-4777-8777-777777777777',visitor_id:visitor}});
  }
  return route.fulfill({json:{title:'门店助手',color:'#123456',welcome:'你好，请描述你的问题。',application:'门店客服'}});
 });
 await page.route('**/openapi/v1/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/openapi/v1','');
  expect(r.headers()['authorization']).toBe('Bearer chat_visitor');
  if(path==='/targets')return route.fulfill({json:{mode:'service_application',target:{kind:'service_application',id:conversation,key:'store',name:'门店客服',version:1,pinned:false,published_version:1}}});
  if(path==='/conversations'){createBody=r.postDataJSON();return route.fulfill({status:201,json:{conversation_id:conversation,agent_id:null}});}
  if(path.endsWith('/messages')&&r.method()==='POST'){expect(r.postDataJSON().message).toBe('门店几点关门？');return route.fulfill({status:200,contentType:'text/event-stream',body:`event: accepted\ndata: {"run_id":"${run}"}\n\nevent: run.completed\ndata: {"run_id":"${run}","id":"${run}","status":"completed","output":"每天十点关门。"}\n\n`});}
  if(path.endsWith('/messages'))return route.fulfill({json:{items:[{role:'user',content:'门店几点关门？'},{role:'assistant',content:'每天十点关门。'}]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/h/'+link);
 await expect(page.getByText('门店助手',{exact:true})).toBeVisible();
 await expect(page.getByText('你好，请描述你的问题。',{exact:true})).toBeVisible();
 await expect.poll(()=>minted).toBe(1);
 expect(visitor).toMatch(/^[0-9a-f]{32}$/);
 // An application-delivered page must not name an agent: the binding decides.
 await page.getByLabel('输入消息',{exact:true}).fill('门店几点关门？');
 await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.getByText('每天十点关门。',{exact:true})).toBeVisible();
 expect(createBody).toEqual({external_session_id:expect.any(String)});
 await expect(page.getByLabel('选择 Agent')).toHaveCount(0);
 await page.screenshot({path:'test-results-phase3/hosted-web-chat.png',fullPage:true});
 expect(errors).toEqual([]);
});

test('hosted page renews an expired credential instead of showing a sign-in',async({page})=>{
 let tokens=0;
 await page.route('**/api/v1/hosted/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/sessions'))return route.fulfill({status:201,json:{access_token:'chat_'+(++tokens),token_type:'Bearer',expires_in:43200,external_user_id:'enterprise:77777777-7777-4777-8777-777777777777',visitor_id:'v'}});
  return route.fulfill({json:{title:'门店助手',color:'#123456',welcome:'',application:'门店客服'}});
 });
 await page.route('**/openapi/v1/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/openapi/v1','');
  // The stored credential is stale: the first probe must push the page to mint
  // a replacement rather than render a login wall.
  if(r.headers()['authorization']==='Bearer chat_stale')return route.fulfill({status:401,json:{error:{code:'invalid_enterprise_session'}}});
  if(path==='/targets')return route.fulfill({json:{mode:'service_application',target:{kind:'service_application',id:conversation,key:'store',name:'门店客服',version:1,pinned:false,published_version:1}}});
  return route.fulfill({json:{items:[]}});
 });
 await page.goto('/h/'+link);
 await page.evaluate(()=>sessionStorage.setItem('nexusdesk.hosted.'+location.pathname.split('/')[2],'chat_stale'));
 await page.reload();
 await expect(page.getByLabel('输入消息',{exact:true})).toBeVisible();
 await expect.poll(()=>tokens).toBeGreaterThan(0);
 await expect(page.getByText('登录后开始对话')).toHaveCount(0);
});

test('a reload resumes the stored session instead of opening a new conversation',async({page})=>{
 const sessionBodies:any[]=[];let minted=0;
 await page.route('**/api/v1/hosted/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/sessions')){minted++;return route.fulfill({status:201,json:{access_token:'chat_visitor',token_type:'Bearer',expires_in:43200,external_user_id:'enterprise:77777777-7777-4777-8777-777777777777',visitor_id:'v'}});}
  return route.fulfill({json:{title:'门店助手',color:'#123456',welcome:'你好，请描述你的问题。',application:'门店客服'}});
 });
 await page.route('**/openapi/v1/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/openapi/v1','');
  if(path==='/targets')return route.fulfill({json:{mode:'service_application',target:{kind:'service_application',id:conversation,key:'store',name:'门店客服',version:1,pinned:false,published_version:1}}});
  if(path==='/targets')return route.fulfill({json:{mode:'service_application',target:{kind:'service_application',id:conversation,key:'store',name:'门店客服',version:1,pinned:false,published_version:1}}});
  if(path==='/conversations'&&r.method()==='POST'){sessionBodies.push(r.postDataJSON());return route.fulfill({status:201,json:{conversation_id:conversation,agent_id:null}});}
  if(path.endsWith('/messages')&&r.method()==='POST'){const run='77777777-7777-4777-8777-777777777777';return route.fulfill({status:200,contentType:'text/event-stream',body:`event: accepted\ndata: {"run_id":"${run}"}\n\nevent: run.completed\ndata: {"run_id":"${run}","status":"completed","output":"每天十点关门。"}\n\n`});}
  if(path.endsWith('/messages'))return route.fulfill({json:{items:[{role:'user',content:'门店几点关门？'},{role:'assistant',content:'每天十点关门。'}]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/h/'+link);
 await expect(page.getByLabel('输入消息',{exact:true})).toBeVisible({timeout:30000});
 await page.getByLabel('输入消息',{exact:true}).fill('门店几点关门？');
 await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.getByText('每天十点关门。',{exact:true})).toBeVisible();
 expect(minted).toBe(1);
 const firstSession=sessionBodies[0].external_session_id;

 // The reload keeps the session segment, so the same conversation comes back
 // with its history instead of a blank welcome screen.
 await page.reload();
 await expect(page.getByText('每天十点关门。',{exact:true})).toBeVisible({timeout:30000});
 const resumed=sessionBodies.filter(body=>body.external_session_id===firstSession);
 expect(resumed.length).toBeGreaterThan(1);
 expect(minted).toBe(1);
});

test('a framed hosted page reports its content height to the host',async({page})=>{
 const base=process.env.E2E_BASE_URL||'http://127.0.0.1:5173';
 await page.route('**/api/v1/hosted/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/sessions'))return route.fulfill({status:201,json:{access_token:'chat_visitor',token_type:'Bearer',expires_in:43200,external_user_id:'enterprise:77777777-7777-4777-8777-777777777777',visitor_id:'v'}});
  return route.fulfill({json:{title:'门店助手',color:'#123456',welcome:'你好，请描述你的问题。',application:'门店客服'}});
 });
 await page.route('**/openapi/v1/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/openapi/v1','');
  if(path==='/targets')return route.fulfill({json:{mode:'service_application',target:{kind:'service_application',id:conversation,key:'store',name:'门店客服',version:1,pinned:false,published_version:1}}});
  if(path==='/conversations')return route.fulfill({status:201,json:{conversation_id:conversation,agent_id:null}});
  return route.fulfill({json:{items:[]}});
 });
 // The host listens for height reports and sizes the iframe to match. A cap
 // based on the viewport would move as the iframe grows, so the count must
 // settle instead of climbing forever.
 await page.setContent(`<body style="margin:0"><iframe id="f" src="${base}/h/${link}" style="width:100%;border:0;height:120px"></iframe>
  <script>window.__heights=[];addEventListener('message',e=>{if(e.data&&e.data.type==='nexusdesk.hosted.height'){window.__heights.push(e.data.height);document.getElementById('f').style.height=e.data.height+'px';}});</script></body>`);
 await expect.poll(()=>page.evaluate(()=>window.__heights.length),{timeout:30000}).toBeGreaterThan(0);
 const heights:number[]=await page.evaluate(()=>window.__heights);
 expect(heights[heights.length-1]).toBeGreaterThan(200);
 await page.waitForTimeout(1500);
 const settled:number[]=await page.evaluate(()=>window.__heights);
 expect(settled.length).toBe(heights.length);
});
