import { test, expect } from '@playwright/test';

test('connection JSON explains Codex field fallbacks and hides it for other resources', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('agent-platform-token', 'codex-hint-verify'));
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path.endsWith('/me')) data = { role: 'admin', tenant: '验证工作区' };
    if (path.includes('/catalog/connections')) data = { items: [], total: 0, page: 1, page_size: 12 };
    if (path.includes('/catalog/models')) data = { items: [], total: 0, page: 1, page_size: 12 };
    if (path.includes('/catalog/profiles')) data = { items: [], total: 0, page: 1, page_size: 12 };
    await route.fulfill({ json: data });
  });

  await page.goto('/#/models/connections');
  await page.getByRole('button', { name: '新建渠道' }).click();
  const hint = page.getByText(/这些 Codex 字段留空即自动回退/);
  await expect(hint).toBeVisible();
  await expect(hint).toContainText('codex_base_url 用上方服务地址');
  await expect(hint).toContainText('codex_wire_api 用 responses');
  await expect(hint).toContainText('credential_ref 仅用于网关出站');

  await page.keyboard.press('Escape');
  await page.goto('/#/models/models');
  await page.getByRole('button', { name: '新建模型' }).click();
  await expect(page.getByText(/这些 Codex 字段留空即自动回退/)).toHaveCount(0);
});
