import { test, expect } from '@playwright/test';

for (const role of ['admin', 'viewer']) {
  test(`channels bind a published application version: ${role}`, async ({ page }) => {
    const errors: string[] = [];
    const requests: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const applicationId = '11111111-1111-4111-8111-111111111111';
    const existingChannelId = '33333333-3333-4333-8333-333333333333';
    let channels: object[] = [{
      id: existingChannelId,
      name: '已有客服渠道',
      application_id: applicationId,
      application_key: 'consumer-service',
      application_name: '客服服务',
      application_version: 1,
      enabled: true,
      provider: 'generic_webhook',
      config: {},
      credentials_configured: false,
      last_activity_at: null,
    }, ...Array.from({ length: 10 }, (_, index) => ({
      id: `filler-channel-${index + 1}`,
      name: `备用渠道 ${index + 1}`,
      application_id: applicationId,
      application_key: 'consumer-service',
      application_name: '客服服务',
      application_version: 1,
      enabled: true,
      provider: 'generic_webhook',
      config: {},
      credentials_configured: false,
      last_activity_at: null,
    }))];

    await page.route('**/api/v1/**', async route => {
      const req = route.request();
      const path = new URL(req.url()).pathname.replace('/api/v1', '');
      requests.push(path);
      if (path === '/me') {
        return route.fulfill({
          json: { role, tenant: 'test', actor: role, permissions: [] },
        });
      }
      if (path === '/deployment') return route.fulfill({ json: { quickstart: false } });
      if (path === '/extensions/ui') return route.fulfill({ json: [] });
      if (path === '/extensions/capabilities') {
        return route.fulfill({ json: { capabilities: { items: [] } } });
      }
      if (path === '/modules') return route.fulfill({ json: [] });
      if (path === '/service-apps') {
        return route.fulfill({
          json: {
            items: [{
              id: applicationId,
              key: 'consumer-service',
              name: '客服服务',
              description: '面向客户的客服服务应用',
              status: 'published',
              origin: 'user',
              immutable: false,
              published_version: 2,
              draft_revision: 3,
            }],
            total: 1,
            page: 1,
            page_size: 100,
          },
        });
      }
      if (path === '/service-apps/consumer-service/versions') {
        return route.fulfill({
          json: {
            items: [
              { id: 'version-2', version: 2, current: true, published: true },
              { id: 'version-1', version: 1, current: false, published: true },
            ],
            published_version: 2,
            total: 2,
            page: 1,
            page_size: 100,
          },
        });
      }
      if (path === '/channels/providers') {
        return route.fulfill({
          json: [{
            id: 'generic_webhook',
            name: '通用 Webhook',
            description: '',
            native: false,
            config_fields: [],
            credential_fields: [],
          }],
        });
      }
      if (path === `/channels/${existingChannelId}/application-version`) {
        expect(req.method()).toBe('PUT');
        expect(req.postDataJSON()).toEqual({ application_version: 2 });
        channels = channels.map(channel => (
          channel && typeof channel === 'object' && 'id' in channel
            && channel.id === existingChannelId
            ? { ...channel, application_version: 2 }
            : channel
        ));
        return route.fulfill({ json: channels[0] });
      }
      if (path === '/channels') {
        if (req.method() === 'POST') {
          const body = req.postDataJSON();
          expect(body).toEqual({
            name: '新客服消息入口',
            application_id: applicationId,
            application_version: 2,
            provider: 'generic_webhook',
            signing_secret_ref: null,
          });
          expect(body).not.toHaveProperty('agent_id');
          const channel = {
            id: '44444444-4444-4444-8444-444444444444',
            name: '新客服消息入口',
            application_id: applicationId,
            application_key: 'consumer-service',
            application_name: '客服服务',
            application_version: 2,
            enabled: true,
            provider: 'generic_webhook',
            config: {},
            credentials_configured: false,
          };
          channels = [channel, ...channels];
          return route.fulfill({ status: 201, json: { ...channel, token: 'test-channel-token' } });
        }
        return route.fulfill({ json: channels });
      }
      return route.fulfill({ json: { items: [], total: 0 } });
    });

    await page.goto('/#/channels');
    await expect(page).toHaveURL(/#\/open-platform\/channels$/);
    await expect(page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '渠道接入', exact: true })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: '客服渠道', exact: true })).toHaveAttribute('aria-selected', 'true');
    expect(requests.some(path => path === '/agents')).toBe(false);
    expect(requests.some(path => path.includes('/applications/channels'))).toBe(false);

    await expect(page.getByRole('cell', { name: /已有客服渠道/ })).toBeVisible();
    await expect(page.getByRole('row', { name: /已有客服渠道/ })).toContainText('客服服务');
    await expect(page.getByRole('row', { name: /已有客服渠道/ })).toContainText('v1');
    await expect(page.locator('.channel-table .ant-table-row')).toHaveCount(10);
    await expect(page.locator('.channel-table .ant-pagination-item-2')).toBeVisible();
    await expect(page.locator('.channel-table .ant-table-pagination')).toBeVisible();
    await expect(page.locator('.channel-table .ant-table-pagination')).toHaveCSS(
      'justify-content',
      'flex-end',
    );

    if (role === 'viewer') {
      await expect(page.getByRole('button', { name: '创建渠道', exact: true })).toBeDisabled();
      await expect(
        page.getByRole('row', { name: /已有客服渠道/ })
          .getByRole('button', { name: '切换应用版本', exact: true }),
      ).toBeDisabled();
    } else {
      const existingRow = page.getByRole('row', { name: /已有客服渠道/ });
      await existingRow.getByRole('button', { name: '切换应用版本', exact: true }).click();
      const switchDialog = page.getByRole('dialog', { name: /切换应用版本/ });
      await expect(switchDialog).toBeVisible();
      await switchDialog.getByRole('combobox', { name: '应用版本', exact: true }).click();
      await page.locator('.ant-select-dropdown:visible .ant-select-item-option')
        .filter({ hasText: 'v2 · 当前版本' })
        .click();
      await switchDialog.getByRole('button', { name: '切换应用版本', exact: true }).click();
      await expect.poll(() => requests.some(
        path => path === `/channels/${existingChannelId}/application-version`,
      )).toBe(true);
      await expect(page.getByRole('row', { name: /已有客服渠道/ })).toContainText('v2');

      await page.getByLabel('渠道名称', { exact: true }).fill('新客服消息入口');
      await page.getByRole('combobox', { name: '已发布服务应用', exact: true }).click();
      await page.getByText('客服服务', { exact: true }).last().click();
      await expect(page.getByRole('button', { name: '创建渠道', exact: true })).toBeEnabled();
      await page.getByRole('button', { name: '创建渠道', exact: true }).click();
      await expect(page.getByText('test-channel-token', { exact: true })).toBeVisible();
    }

    await page.getByRole('tab', { name: '应用接入', exact: true }).click();
    await expect(page).toHaveURL(/#\/open-platform$/);
    await expect(page.getByRole('heading', { name: '企业应用', exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('tab', { name: '客服渠道', exact: true })).toHaveAttribute('aria-selected', 'true');
    await page.reload();
    await expect(page.getByRole('heading', { name: '客服渠道', exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}
