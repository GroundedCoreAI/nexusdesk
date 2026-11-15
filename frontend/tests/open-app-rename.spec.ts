import {test,expect} from '@playwright/test';
const appId='11111111-1111-4111-8111-111111111111',aid='22222222-2222-4222-8222-222222222222',said='55555555-5555-4555-8555-555555555555';

/** Renaming a service-application-bound app used to be silently ignored: the
 *  subject branch built its payload from the stored app, not the form values. */
test('rename a service-application-bound application',async({page})=>{
 let app:any={id:appId,name:'wrench-probe',description:'',enabled:true,agent_ids:[aid],agent_versions:{},knowledge_base_ids:[],revision:2,rpm:120,max_concurrency:5,
  target:{target_kind:'service_application',target_id:said,key:'sa-key',name:'出行服务助手',status:'published',published_version:3,version:3,pinned:false}};
 const puts:any[]=[];const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/api/v1','');
  if(path==='/me')return route.fulfill({json:{role:'admin',tenant:'local'}});
  if(path==='/deployment')return route.fulfill({json:{quickstart:false}});
  if(path==='/open-platform/agents')return route.fulfill({json:[{id:aid,name:'出行助手',published_version:3}]});
  if(path==='/open-platform/service-applications')return route.fulfill({json:[{id:said,application_key:'sa-key',name:'出行服务助手',status:'published',published_version:3,agent_id:aid}]});
  if(path===`/open-platform/service-applications/${said}/versions`)return route.fulfill({json:[{version:3},{version:2}]});
  if(path===`/open-platform/applications/${appId}`){
   if(r.method()==='PUT'){
    const body=r.postDataJSON() as Record<string,unknown>;puts.push(body);
    if(body.revision!==app.revision)return route.fulfill({status:409,json:{detail:'application_revision_conflict'}});
    app={...app,...body,revision:app.revision+1};
   }
   return route.fulfill({json:app});
  }
  return route.fulfill({json:[]});
 });
 await page.goto(`/#/open-platform/${appId}/settings`);
 await expect(page.getByRole('heading',{name:'wrench-probe'})).toBeVisible();
 await page.getByRole('button',{name:'编辑应用',exact:true}).click();
 await page.getByLabel('应用名称',{exact:true}).fill('企业出行门户');
 await page.getByRole('button',{name:/确.*定/}).click();
 await expect.poll(()=>app.name).toBe('企业出行门户');
 expect(puts[0].service_application_id).toBe(said);
 expect(puts[0].service_application_version).toBeNull();
 await expect(page.getByRole('heading',{name:'企业出行门户'})).toBeVisible();
 expect(errors).toEqual([]);
});
