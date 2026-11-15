import {test,expect} from '@playwright/test';
const appId='11111111-1111-4111-8111-111111111111',aid='22222222-2222-4222-8222-222222222222';
test('hosted switch echoes saved state after reload',async({page})=>{
  await page.route('**/api/v1/**',async route=>{
    const pt=new URL(route.request().url()).pathname.replace('/api/v1','');
    if(pt==='/me')return route.fulfill({json:{role:'admin',tenant:'local'}});
    if(pt==='/deployment')return route.fulfill({json:{quickstart:false}});
    if(pt==='/open-platform/identity/providers')return route.fulfill({json:[]});
    if(pt==='/open-platform/agents')return route.fulfill({json:[{id:aid,name:'员工助手',published_version:1}]});
    if(pt.endsWith('/embed'))return route.fulfill({json:{
      app_id:appId,enabled:false,origins:[],provider_ids:[],title:'测试',color:'#6562ff',
      revision:4,hosted:true,hosted_key:'pusxX5HyrZcIllSi',welcome:'欢迎'}});
    return route.fulfill({json:{}});
  });
  await page.goto(`/#/open-platform/${appId}/embed`);
  await expect(page.getByLabel('启用独立网页')).toBeChecked({timeout:5000});
  await expect(page.getByLabel('欢迎语')).toHaveValue('欢迎');
  await expect(page.getByText('pusxX5HyrZcIllSi')).toBeVisible();
});
