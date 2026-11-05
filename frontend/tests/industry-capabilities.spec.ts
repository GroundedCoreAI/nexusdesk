import { expect, test } from '@playwright/test';
import { mockConsoleApi } from './serviceApiFixtures';

const pack = {
    pack_key: 'content-community',
    name: '内容社区服务包',
    description: '覆盖账号、内容、举报与创作者服务。',
    pack_version: '1.0.0',
    maturity: 'beta',
    digest: 'sha256:content-community',
    object_count: 6,
    scenario_count: 11,
    application_key: 'content-community-service',
    installation_count: 0,
};

const installation = {
    id: '4cc20135-09d7-42a0-a1d4-5a30bfc97c99',
    pack_key: pack.pack_key,
    pack_version: pack.pack_version,
    pack_digest: pack.digest,
    maturity: pack.maturity,
    application_key: pack.application_key,
    status: 'installed',
    scenario_template_versions: {},
    scenario_template_digests: {},
    installed_scenarios: {},
    revision: 1,
    installed_by: 'admin',
    created_at: '2026-11-02T00:00:00Z',
    updated_at: '2026-11-02T00:00:00Z',
};

const provider = {
    id: 'c940bba0-8f91-455c-83d2-e40e84eb8a80',
    key: 'community.account',
    kind: 'object',
    name: '社区账号数据',
    description: '账号状态与资料数据源',
    enabled: true,
    config: { endpoint: 'internal' },
    source: 'manual',
    source_ref: null,
    revision: 1,
    created_at: '2026-11-02T00:00:00Z',
    updated_at: '2026-11-02T00:00:00Z',
};

test('industry capabilities installs packs and manages providers inside service applications', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', error => pageErrors.push(error.message));

    await mockConsoleApi(page);
    await page.route('**/api/v1/industry-packs', route =>
        route.fulfill({ json: { items: [pack], total: 1 } }));
    await page.route('**/api/v1/industry-packs/installations', route =>
        route.fulfill({ json: { items: [], total: 0 } }));
    await page.route('**/api/v1/service-providers**', route =>
        route.fulfill({ json: { items: [provider], total: 1 } }));
    await page.route('**/api/v1/industry-packs/content-community/install', route =>
        route.fulfill({
            status: 201,
            json: { created: true, installation },
        }));

    await page.goto('/#/service-apps/industry');
    await expect(page.getByText('行业能力中心')).toBeVisible();
    await expect(page.locator('.sa-pack-card')).toContainText('内容社区服务包');

    await page.getByRole('button', { name: /接入能力/ }).click();
    await expect(page.locator('.sa-provider-card')).toContainText('社区账号数据');

    await page.getByRole('button', { name: /行业模板/ }).click();
    await page.locator('.sa-pack-card').getByRole('button', { name: /安装/ }).click();
    await expect(page.getByRole('dialog')).toContainText('内容社区服务包');
    await page.getByRole('button', { name: '开始安装' }).click();
    await expect(page.getByText('安装完成')).toBeVisible();

    expect(pageErrors).toEqual([]);
});
