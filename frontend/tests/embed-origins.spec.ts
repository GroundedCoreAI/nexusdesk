import {test,expect} from '@playwright/test';
const appId='11111111-1111-4111-8111-111111111111',aid='22222222-2222-4222-8222-222222222222';

/** Turning the iframe switch on without an origin used to surface as a raw 422. */
test('embed chat validates origins in the form and keeps a tag typed without Enter',async({page})=>{
 const puts:Record<string,unknown>[]=[];let embed:Record<string,unknown>|null=null;
 await page.route('**/api/v1/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/api/v1','');
  if(path==='/me')return route.fulfill({json:{role:'admin',tenant:'local'}});
  if(path==='/deployment')return route.fulfill({json:{quickstart:false}});
  if(path==='/open-platform/identity/providers')return route.fulfill({json:[]});
  if(path==='/open-platform/applications/'+appId)return route.fulfill({json:{id:appId,name:'员工助手',enabled:true,agent_ids:[aid],revision:1,rpm:120,max_concurrency:5}});
  if(path.endsWith('/embed')){
   if(r.method()==='PUT'){
    const body=r.postDataJSON() as {enabled:boolean;origins:string[]};
    puts.push(body);
    // Mirrors the service rule: an iframe embed cannot be saved without an origin.
    if(body.enabled&&!body.origins.length)return route.fulfill({status:422,json:{detail:'embed_origin_required'}});
    embed={...body,revision:1};
    return route.fulfill({json:embed});
   }
   return route.fulfill({json:embed});
  }
  if(path==='/open-platform/agents')return route.fulfill({json:[{id:aid,name:'员工助手',published_version:1}]});
  return route.fulfill({json:[]});
 });
 await page.goto(`/#/open-platform/${appId}/embed`);
 await page.getByLabel('启用嵌入聊天',{exact:true}).click();
 await expect(page.getByText('启用嵌入聊天时，至少填写一个允许的来源地址。')).toBeVisible();
 await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await expect.poll(()=>puts.length).toBe(0);
 await page.getByRole('combobox',{name:'允许嵌入的来源地址'}).fill('https://oa.example.com');
 await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await expect.poll(()=>puts.length).toBe(1);
 expect(puts[0].origins).toEqual(['https://oa.example.com']);
 await expect(page.getByRole('button',{name:'保存配置',exact:true})).toBeEnabled();
});
