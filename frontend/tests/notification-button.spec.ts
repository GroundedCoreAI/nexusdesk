import { test, expect } from '@playwright/test';

test('notification button sits beside the account menu and exposes an empty inbox', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/me') return route.fulfill({ json: { role: 'admin', tenant: 'test', actor: 'staff:test' } });
    if (path === '/modules' || path === '/extensions/ui') return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto('/#/overview');

  const notification = page.getByRole('button', { name: '消息通知' });
  const language = page.locator('.language-switch');
  const account = page.getByRole('button', { name: '账户菜单' });

  await expect(notification).toBeVisible();
  await expect(account).toBeVisible();
  const languageBox = await language.boundingBox();
  const notificationBox = await notification.boundingBox();
  const accountBox = await account.boundingBox();
  expect(notificationBox!.x).toBeGreaterThan(languageBox!.x + languageBox!.width);
  expect(accountBox!.x).toBeGreaterThan(notificationBox!.x + notificationBox!.width);

  await notification.click();
  await expect(page.locator('.notification-panel')).toContainText('暂无新消息');
  await expect(notification).toHaveAttribute('aria-expanded', 'true');
  await page.screenshot({ path: 'test-results/notification-button.png', fullPage: true });
  await page.keyboard.press('Escape');
  await expect(page.locator('.notification-panel')).toBeHidden();
  await expect(notification).toHaveAttribute('aria-expanded', 'false');

  await language.click();
  await page.getByRole('menuitem').filter({ hasText: 'English' }).click();
  await expect(page.getByRole('button', { name: 'Notifications' })).toBeVisible();
  await page.getByRole('button', { name: 'Notifications' }).click();
  await expect(page.locator('.notification-panel')).toContainText('No new notifications');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
