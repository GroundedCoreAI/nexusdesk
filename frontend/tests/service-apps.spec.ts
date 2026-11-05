import { expect, test } from '@playwright/test';
import { mockConsoleApi } from './serviceApiFixtures';

test('service application combines orchestration, capabilities and backend debugging', async ({ page }) => {
    const simulations: unknown[] = [];
    await mockConsoleApi(page, { onSimulate: body => simulations.push(body) });
    await page.goto('/#/service-apps');
    await expect(page.locator('.console-heading h1')).toHaveText('服务应用');
    await expect(page.getByRole('heading', { name: '购物消费服务应用' })).toBeVisible();
    await page.screenshot({ path: 'test-results/service-app-catalog.png', fullPage: true });

    await page.getByRole('button', { name: /购物消费服务应用/ }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service$/);
    await expect(page.locator('.console-heading h1')).toHaveText('购物消费服务应用');
    await expect(page.getByRole('heading', { name: '业务编排' })).toBeVisible();
    await expect(page.locator('.sa-tree-scene')).toHaveCount(6);
    await expect(page.getByText('Agent 是应用引用的执行资源', { exact: false })).toBeVisible();
    await page.screenshot({ path: 'test-results/service-app-orchestration.png', fullPage: true });

    await page.getByRole('button', { name: '执行能力', exact: true }).click();
    await expect(page.getByText('Agent 不是应用内部配置', { exact: true })).toBeVisible();
    await expect(page.getByText('购物消费助手', { exact: true })).toBeVisible();
    await expect(page.getByText('service-tracking', { exact: false })).toBeVisible();

    await page.getByRole('button', { name: '接入与发布', exact: true }).click();
    await expect(page.getByText('官网帮助中心', { exact: true })).toBeVisible();
    await expect(page.getByText('当前生产版本 v8', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: '调试', exact: true }).first().click();
    await expect(page.getByText('SERVER TRACE', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /运行服务端模拟/ })).toBeVisible();
    await page.getByRole('button', { name: /运行服务端模拟/ }).click();
    await expect(page.locator('.sa-result-inline p').filter({ hasText: '已由发票与报销处理后端模拟请求。' })).toBeVisible();
    await expect(page.locator('.sa-debug-head small')).toHaveText('trace-e2e-20261101');
    expect(simulations).toHaveLength(1);
    await page.screenshot({ path: 'test-results/service-app-studio.png', fullPage: true });
});

test('capability and customer channel edits are persisted through the application API', async ({ page }) => {
    const updates: any[] = [];
    await mockConsoleApi(page, { onUpdateApp: body => updates.push(body) });
    await page.goto('/#/service-apps/consumer-service');

    await page.getByRole('button', { name: '执行能力', exact: true }).click();
    await page.getByRole('button', { name: /添加执行能力/ }).click();
    await page.getByLabel('展示名称').fill('订单查询代理');
    await page.getByLabel('能力标识').fill('order-query-agent');
    await page.getByRole('button', { name: '添加能力', exact: true }).click();
    await expect.poll(() => updates.length).toBe(1);
    expect(updates[0].config.capabilities.some((item: any) => item.key === 'order-query-agent')).toBeTruthy();

    await page.getByRole('button', { name: '接入与发布', exact: true }).click();
    await page.getByRole('button', { name: /添加触点/ }).click();
    await page.getByLabel('触点名称').fill('App 客户端');
    await page.getByLabel('触点标识').fill('app-client');
    await page.getByRole('button', { name: '添加触点', exact: true }).last().click();
    await expect.poll(() => updates.length).toBe(2);
    expect(updates[1].config.channels.some((item: any) => item.key === 'app-client')).toBeTruthy();
});

test('advanced settings sit after deploy and open the active scenario', async ({ page }) => {
    await mockConsoleApi(page);
    await page.goto('/#/service-apps/consumer-service');

    const tabs = page.locator('.sa-studio-tabs button');
    await expect(tabs.nth(4)).toHaveText('接入与发布');
    await expect(tabs.nth(5)).toContainText('高级设置');
    await page.getByRole('button', { name: '高级设置', exact: true }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/scenarios\/invoice$/);
    await expect(page.locator('.sa-app-bar')).toBeVisible();
    await expect(tabs.nth(5)).toHaveClass(/is-active/);
    await expect(page.locator('.scene-embedded-toolbar')).toBeVisible();
    await expect(page.locator('.scenario-topline')).toHaveCount(0);
    await expect(page.locator('.scenario-subnav')).toHaveCount(0);
    await page.screenshot({ path: 'test-results/service-app-advanced-settings.png', fullPage: true });

    await page.getByRole('button', { name: '接入与发布', exact: true }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service$/);
    await expect(page.getByText('官网帮助中心', { exact: true })).toBeVisible();
});

test('service application mobile layout does not overflow horizontally', async ({ page }) => {
    await mockConsoleApi(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/#/service-apps/consumer-service');
    await expect(page.getByRole('heading', { name: '业务编排' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('admin creates a service application from the catalog and opens it', async ({ page }) => {
    let requestBody: unknown;
    await mockConsoleApi(page, { onCreate: body => { requestBody = body; } });
    await page.goto('/#/service-apps');

    await page.getByRole('button', { name: '新建服务应用' }).first().click();
    await page.getByLabel('应用名称').fill('账号安全服务应用');
    await page.getByLabel('应用标识').fill('account-service');
    await page.getByLabel('应用描述').fill('处理登录、密码与账号安全相关服务');
    await page.getByRole('button', { name: '创建应用', exact: true }).click();

    await expect(page).toHaveURL(/#\/service-apps\/account-service$/);
    await expect(page.locator('.console-heading h1')).toHaveText('账号安全服务应用');
    await expect(page.locator('.sa-app-title-line h2')).toHaveText('账号安全服务应用');
    await expect(page.getByText('账号安全服务应用 已创建', { exact: true })).toBeVisible();
    await page.screenshot({ path: 'test-results/service-app-empty.png', fullPage: true });
    expect(requestBody).toEqual({
        key: 'account-service',
        config: {
            schema_version: 'v1',
            name: '账号安全服务应用',
            description: '处理登录、密码与账号安全相关服务',
            service_categories: [],
            scenarios: [],
            capabilities: [],
            default_execution_order: ['deterministic', 'action', 'agent', 'human'],
            channels: [],
        },
    });
});

test('new scenarios select a category from the application service catalog', async ({ page }) => {
    const created: any[] = [];
    await mockConsoleApi(page, { onScenarioCreate: body => created.push(body) });
    await page.goto('/#/service-apps/consumer-service');

    await page.getByRole('button', { name: '新建场景' }).click();
    const create = page.getByRole('dialog', { name: '新建服务场景' });
    await create.getByLabel('场景名称').fill('查询开具进度');
    await create.getByLabel('场景标识').fill('invoice-progress');
    const category = create.getByRole('combobox', { name: '服务目录' });
    await category.click();
    await category.fill('售后服务');
    await category.press('Enter');
    await create.getByRole('button', { name: '创建并配置', exact: true }).click();

    await expect.poll(() => created.length).toBe(1);
    expect(created[0].config.category).toBe('售后服务');
    expect(created[0].config.category).not.toBe('通用服务');
});

test('service catalog supports reorder, rename and merge through one revisioned request', async ({ page }) => {
    const updates: any[] = [];
    await mockConsoleApi(page, { onCatalogUpdate: body => updates.push(body) });
    await page.goto('/#/service-apps/consumer-service');

    await page.getByRole('button', { name: '服务目录', exact: true }).click();
    const catalog = page.getByRole('dialog', { name: '服务目录' });
    await expect(catalog).toBeVisible();

    await catalog.getByRole('button', { name: '下移 订单服务' }).click();
    await catalog.getByLabel('分类名称 发票服务').fill('发票与报销');
    await catalog.getByRole('button', { name: '合并 投诉反馈' }).click();

    const merge = page.getByRole('dialog', { name: '合并服务分类' });
    await merge.getByRole('combobox', { name: '合并目标分类' }).click();
    await page.locator('.ant-select-dropdown:visible').getByText('订单服务', { exact: true }).click();
    await merge.getByRole('button', { name: '确认合并', exact: true }).click();
    await catalog.getByRole('button', { name: '保存目录', exact: true }).click();

    await expect.poll(() => updates.length).toBe(1);
    expect(updates[0].revision).toBe(8);
    expect(updates[0].categories.map((item: any) => item.name)).toEqual([
        '售后服务',
        '订单服务',
        '发票与报销',
        '规则与知识',
    ]);
    expect(updates[0].categories.map((item: any) => item.order)).toEqual([10, 20, 30, 40]);
    expect(updates[0].category_changes).toEqual({
        '发票服务': '发票与报销',
        '投诉反馈': '订单服务',
    });
});
