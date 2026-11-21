import { test, expect } from '@playwright/test';

test('unconfigured model guides setup, allows draft saving and blocks publishing', async ({ page }) => {
  const mutations: string[] = [];
  const agent = { id: 'agent-1', name: '待配置助手', description: '', draft: { system_prompt: 'test', tool_names: [], knowledge_base_ids: [], max_model_rounds: 6, model_profile_id: null, model_profile_version: null }, draft_revision: 1, published_version: null, archived: false };
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (request.method() !== 'GET') mutations.push(path);
    if (path === '/me') return route.fulfill({ json: { role: 'admin', tenant: 'test' } });
    if (path === '/agents/catalog') return route.fulfill({ json: { items: [agent], total: 1, page: 1, page_size: 12 } });
    if (path === '/agents/agent-1' && request.method() === 'PUT') return route.fulfill({ json: { ...agent, name: request.postDataJSON().name, draft_revision: 2 } });
    if (path === '/agents/agent-1') return route.fulfill({ json: agent });
    if (path.startsWith('/model-gateway/catalog/')) return route.fulfill({ json: { items: [], total: 0 } });
    if (['/tools', '/knowledge-bases', '/modules'].includes(path)) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  // AuthBoundary treats a bare `/` as the login route; open the editor's hash
  // route directly so the mocked /me session is actually exercised.
  await page.goto('/#/agents/agent-1/config');
  await expect(page.getByRole('option', { name: '部署默认模型' })).toHaveCount(0);
  await expect(page.getByText('尚未配置模型：', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: /发\s*布/, exact: true }).click();
  // useAction raises both an inline alert and a toast, both with role="alert";
  // assert the durable inline one (same pattern as gateway-fullstack.spec.ts).
  await expect(page.locator('.alert.error').filter({ hasText: '请先选择已发布的 Chat 配置方案' })).toBeVisible();
  expect(mutations).toEqual([]);
  await page.getByLabel('Agent 名称').fill('草稿助手');
  await page.getByRole('button', { name: /保\s*存/, exact: true }).click();
  await expect.poll(() => mutations).toEqual(['/agents/agent-1']);
  await page.getByRole('button', { name: '前往模型网关配置', exact: true }).click();
  await expect(page.getByRole('button', { name: '新建配置方案', exact: true })).toBeVisible();
});

/**
 * P7 D-1 parity, UI half: the backend model gate is React-only, so a CLI engine
 * must not be held back by the frontend's unconditional "choose a Chat profile"
 * check. This is the "无法发布 Agent" blocker of the published-Agent defect set.
 */
test('a Codex engine agent publishes without a platform Chat model profile', async ({ page }) => {
  const mutations: string[] = [];
  const agent = {
    id: 'agent-1', name: 'Codex 助手', description: '',
    draft: {
      system_prompt: 'test', tool_names: [], knowledge_base_ids: [], max_model_rounds: 6,
      model_profile_id: null, model_profile_version: null,
      engine: { engine_id: 'codex', protocol_id: 'cli_exec', adapter_version: 'v1' },
      codex: {
        protocol: 'cli_exec', version: '0.169.0', executable: 'codex', timeout_seconds: 600,
        approval_mode: 'never', sandbox_mode: 'read-only', credential_ref: null,
        path_env: '/usr/local/bin:/usr/bin:/bin',
      },
    },
    draft_revision: 1, published_version: null, archived: false,
  };
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (request.method() !== 'GET') mutations.push(`${request.method()} ${path}`);
    if (path === '/me') return route.fulfill({ json: { role: 'admin', tenant: 'test' } });
    if (path === '/agents/execution-config-flags') return route.fulfill({ json: { execution_phase3_enabled: true, execution_orchestrator_enabled: true } });
    if (path === '/agents/memory-config-caps') return route.fulfill({ json: { summary_enabled: true, memory_inject_enabled: true, memory_extract_enabled: true, memory_inject_max_items: 20, memory_search_limit: 5, memory_blacklist_auto_handoff: false } });
    if (path === '/agents/agent-1/publish' && request.method() === 'POST') return route.fulfill({ json: { ...agent, published_version: 1 } });
    if (path === '/agents/catalog') return route.fulfill({ json: { items: [{ ...agent, published_version: 1 }], total: 1, page: 1, page_size: 12 } });
    if (path === '/agents/agent-1') return route.fulfill({ json: { ...agent, published_version: 1 } });
    if (path === '/agents/agent-1/evaluation-reports') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 1, versions: [] } });
    if (path.startsWith('/model-gateway/catalog/')) return route.fulfill({ json: { items: [], total: 0 } });
    if (['/tools', '/knowledge-bases', '/modules'].includes(path)) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  await page.goto('/#/agents/agent-1/config');
  // The React-only model picker is not offered to a CLI engine.
  await expect(page.getByLabel('Chat 模型方案')).toHaveCount(0);
  await expect(page.getByText('此处无需绑定 Chat 方案', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: /发\s*布/, exact: true }).click();
  await expect.poll(() => mutations).toContain('POST /agents/agent-1/publish');
  await expect(page.getByText('请先选择已发布的 Chat 配置方案')).toHaveCount(0);
  await expect(page.locator('.agent-workspace > .alert.success')).toContainText('当前配置已保存并发布');
});
