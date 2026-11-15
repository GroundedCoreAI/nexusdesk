import { test, expect } from '@playwright/test';

const appA = '11111111-1111-4111-8111-111111111111';
const appB = '22222222-2222-4222-8222-222222222222';

test('channel page filters by service application from the URL', async ({ page }) => {
    const channels = [
        {
            id: '33333333-3333-4333-8333-333333333333',
            name: 'A 应用渠道',
            application_id: appA,
            application_key: 'app-a',
            application_name: '应用 A',
            application_version: 1,
            enabled: true,
            provider: 'generic_webhook',
            config: {},
            credentials_configured: true,
            last_activity_at: null,
        },
        {
            id: '44444444-4444-4444-8444-444444444444',
            name: 'B 应用渠道',
            application_id: appB,
            application_key: 'app-b',
            application_name: '应用 B',
            application_version: 2,
            enabled: false,
            provider: 'generic_webhook',
            config: {},
            credentials_configured: false,
            last_activity_at: null,
        },
    ];
    await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
        if (path === '/me') {
            return route.fulfill({ json: { role: 'admin', tenant: 'test', actor: 'admin', permissions: [] } });
        }
        if (path === '/deployment') return route.fulfill({ json: { quickstart: false } });
        if (path === '/extensions/ui') return route.fulfill({ json: [] });
        if (path === '/extensions/capabilities') {
            return route.fulfill({ json: { capabilities: { items: [] } } });
        }
        if (path === '/modules') return route.fulfill({ json: [] });
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
        if (path === '/channels') return route.fulfill({ json: channels });
        if (path === '/service-apps') {
            return route.fulfill({
                json: {
                    items: [
                        { id: appA, key: 'app-a', name: '应用 A', status: 'published', origin: 'user', immutable: false, published_version: 1, draft_revision: 1 },
                        { id: appB, key: 'app-b', name: '应用 B', status: 'published', origin: 'user', immutable: false, published_version: 2, draft_revision: 1 },
                    ],
                    total: 2,
                    page: 1,
                    page_size: 100,
                },
            });
        }
        return route.fulfill({ json: { items: [], total: 0 } });
    });

    await page.goto(`/#/open-platform/channels?application_id=${appA}`);
    await expect(page).toHaveURL(new RegExp(`application_id=${appA}`));
    await expect(page.getByRole('cell', { name: /A 应用渠道/ })).toBeVisible();
    await expect(page.getByRole('cell', { name: /B 应用渠道/ })).toHaveCount(0);
    await expect(page.getByText('1 个渠道', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: '清除筛选', exact: true }).click();
    await expect(page.getByRole('cell', { name: /B 应用渠道/ })).toBeVisible();
    await expect(page).not.toHaveURL(/application_id=/);
});
