import { test, expect, type Page } from '@playwright/test';

async function openShell(page: Page, extensionManifests: object[] = []) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/me') return route.fulfill({ json: { role: 'admin', tenant: '测试企业', permissions: [] } });
    if (path === '/extensions/ui') return route.fulfill({ json: extensionManifests });
    if (path === '/modules' || path === '/tickets') return route.fulfill({ json: [] });
    if (path === '/agents/catalog') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 12 } });
    if (path.startsWith('/model-gateway/catalog/')) return route.fulfill({ json: { items: [], total: 0 } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/#/overview');
  await expect(page.getByRole('navigation')).toBeAttached();
}

test('business catalog is honest and service groups contain their real routes', async ({ page }) => {
  await openShell(page);
  const navigation = page.getByRole('navigation');
  await expect(navigation.getByRole('button', { name: '工作台', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(navigation.getByRole('button', { name: 'Agent 管理', exact: true })).toHaveCount(0);

  await navigation.getByRole('button', { name: 'AI 员工', exact: true }).click();
  await expect(navigation.getByRole('button', { name: '员工团队', exact: true })).toBeDisabled();
  await expect(navigation.getByRole('button', { name: '发布与版本', exact: true })).toBeDisabled();
  await navigation.getByRole('button', { name: 'Agent 管理', exact: true }).click();
  await expect(page).toHaveURL(/#\/agents$/);
  await expect(navigation.getByRole('button', { name: 'Agent 管理', exact: true })).toHaveAttribute('aria-current', 'page');

  await page.getByRole('button', { name: '切换业务：AI 客服', exact: true }).click();
  await expect(page.getByRole('menuitem', { name: /AI 客服/ })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: /AI 财务运营/ })).toBeDisabled();
  await expect(page.getByRole('menuitem', { name: /AI 销售/ })).toBeDisabled();
  await page.keyboard.press('Escape');
});

test('planned capabilities reserve their positions without creating routes', async ({ page }) => {
  await openShell(page);
  const navigation = page.getByRole('navigation');
  await expect(navigation.getByRole('button', { name: '数据分析', exact: true })).toBeDisabled();

  await navigation.getByRole('button', { name: '任务中心', exact: true }).click();
  await expect(navigation.getByRole('button', { name: '全部任务', exact: true })).toBeDisabled();
  await expect(navigation.getByRole('button', { name: '执行记录', exact: true })).toBeDisabled();
  await expect(navigation.getByRole('button', { name: '审批与待办', exact: true })).toBeDisabled();

  await navigation.getByRole('button', { name: '资源中心', exact: true }).click();
  for (const name of ['知识库', '工具目录', '模型网关', 'Skill 能力库']) {
    await expect(navigation.getByRole('button', { name, exact: true })).toBeEnabled();
  }
  for (const name of ['Workflow', 'Connector']) {
    await expect(navigation.getByRole('button', { name, exact: true })).toBeDisabled();
  }

  await navigation.getByRole('button', { name: '运营中心', exact: true }).click();
  await expect(navigation.getByRole('button', { name: '质量评估', exact: true })).toBeEnabled();
  await expect(navigation.getByRole('button', { name: '运行监控与审计', exact: true })).toBeEnabled();
  await expect(navigation.getByRole('button', { name: '成本分析', exact: true })).toBeDisabled();
  await expect(page).toHaveURL(/#\/overview$/);
});

test('dynamic task extensions remain available', async ({ page }) => {
  await openShell(page, [{
    extensionId: 'approval',
    navigation: [{ id: 'approvals', labelKey: '审批工作台', path: '/approvals', group: 'approval' }],
    routes: [{ path: '/approvals', feature: 'approval/workbench' }],
  }]);
  const navigation = page.getByRole('navigation');

  await navigation.getByRole('button', { name: '任务中心', exact: true }).click();
  await expect(navigation.getByRole('button', { name: '全部任务', exact: true })).toHaveCount(0);
  await navigation.getByRole('button', { name: '审批工作台', exact: true }).click();
  await expect(page).toHaveURL(/#\/approvals$/);
});

test('existing plugin management remains available to administrators', async ({ page }) => {
  await openShell(page);
  const navigation = page.getByRole('navigation');
  await navigation.getByRole('button', { name: '系统管理', exact: true }).click();
  await navigation.getByRole('button', { name: '插件与扩展', exact: true }).click();
  await expect(page).toHaveURL(/#\/extensions$/);
});

test('resource navigation and desktop icon mode preserve access to the gateway', async ({ page }) => {
  await openShell(page);
  const navigation = page.getByRole('navigation');
  await navigation.getByRole('button', { name: '资源中心', exact: true }).click();
  await navigation.getByRole('button', { name: '模型网关', exact: true }).click();
  await expect(page).toHaveURL(/#\/models\/models$/);

  await page.locator('.console-sidebar-collapse').click();
  await expect(page.locator('.console-sider')).toHaveClass(/ant-layout-sider-collapsed/);
  await expect(page.locator('.console-sider')).toHaveCSS('width', '72px');
  await navigation.getByRole('button', { name: '工作台', exact: true }).click();
  await expect(page).toHaveURL(/#\/overview$/);
  await expect(page.locator('.console-sider')).toHaveClass(/ant-layout-sider-collapsed/);
  await navigation.getByRole('button', { name: '资源中心', exact: true }).click();
  await expect(page.locator('.console-sider')).not.toHaveClass(/ant-layout-sider-collapsed/);
  await expect(navigation.getByRole('button', { name: '模型网关', exact: true })).toBeVisible();
});

test('Open platform remains reachable from the Skill workspace sidebar', async ({ page }) => {
  await openShell(page);
  await page.goto('/#/skills');
  const navigation = page.getByRole('navigation');
  const openPlatform = navigation.getByRole('button', { name: '开放平台', exact: true });

  await expect(openPlatform).toBeVisible();
  await openPlatform.scrollIntoViewIfNeeded();
  await expect(openPlatform).toBeInViewport();
  await openPlatform.click();

  await expect(page).toHaveURL(/#\/open-platform$/);
  await expect(navigation.getByRole('button', { name: '开放平台', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('Skill and other workspaces share the same sidebar structure and styling', async ({ page }) => {
  await openShell(page);

  async function snapshot(path: string) {
    await page.goto(path);
    await expect(page.getByRole('navigation')).toBeVisible();
    await page.waitForTimeout(250);
    return page.evaluate(() => {
      const read = (selector: string) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const style = getComputedStyle(element);
        return {
          display: style.display,
          backgroundImage: style.backgroundImage,
          padding: style.padding,
          gap: style.gap,
          height: style.height,
        };
      };
      return {
        width: document.querySelector('.console-sider')?.getBoundingClientRect().width,
        sider: read('.console-sider'),
        switcher: read('.business-switcher.ant-btn'),
        navButton: read('.console-nav .ant-btn'),
        groupTitle: read('.console-nav .nav-group-title'),
        footer: read('.console-sidebar-footer'),
        rootLabels: Array.from(document.querySelectorAll('.console-nav-section > .console-nav-item > .ant-btn'))
          .map(element => element.getAttribute('aria-label')),
      };
    });
  }

  const overview = await snapshot('/#/overview');
  const skills = await snapshot('/#/skills');

  expect(skills.width).toBe(228);
  expect(skills.rootLabels).toEqual(overview.rootLabels);
  expect(skills.sider).toEqual(overview.sider);
  expect(skills.switcher).toEqual(overview.switcher);
  expect(skills.navButton).toEqual(overview.navButton);
  expect(skills.groupTitle).toEqual(overview.groupTitle);
  expect(skills.footer).toEqual(overview.footer);
});

test('mobile navigation behaves as a modal drawer and closes after routing', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openShell(page);
  await expect(page.locator('.console-sider')).toHaveClass(/ant-layout-sider-collapsed/);
  await page.getByRole('button', { name: '展开导航', exact: true }).click();
  await expect(page.locator('.console-sidebar-mask')).toBeVisible();
  await expect(page.locator('.console-nav .nav-label').first()).toBeVisible();
  await page.getByRole('navigation').getByRole('button', { name: '服务工单', exact: true }).click();
  await expect(page).toHaveURL(/#\/tickets$/);
  await expect(page.locator('.console-sider')).toHaveClass(/ant-layout-sider-collapsed/);
  await expect(page.locator('.console-sidebar-mask')).toHaveCount(0);
});
