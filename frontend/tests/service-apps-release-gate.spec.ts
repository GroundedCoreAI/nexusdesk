import { expect, test, type Page } from '@playwright/test';
import {
    buildApplicationReadiness,
    consumerApp,
    mockConsoleApi,
    scenarios,
} from './serviceApiFixtures';

async function mockReleaseVariant(
    page: Page,
    application: typeof consumerApp,
    scenarioItems: typeof scenarios,
    readiness: ReturnType<typeof buildApplicationReadiness>,
) {
    await mockConsoleApi(page);
    await page.route('**/api/v1/service-scenarios', route => {
        if (route.request().method() === 'GET') {
            return route.fulfill({ json: { items: scenarioItems, total: scenarioItems.length } });
        }
        return route.fallback();
    });
    await page.route('**/api/v1/service-apps/consumer-service', route => {
        if (route.request().method() === 'GET') return route.fulfill({ json: application });
        return route.fallback();
    });
    await page.route('**/api/v1/service-apps/consumer-service/readiness', route =>
        route.fulfill({ json: readiness }));
}

async function openDeploy(page: Page) {
    await page.getByRole('button', { name: '接入与发布', exact: true }).click();
    await expect(page.getByRole('heading', { name: '发布前完整性检查' })).toBeVisible();
}

test('ready readiness enables all three publishing entrances', async ({ page }) => {
    await mockReleaseVariant(page, consumerApp, scenarios, buildApplicationReadiness('ready'));
    await page.goto('/#/service-apps/consumer-service');
    await expect(page.locator('.sa-tree-scene')).toHaveCount(6);

    const topPublish = page.locator('.sa-app-actions').getByRole('button', { name: '发布新版本' });
    await expect(topPublish).toBeEnabled();
    await openDeploy(page);
    await expect(page.locator('.sa-deploy-hero').getByRole('button', { name: '发布新版本' })).toBeEnabled();
    await expect(page.locator('.sa-release-foot').getByRole('button', { name: /发布新版本/ })).toBeEnabled();
    await expect(page.getByText('全部场景已通过完整性检查，可以发布新版本。')).toBeVisible();
});

test('simulate-only readiness disables all three publishing entrances', async ({ page }) => {
    await mockReleaseVariant(page, consumerApp, scenarios, buildApplicationReadiness('simulate_only'));
    await page.goto('/#/service-apps/consumer-service');
    await expect(page.locator('.sa-tree-scene')).toHaveCount(6);

    await expect(page.locator('.sa-app-actions').getByRole('button', { name: '发布新版本' })).toBeDisabled();
    await openDeploy(page);
    await expect(page.locator('.sa-deploy-hero').getByRole('button', { name: '发布新版本' })).toBeDisabled();
    await expect(page.locator('.sa-release-foot').getByRole('button', { name: /发布新版本/ })).toBeDisabled();
    await expect(page.getByText('有 6 个场景仍有发布前待处理项，完成检查后才能发布。')).toBeVisible();
});

test('blocked readiness disables publishing and readiness items open orchestration', async ({ page }) => {
    const blockedReadiness = buildApplicationReadiness(
        'blocked',
        { invoice: 'blocked' },
        'ready',
    );
    await mockReleaseVariant(page, consumerApp, scenarios, blockedReadiness);
    await page.goto('/#/service-apps/consumer-service');
    await expect(page.locator('.sa-tree-scene')).toHaveCount(6);

    await expect(page.locator('.sa-app-actions').getByRole('button', { name: '发布新版本' })).toBeDisabled();
    await openDeploy(page);
    await expect(page.locator('.sa-deploy-hero').getByRole('button', { name: '发布新版本' })).toBeDisabled();
    await expect(page.locator('.sa-release-foot').getByRole('button', { name: /发布新版本/ })).toBeDisabled();
    await expect(page.getByText('有 1 个场景存在发布阻断项，完成检查后才能发布。')).toBeVisible();

    await page.getByRole('button', { name: '在业务编排中查看 发票与报销' }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service$/);
    await expect(page.getByRole('heading', { name: '业务编排' })).toBeVisible();
    await expect(page.locator('.sa-tree-scene.is-active')).toContainText('发票与报销');
    await expect(page.locator('.sa-canvas-head')).toContainText('发票与报销');
    await expect(page.locator('.sa-orchestration-readiness .sa-readiness-state')).toContainText('配置不完整');
});

test('readiness failure disables publishing and retry recovers the gate', async ({ page }) => {
    let allowReady = false;
    let readinessCalls = 0;
    await mockConsoleApi(page);
    await page.route('**/api/v1/service-apps/consumer-service/readiness', route => {
        readinessCalls += 1;
        if (!allowReady) {
            return route.fulfill({ status: 500, json: { detail: 'readiness unavailable' } });
        }
        return route.fulfill({ json: buildApplicationReadiness('ready') });
    });

    await page.goto('/#/service-apps/consumer-service');
    await expect(page.locator('.sa-tree-scene')).toHaveCount(6);
    await expect(page.getByText('完整性检查加载失败')).toBeVisible();

    const topPublish = page.locator('.sa-app-actions').getByRole('button', { name: '发布新版本' });
    await expect(topPublish).toBeDisabled();
    await openDeploy(page);
    await expect(page.locator('.sa-deploy-hero').getByRole('button', { name: '发布新版本' })).toBeDisabled();
    await expect(page.locator('.sa-release-foot').getByRole('button', { name: /发布新版本/ })).toBeDisabled();
    await expect(page.locator('.sa-release-gate-state.error')).toContainText('完整性检查不可用，暂不能发布。');

    allowReady = true;
    await page.getByRole('button', { name: '重试' }).click();
    await expect.poll(() => readinessCalls).toBeGreaterThanOrEqual(2);
    await expect(page.getByText('完整性检查加载失败')).toHaveCount(0);
    await expect(page.locator('.sa-deploy-hero').getByRole('button', { name: '发布新版本' })).toBeEnabled();
    await expect(page.locator('.sa-release-foot').getByRole('button', { name: /发布新版本/ })).toBeEnabled();
    await expect(topPublish).toBeEnabled();
});

test('handoff workbench supports search, status filters and conversation detail without browser errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on('console', message => {
        if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', error => pageErrors.push(error.message));

    await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        const path = url.pathname.replace('/api/v1', '');
        if (path === '/me') {
            return route.fulfill({ json: { role: 'admin', tenant: '演示企业', actor: 'admin', permissions: [] } });
        }
        if (path === '/extensions/ui') return route.fulfill({ json: [] });
        if (path === '/extensions/capabilities') return route.fulfill({ json: { capabilities: { items: [] } } });
        if (path === '/modules') return route.fulfill({ json: [] });
        if (path === '/observability/summary') return route.fulfill({ json: {} });
        if (path === '/handoffs') {
            return route.fulfill({
                json: [
                    {
                        id: 'handoff-1',
                        conversation_id: 'conv-1',
                        external_id: 'HO-001',
                        reason: '物流异常需要人工核查',
                        summary: '客户反馈物流三天没有更新，希望确认包裹位置。',
                        status: 'waiting',
                        assignee: null,
                        revision: 3,
                        created_at: '2026-11-02T01:00:00Z',
                        updated_at: '2026-11-02T01:10:00Z',
                    },
                    {
                        id: 'handoff-2',
                        conversation_id: 'conv-2',
                        external_id: 'HO-002',
                        reason: '退款问题等待确认',
                        summary: '客户咨询退款到账时间，需要人工核对支付渠道。',
                        status: 'active',
                        assignee: 'admin',
                        revision: 5,
                        created_at: '2026-11-02T00:30:00Z',
                        updated_at: '2026-11-02T01:20:00Z',
                    },
                ],
            });
        }
        if (path === '/conversations/conv-1') {
            return route.fulfill({
                json: {
                    id: 'conv-1',
                    external_id: 'ext-conv-1',
                    mode: 'human',
                    agent_id: 'agent-1',
                    assigned_to: null,
                    customer_id: 'customer-1',
                    business_id: 'business-1',
                    workspace_id: 'workspace-1',
                    source: 'business',
                    updated_at: '2026-11-02T01:10:00Z',
                    messages: [
                        { id: 'message-1', seq: 1, role: 'user', content: '物流为什么没有更新？', created_at: '2026-11-02T01:00:00Z' },
                        { id: 'message-2', seq: 2, role: 'assistant', content: '正在为您核实物流节点。', created_at: '2026-11-02T01:01:00Z' },
                    ],
                    runs: [{ id: 'run-1', conversation_id: 'conv-1', status: 'completed', error_code: null, created_at: '2026-11-02T01:00:30Z' }],
                    actions: [{ id: 'action-1', status: 'pending', payload: { title: '确认补齐收货地址', description: '需要客户确认新的收货地址。' }, expires_at: '2026-11-03T01:00:00Z' }],
                },
            });
        }
        if (path === '/conversations/conv-2') {
            return route.fulfill({
                json: {
                    id: 'conv-2',
                    external_id: 'ext-conv-2',
                    mode: 'human',
                    agent_id: 'agent-1',
                    assigned_to: 'admin',
                    customer_id: 'customer-2',
                    business_id: 'business-2',
                    workspace_id: 'workspace-1',
                    source: 'business',
                    updated_at: '2026-11-02T01:20:00Z',
                    messages: [{ id: 'message-3', seq: 1, role: 'user', content: '退款什么时候到账？', created_at: '2026-11-02T00:30:00Z' }],
                    runs: [],
                    actions: [],
                },
            });
        }
        return route.fulfill({ json: { items: [], total: 0 } });
    });

    await page.goto('/#/handoff');
    await expect(page.locator('.handoff-card')).toHaveCount(2);

    const search = page.getByPlaceholder('搜索交接编号或原因');
    await search.fill('退款');
    await expect(page.locator('.handoff-card')).toHaveCount(1);
    await expect(page.locator('.handoff-card')).toContainText('HO-002');

    await search.clear();
    await page.getByRole('button', { name: /等待接管/ }).first().click();
    await expect(page.locator('.handoff-card')).toHaveCount(1);
    await expect(page.locator('.handoff-card')).toContainText('HO-001');
    await expect(page.locator('.handoff-detail')).toContainText('物流异常需要人工核查');
    await expect(page.locator('.handoff-detail')).toContainText('客户信息');
    await expect(page.locator('.handoff-detail')).toContainText('物流为什么没有更新？');

    await page.getByRole('button', { name: /我的处理中/ }).click();
    await expect(page.locator('.handoff-card')).toHaveCount(1);
    await expect(page.locator('.handoff-card')).toContainText('HO-002');
    await expect(page.locator('.handoff-detail')).toContainText('退款什么时候到账？');

    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
});
