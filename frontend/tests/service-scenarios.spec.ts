import { expect, test } from '@playwright/test';
import { mockConsoleApi } from './serviceApiFixtures';

test('service scenarios are managed inside their owning application', async ({ page }) => {
    await mockConsoleApi(page);
    await page.goto('/#/service-apps/consumer-service');
    await expect(page.locator('.console-heading h1')).toHaveText('购物消费服务应用');
    await expect(page.locator('.console-nav .nav-selected')).toHaveText('服务应用');
    await expect(page.getByRole('button', { name: '服务场景', exact: true })).toHaveCount(0);
    await expect(page.locator('.sa-tree-scene')).toHaveCount(6);

    await page.locator('.sa-tree-scene').filter({ hasText: '查询我的订单' }).click();
    await page.getByRole('button', { name: '打开场景高级配置' }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/scenarios\/query-orders$/);
    await expect(page.locator('.console-heading h1')).toHaveText('查询我的订单');
    await expect(page.locator('.console-nav .nav-selected')).toHaveText('服务应用');
    await expect(page.getByText('关联 Agent · 复杂问题与查询失败时启用')).toBeVisible();

    await page.getByRole('button', { name: '模拟与决策', exact: true }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/scenarios\/query-orders\/simulator$/);
    await expect(page.locator('.console-heading h1')).toHaveText('场景模拟器');
    await page.getByRole('button', { name: '运行模拟', exact: true }).click();
    await expect(page.locator('.simulator-agent-card p').filter({ hasText: '已由查询我的订单处理后端模拟请求。' })).toBeVisible();

    await page.getByRole('button', { name: '客户端预览', exact: true }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/scenarios\/query-orders\/customer$/);
    await expect(page.locator('.console-heading h1')).toHaveText('客户端交互预览');
    await expect(page.locator('.customer-phone')).toHaveCount(2);
});

test('the standalone service scenario route is removed without a redirect', async ({ page }) => {
    await mockConsoleApi(page);
    await page.goto('/#/service-scenarios');
    await expect(page).toHaveURL(/#\/overview$/);
    await expect(page.locator('.console-heading h1')).toHaveText('平台总览');
    await expect(page.getByRole('button', { name: '服务场景', exact: true })).toHaveCount(0);
});

test('unified customer experience is scoped to one service application', async ({ page }) => {
    await mockConsoleApi(page);
    await page.goto('/#/service-apps/consumer-service');
    await page.getByRole('button', { name: '统一体验', exact: true }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/experience$/);
    await expect(page.locator('.console-heading h1')).toHaveText('客户统一体验');
    await expect(page.getByRole('heading', { name: '你好，我是购物消费服务应用服务助手' })).toBeVisible();

    await page.getByRole('button', { name: /查询我的订单/ }).first().click();
    await expect(page.locator('.cx-message-bubble').filter({ hasText: '已进入「查询我的订单」' })).toHaveCount(1);
    await page.getByRole('button', { name: '选择订单 SIM-ORDER-20261031' }).click();
    await expect(page.locator('.cx-context-chip.order')).toContainText('SIM-ORDER-20261031');
    await expect(page.locator('.cx-result-lead').filter({ hasText: '已由查询我的订单处理后端模拟请求。' })).toBeVisible();

    await page.locator('.cx-topbar-actions').getByRole('button', { name: '决策解释' }).click();
    await expect(page.getByText('这次服务如何被处理', { exact: true })).toBeVisible();
    await expect(page.getByText('消息命中服务场景「查询我的订单」', { exact: true })).toBeVisible();
});

test('agent detail links scene references back into the owning application', async ({ page }) => {
    await mockConsoleApi(page);
    await page.goto('/#/agents/agent-1/config');
    await expect(page.getByLabel('Agent 名称')).toHaveValue('购物消费助手');
    await page.getByRole('button', { name: '使用场景', exact: true }).click();
    await expect(page).toHaveURL(/#\/agents\/agent-1\/usage$/);
    await expect(page.getByRole('heading', { name: '被以下服务场景使用' })).toBeVisible();
    await expect(page.locator('.agent-usage-row')).toHaveCount(3);
    await expect(page.getByText('服务场景与 Agent 是引用关系')).toBeVisible();

    await page.locator('.agent-usage-row').first().click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/scenarios\/query-orders$/);
    await expect(page.locator('.console-heading h1')).toHaveText('查询我的订单');
});

test('service scenario mobile pages stay inside the application without horizontal overflow', async ({ page }) => {
    await mockConsoleApi(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/#/service-apps/consumer-service/scenarios/query-orders');
    await expect(page.locator('.scene-workbench-grid')).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.goto('/#/service-apps/consumer-service/scenarios/query-orders/customer');
    await expect(page.locator('.customer-phone')).toHaveCount(2);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

    await page.goto('/#/service-apps/consumer-service/experience');
    await expect(page.getByRole('heading', { name: '你好，我是购物消费服务应用服务助手' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
