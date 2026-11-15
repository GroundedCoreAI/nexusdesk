import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Phase 3 · T9 — execution config, capability preview and four-locale evidence.
// docs/requirement/agent-execution-platform-v2/phase-3-capability-config-instructions/
//   02-requirements.md  FR-1 / FR-5 / FR-8, AC-1 / AC-2 / AC-9
//   04-test-plan.md     §6.1 frontend evidence, P3-CM-08
//   05-acceptance-plan.md  A9 and M1–M3
// Everything below runs against a mocked `/api/v1/**`: it is contract-level UI
// evidence, not an end-to-end proof that the real preview endpoint behaves.

type Dict = Record<string, string>;
// Resolved next to this file so the dictionaries load regardless of the cwd
// Playwright was started from.
const locale = (name: string) => JSON.parse(readFileSync(fileURLToPath(new URL(`../src/i18n/locales/${name}.json`, import.meta.url)), 'utf8')) as Dict;
const DICTIONARIES: Record<string, Dict> = {
  'zh-CN': locale('zh-CN'),
  'zh-TW': locale('zh-TW'),
  en: locale('en'),
  hi: locale('hi'),
};
/** Text of `key` in the given UI language; fails when a locale lacks the key. */
function tr(language: string, key: string): string {
  const value = DICTIONARIES[language]?.[key];
  expect(value, `locale ${language} is missing the key ${key}`).toBeTruthy();
  return value;
}

const CAPABILITIES = [
  'streaming',
  'persistent_session',
  'session_resume',
  'cancellation',
  'human_approval',
  'interactive_input',
  'tool_calling',
  'file_operations',
  'terminal_execution',
  'native_events',
  'workspace_required',
];
const ENGINE = { engine_id: 'react', protocol_id: 'native', adapter_version: 'v1' };
const CAPS = {
  summary_enabled: true, memory_inject_enabled: true, memory_extract_enabled: true,
  memory_inject_max_items: 20, memory_search_limit: 5, memory_blacklist_auto_handoff: false,
};
// GET /agents/execution-config-flags (03 §7.4): exactly the two booleans, named
// verbatim like the backend settings. Both on is the regular deployment state,
// so the pre-existing cases keep exercising the Phase 3 entries.
const FLAGS = { execution_phase3_enabled: true, execution_orchestrator_enabled: true };
// One stored conversation with one finished Run, used only by the M3
// "history and Run stay viewable" cases (P3-FE-20/21).
const RECORD = {
  id: 'conv-record',
  external_id: 'record-run-1',
  mode: 'bot',
  agent_id: 'agent-1',
  assigned_to: null,
  source: 'playground',
  last_message: '记录里的最后一条回答',
  updated_at: '2026-10-02T00:00:00Z',
};
const RECORD_ANSWER = '历史运行给出的回答';
const RECORD_RUN_ID = 'run-record';
/**
 * `GET /runs/{run-record}/events` as the backend sends it: SSE frames ended by
 * `run.completed`, so the reader stops instead of reconnecting (05 M3 asserts a
 * past Run can still be opened, which needs a stream that actually finishes).
 */
const RUN_EVENT_STREAM = [
  'id: 1',
  'event: model.completed',
  'data: {"round":1,"tool_calls":0,"duration_ms":120,"first_token_ms":30,"usage":{"total_tokens":42}}',
  '',
  'id: 2',
  'event: run.completed',
  'data: {"status":"completed"}',
  '',
  '',
].join('\n');

/** A Phase 0 / Phase 2 draft: no `engine`, no `react`, no `disabled_capabilities`. */
function legacyDraft(overrides: Record<string, unknown> = {}) {
  return {
    system_prompt: '你是一位专业的售后客服。',
    tool_names: [],
    knowledge_base_ids: [],
    max_model_rounds: 6,
    model_profile_id: '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f',
    model_profile_version: 3,
    reply_language: 'auto',
    summary_enabled: true,
    memory_enabled: true,
    memory_read_enabled: true,
    memory_write: true,
    memory_types: ['profile', 'preference', 'event'],
    memory_search_enabled: true,
    memory_write_mode: 'auto',
    memory_inject_max_items: null,
    memory_search_limit: null,
    memory_blacklist_auto_handoff: false,
    ...overrides,
  };
}

/** Preview response shaped exactly like 03-technical-design.md §7.2. */
function previewBody(reasons: Record<string, string> = {}) {
  return {
    engine: ENGINE,
    config_schema: {
      schema_version: 'v1',
      fields: [
        { name: 'model_profile_id', type: 'string', required: false },
        { name: 'max_model_rounds', type: 'integer', required: true },
      ],
    },
    capabilities: CAPABILITIES.map(name => ({
      name,
      reason_code: reasons[name] ?? 'allowed',
      effective: !reasons[name],
    })),
  };
}

interface Options {
  role?: string;
  draft?: Record<string, unknown>;
  preview?: () => unknown;
  previewStatus?: number;
  /** Response body the preview endpoint answers with on `previewStatus`. */
  previewError?: unknown;
  saveStatus?: number;
  /** Response body the draft PUT answers with on `saveStatus`. */
  saveError?: unknown;
  onSave?: (config: Record<string, unknown>) => void;
  /** Deployment switches the flags endpoint answers with; defaults to both on. */
  flags?: { execution_phase3_enabled: boolean; execution_orchestrator_enabled: boolean };
  /** Status code the flags endpoint answers with, to exercise fail-closed gating. */
  flagsStatus?: number;
}

interface Harness {
  /** Every `/api/v1` call the page issued, as `METHOD /path`. */
  calls: string[];
  /** Bodies posted to the preview endpoint. */
  previews: Record<string, unknown>[];
  /** Bodies put to the agent draft. */
  saves: Record<string, unknown>[];
}

async function editor(page: import('@playwright/test').Page, options: Options): Promise<Harness> {
  const role = options.role ?? 'admin';
  const harness: Harness = { calls: [], previews: [], saves: [] };
  let agent: Record<string, unknown> = {
    id: 'agent-1', name: '售后服务助手', description: '解答产品问题',
    draft: options.draft ?? legacyDraft(), draft_revision: 1, published_version: 1,
    archived: false, updated_at: '2026-10-01T00:00:00Z',
  };
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    harness.calls.push(`${method} ${path}`);
    if (path === '/me') return route.fulfill({ json: { role, tenant: '测试企业' } });
    if (path === '/agents/memory-config-caps') return route.fulfill({ json: CAPS });
    if (path === '/agents/execution-config-flags') {
      if (options.flagsStatus) {
        return route.fulfill({ status: options.flagsStatus, json: { detail: 'database_unavailable' } });
      }
      return route.fulfill({ json: options.flags ?? FLAGS });
    }
    if (path === '/agents/execution-preview') {
      harness.previews.push(request.postDataJSON() as Record<string, unknown>);
      if (options.previewStatus) {
        return route.fulfill({ status: options.previewStatus, json: { detail: options.previewError ?? 'execution_phase3_disabled' } });
      }
      return route.fulfill({ json: options.preview ? options.preview() : previewBody() });
    }
    if (path === '/agents/catalog') {
      return route.fulfill({ json: { items: [agent], total: 1, page: 1, page_size: 12 } });
    }
    if (path === '/agents/agent-1' && method === 'PUT') {
      const body = request.postDataJSON() as Record<string, unknown>;
      harness.saves.push(body);
      if (options.saveStatus) {
        return route.fulfill({ status: options.saveStatus, json: { detail: options.saveError ?? 'execution_engine_unavailable' } });
      }
      // Mirrors the real service: the stored draft is the validated model, so it
      // carries the canonical execution fields plus the legacy root aliases.
      const config = body.config as Record<string, unknown>;
      const react = (config.react ?? {}) as Record<string, unknown>;
      const canonical = {
        ...config,
        engine: config.engine ?? ENGINE,
        react: {
          model_profile_id: react.model_profile_id ?? config.model_profile_id ?? null,
          model_profile_version: react.model_profile_version ?? config.model_profile_version ?? null,
          max_model_rounds: react.max_model_rounds ?? config.max_model_rounds ?? 6,
        },
        disabled_capabilities: config.disabled_capabilities ?? [],
      };
      agent = { ...agent, name: body.name, description: body.description, draft: canonical, draft_revision: 2 };
      return route.fulfill({ json: agent });
    }
    if (path === '/agents/agent-1') return route.fulfill({ json: agent });
    if (path === '/agents/agent-1/versions') {
      return route.fulfill({ json: [{ version: 1, created_at: '2026-10-01T00:00:00Z' }] });
    }
    if (path.startsWith('/agents/agent-1/diff')) {
      return route.fulfill({ json: { changes: [] } });
    }
    if (path === '/agents/agent-1/evaluation-reports') {
      return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 1, versions: [] } });
    }
    // Read-only history/Run views (05 M3, P3-FE-20/21). These stay mocked like
    // everything else, and only for the record view's own endpoints — the
    // catch-all below keeps answering `{}` for any path this spec does not
    // deliberately cover.
    if (path === '/agents/agent-1/conversations') {
      return route.fulfill({ json: { items: [RECORD], total: 1, page: 1, page_size: 12 } });
    }
    if (path === `/conversations/${RECORD.id}`) {
      return route.fulfill({
        json: {
          ...RECORD,
          messages: [
            { id: 'msg-1', seq: 1, role: 'user', content: '历史提问', created_at: '2026-10-02T00:00:01Z', run_id: null },
            { id: 'msg-2', seq: 2, role: 'assistant', content: RECORD_ANSWER, created_at: '2026-10-02T00:00:02Z', run_id: RECORD_RUN_ID },
          ],
          runs: [{ id: RECORD_RUN_ID, conversation_id: RECORD.id, status: 'completed', error_code: null, created_at: '2026-10-02T00:00:02Z' }],
          actions: [],
        },
      });
    }
    if (path === `/runs/${RECORD_RUN_ID}/events`) {
      return route.fulfill({ contentType: 'text/event-stream', body: RUN_EVENT_STREAM });
    }
    if (path.startsWith('/model-gateway/catalog/')) {
      return route.fulfill({ json: { items: [{ id: '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f', name: '线上方案', enabled: true, published_version: 3, spec: { operation: 'chat' } }], total: 1 } });
    }
    if (path === '/tools' || path === '/knowledge-bases' || path === '/modules') return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  return harness;
}

/** Opens the editor and probes the environment in the page's own language. */
async function open(page: import('@playwright/test').Page, options: Options, language = 'zh-CN', hash = '/agents/agent-1/config') {
  const harness = await editor(page, options);
  await page.goto(`/#${hash}`);
  // Environment probe first: if this resolves, any later failure is a missing
  // behaviour, not a broken page or a wrong selector scope.
  await expect(page.getByLabel(tr(language, 'Agent 名称'), { exact: true })).toBeVisible();
  await expect(page.locator('#agent-model')).toBeVisible();
  return harness;
}

const saveState = (page: import('@playwright/test').Page) => page.locator('.agent-save-state');
const section = (page: import('@playwright/test').Page) => page.locator('#agent-execution');
/**
 * How often the page read `GET /agents/execution-config-flags`.
 * Measured against a real browser and the current `useResource` semantics
 * (src/shared/components/ui.tsx: fetch in an effect keyed on the path): the
 * count is exactly **2** for one editor lifetime, because `src/main.tsx` mounts
 * the app in React 19 `StrictMode`, which double-invokes the mount effect — and
 * every other editor GET (`/me`, `/agents/catalog`,
 * `/agents/memory-config-caps`, `/tools`, …) is doubled the same way, while the
 * count does **not** grow with preview clicks or saves. So 2 is framework noise,
 * not a contract: the load-bearing invariant behind 03 §7.4 ("response is
 * deterministic, the frontend reads it once per editor lifetime") is that the
 * read happens, stays bounded by the single mount, and is independent of how
 * often the preview is run. Asserting `=== 2` would freeze StrictMode into the
 * contract and break the moment the app is tested against a production build.
 */
const flagsReads = (harness: Harness) => harness.calls.filter(call => call === 'GET /agents/execution-config-flags').length;
/**
 * Takes the post-open baseline once the initial burst has settled: both
 * StrictMode invocations are dispatched inside the same mount commit, so after a
 * short settle any further read can only come from a repeated fetch, not from
 * the mount. The bound (at most one read plus its doubled mount) is asserted
 * here so every caller of the baseline inherits it.
 */
const settleReads = async (page: import('@playwright/test').Page, harness: Harness) => {
  await expect.poll(() => flagsReads(harness)).toBeGreaterThan(0);
  await page.waitForTimeout(600);
  const count = flagsReads(harness);
  expect(count, 'the switches may be read at most once per mount (StrictMode doubles it)').toBeLessThanOrEqual(2);
  return count;
};

/**
 * 05 M3's other half — "历史发布与 Run 仍可查看". Opens the record view, one
 * stored conversation and the Run trace behind its assistant answer, and fails
 * if any of that is missing, disabled or served empty. The two Phase 3
 * switches must never gate this path (03 §8, FR-9/AC-10).
 */
async function recordsStayOpen(page: import('@playwright/test').Page, language = 'zh-CN') {
  const local = (key: string) => tr(language, key);
  // The workspace nav entry is visible and clickable.
  const recordsEntry = page.getByRole('button', { name: local('对话记录') });
  await expect(recordsEntry).toBeVisible();
  await expect(recordsEntry).toBeEnabled();
  await recordsEntry.click();
  await expect(page.locator('.agent-records-heading')).toContainText(local('对话记录'));
  // The stored conversation is listed and opens.
  const recordLink = page.getByRole('button', { name: RECORD.external_id, exact: true });
  await expect(recordLink).toBeVisible();
  await recordLink.click();
  await expect(page.locator('.agent-record-detail')).toContainText(RECORD_ANSWER);
  // The past Run behind that answer still opens its trace.
  await page.getByRole('button', { name: local('查看运行轨迹') }).click();
  await expect(page.locator('.ant-modal-title')).toHaveText(local('运行详情'));
  // The event stream really was read and parsed, not merely a closed drawer:
  // the stable machine event names come straight off `GET /runs/{id}/events`.
  await expect(page.locator('.trace')).toContainText('model.completed');
  await expect(page.locator('.trace')).toContainText('run.completed');
}

test('P3-FE-01 (M1) an old draft opens without default-filled fields or dirty state', async ({ page }) => {
  const harness = await open(page, {});
  await expect(page.getByLabel('Agent 名称')).toHaveValue('售后服务助手');
  // The canonical triple is presented even though the stored draft omits it.
  await expect(section(page)).toBeVisible();
  await expect(page.getByLabel('Engine 三元组')).toHaveValue('react / native / v1');
  // Single canonical form: the legacy root alias is what the React card edits.
  await expect(page.getByLabel('最大模型轮次')).toHaveValue('6');
  await expect(saveState(page)).not.toContainText('有未保存修改');
  // Nothing was written back just by reading.
  expect(harness.calls.filter(call => call.startsWith('PUT') || call.startsWith('POST'))).toEqual([]);
  await page.screenshot({ path: 'test-results/agent-execution-legacy-open.png', fullPage: true });
});

test('P3-FE-02 a legal new execution config saves, and re-saving adds no churn', async ({ page }) => {
  const harness = await open(page, { preview: () => previewBody() });
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect(page.locator('.agent-capability-row')).toHaveCount(CAPABILITIES.length);
  await page.getByRole('checkbox', { name: /终端执行/ }).check();
  await expect(saveState(page)).toContainText('有未保存修改');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const saved = harness.saves[0].config as Record<string, unknown>;
  expect(saved.disabled_capabilities).toEqual(['terminal_execution']);
  expect(saved.max_model_rounds).toBe(6);
  // The UI never sends the server-computed layers as (fake) authorization.
  for (const forged of ['effective', 'effective_capabilities', 'declared', 'available', 'policy', 'policy_version', 'probe']) {
    expect(saved, `draft payload must not carry ${forged}`).not.toHaveProperty(forged);
  }
  // The server echoes the canonical form (engine + react + root aliases); saving
  // it back unchanged must not write again or leave the form dirty.
  await expect(saveState(page)).not.toContainText('有未保存修改');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.waitForTimeout(500);
  expect(harness.saves.length).toBe(1);
  // Editing one value now updates every alias the draft carries, so the next
  // save cannot arrive at the server as an alias conflict.
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('8');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(2);
  const again = harness.saves[1].config as Record<string, unknown>;
  expect(again.max_model_rounds).toBe(8);
  expect((again.react as Record<string, unknown>).max_model_rounds).toBe(8);
  expect(again.disabled_capabilities).toEqual(['terminal_execution']);
  await expect(saveState(page)).not.toContainText('有未保存修改');
});

test('P3-FE-03 conflicting aliases are located instead of silently resolved', async ({ page }) => {
  const harness = await open(page, {
    draft: legacyDraft({ max_model_rounds: 9, react: { model_profile_id: '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f', model_profile_version: 3, max_model_rounds: 4 } }),
  });
  await expect(section(page).locator('[role="alert"]')).toContainText('max_model_rounds');
  await expect(section(page).locator('[role="alert"]')).toContainText('react.max_model_rounds');
  // A conflicting draft is blocked before it can reach the API.
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(0);
  await expect(saveState(page)).not.toContainText('有未保存修改');
});

test('P3-FE-04 an unregistered engine triple is reported against the engine field', async ({ page }) => {
  await open(page, { draft: legacyDraft({ engine: { engine_id: 'codex', protocol_id: 'native', adapter_version: 'v1' } }) });
  await expect(section(page).locator('[role="alert"]')).toContainText('engine.engine_id');
  await expect(page.getByLabel('Engine 三元组')).toHaveValue('codex / native / v1');
  await expect(saveState(page)).not.toContainText('有未保存修改');
});

test('P3-FE-05 preview posts the unsaved draft and stays read-only', async ({ page }) => {
  const harness = await open(page, { preview: () => previewBody() });
  await page.getByLabel('Agent 简介').fill('未保存的简介');
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect.poll(() => harness.previews.length).toBe(1);
  const body = harness.previews[0];
  expect(body.agent_id).toBe('agent-1');
  expect((body.config as Record<string, unknown>).system_prompt).toBe('你是一位专业的售后客服。');
  // A preview request carries no authorization material in either direction.
  for (const forged of ['effective', 'effective_capabilities', 'declared', 'available', 'policy', 'policy_version', 'probe', 'tenant_id', 'actor']) {
    expect(body, `preview body must not carry ${forged}`).not.toHaveProperty(forged);
    expect(body.config as Record<string, unknown>, `preview config must not carry ${forged}`).not.toHaveProperty(forged);
  }
  // Only the whitelisted response shape is rendered.
  await expect(page.locator('.agent-capability-row')).toHaveCount(CAPABILITIES.length);
  await expect(page.locator('.agent-capability-row').first().getByText('streaming')).toBeVisible();
  await expect(page.locator('.agent-schema-row')).toHaveCount(2);
  // Effective values are not editable and never turn into draft changes.
  await expect(page.locator('.agent-capability-preview input:not([type="checkbox"]), .agent-capability-preview textarea, .agent-capability-preview select')).toHaveCount(0);
  const dirtyBefore = await saveState(page).innerText();
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect.poll(() => harness.previews.length).toBe(2);
  expect(dirtyBefore).toContain('有未保存修改');
  expect(await saveState(page).innerText()).toBe(dirtyBefore);
});

// Values P3-FE-05b types into the unsaved draft. The expectations below are
// these constants — never a value read back out of the request body — so the
// assertion cannot be produced from the thing it is testing.
const DRAFT_PROMPT = '未保存的新草稿提示词。';
const DRAFT_ROUNDS = 7;
const DRAFT_NARROWING = 'terminal_execution';

test('P3-FE-05b an unsaved new draft previews with a null agent id', async ({ page }) => {
  const harness = await open(page, { preview: () => previewBody() }, 'zh-CN', '/agents/new/config');
  await expect(saveState(page)).toContainText('尚未保存');
  await page.getByLabel('行为指令').fill(DRAFT_PROMPT);
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill(String(DRAFT_ROUNDS));
  await rounds.press('Enter');
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect.poll(() => harness.previews.length).toBe(1);
  expect(harness.previews[0].agent_id).toBeNull();
  // 03 §7.2/§7.4: the preview body carries *this* unsaved draft, field for
  // field — an existence check on `config` would pass on any object at all.
  const previewed = harness.previews[0].config as Record<string, unknown>;
  expect(previewed.system_prompt).toBe(DRAFT_PROMPT);
  expect(previewed.max_model_rounds).toBe(DRAFT_ROUNDS);
  // A draft nobody narrowed declares no narrowing (the server default).
  expect(previewed.disabled_capabilities ?? []).toEqual([]);
  // Narrowing a capability is an unsaved draft edit too, so the next preview
  // must show it while agent_id still says "this draft has no server identity".
  await page.getByRole('checkbox', { name: /终端执行/ }).check();
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect.poll(() => harness.previews.length).toBe(2);
  expect(harness.previews[1].agent_id).toBeNull();
  const narrowed = harness.previews[1].config as Record<string, unknown>;
  expect(narrowed.disabled_capabilities).toEqual([DRAFT_NARROWING]);
  expect(narrowed.system_prompt).toBe(DRAFT_PROMPT);
  expect(narrowed.max_model_rounds).toBe(DRAFT_ROUNDS);
});

test('P3-FE-06 probe unavailability and policy denial are distinguishable', async ({ page }) => {
  await open(page, {
    preview: () => previewBody({
      terminal_execution: 'probe_unavailable',
      file_operations: 'agent_disabled',
      workspace_required: 'workspace_unavailable',
      native_events: 'tenant_denied',
    }),
  });
  await page.getByRole('button', { name: '预览能力' }).click();
  const rows = page.locator('.agent-capability-row');
  await expect(rows).toHaveCount(CAPABILITIES.length);
  const row = (name: string) => rows.filter({ has: page.getByText(name, { exact: true }) });
  await expect(row('terminal_execution').getByText('部署探测不可用')).toBeVisible();
  await expect(row('file_operations').getByText('Agent 已禁用')).toBeVisible();
  await expect(row('workspace_required').getByText('工作区不可用')).toBeVisible();
  await expect(row('native_events').getByText('租户策略拒绝')).toBeVisible();
  // The raw reason code stays inspectable, but no internal snapshot text leaks.
  await expect(row('terminal_execution').locator('code')).toHaveText('probe_unavailable');
  const text = await section(page).innerText();
  for (const secret of ['probe_id', 'policy_version', 'digest', 'observed_at', 'tenant_id', 'snapshot']) {
    expect(text, `preview must not expose ${secret}`).not.toContain(secret);
  }
  await page.screenshot({ path: 'test-results/agent-execution-preview-reasons.png', fullPage: true });
});

test('P3-FE-07 disabled_capabilities can only narrow what the server allowed', async ({ page }) => {
  const harness = await open(page, {
    preview: () => previewBody({ file_operations: 'probe_unavailable', session_resume: 'not_declared' }),
  });
  await page.getByRole('button', { name: '预览能力' }).click();
  const rows = page.locator('.agent-capability-row');
  await expect(rows).toHaveCount(CAPABILITIES.length);
  // Unavailable capabilities cannot be switched on from the UI.
  await expect(rows.filter({ has: page.getByText('file_operations', { exact: true }) }).getByRole('checkbox')).toBeDisabled();
  await expect(rows.filter({ has: page.getByText('session_resume', { exact: true }) }).getByRole('checkbox')).toBeDisabled();
  const narrow = rows.filter({ has: page.getByText('terminal_execution', { exact: true }) }).getByRole('checkbox');
  await expect(narrow).toBeEnabled();
  await narrow.check();
  await narrow.uncheck();
  expect((harness.saves.length)).toBe(0);
  await narrow.check();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect(harness.saves[0].config).toMatchObject({ disabled_capabilities: ['terminal_execution'] });
});

test('P3-FE-08 previewing never creates a run or a message', async ({ page }) => {
  const harness = await open(page, { preview: () => previewBody() });
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect(page.locator('.agent-capability-row')).toHaveCount(CAPABILITIES.length);
  await page.locator('.agent-capability-row').first().getByRole('checkbox').check();
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect.poll(() => harness.previews.length).toBe(2);
  const runCalls = harness.calls.filter(call => /\/runs(\?|$|\/)/.test(call) || /\/conversations\/[^/]+\/messages/.test(call) || /\/conversations(\?|$)/.test(call));
  expect(runCalls).toEqual([]);
  expect(harness.calls.filter(call => call.startsWith('POST'))).toEqual(['POST /agents/execution-preview', 'POST /agents/execution-preview']);
  // The panel states out loud that a preview grants nothing.
  await expect(section(page).getByText('预览结果由服务端计算，不会创建运行，也不会授予执行权限。')).toBeVisible();
});

test('P3-FE-09 (M1) a viewer can read and preview but never write', async ({ page }) => {
  const harness = await open(page, { role: 'viewer', preview: () => previewBody() });
  await expect(page.getByLabel('Agent 名称')).toBeDisabled();
  await expect(page.getByLabel('Chat 模型方案')).toBeDisabled();
  await expect(page.getByLabel('最大模型轮次')).toBeDisabled();
  await expect(page.getByRole('button', { name: '保存草稿' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '发布', exact: true })).toBeDisabled();
  // Preview rides on the existing read permission, so it stays available.
  await expect(page.getByRole('button', { name: '预览能力' })).toBeEnabled();
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect(page.locator('.agent-capability-row')).toHaveCount(CAPABILITIES.length);
  const boxes = page.locator('.agent-capability-row').getByRole('checkbox');
  await expect(boxes).toHaveCount(CAPABILITIES.length);
  for (let index = 0; index < CAPABILITIES.length; index += 1) await expect(boxes.nth(index)).toBeDisabled();
  expect(harness.saves).toEqual([]);
});

test('P3-FE-10 a disabled Phase 3 keeps the panel inert', async ({ page }) => {
  await open(page, { previewStatus: 409, previewError: 'execution_phase3_disabled' });
  await page.getByRole('button', { name: '预览能力' }).click();
  await expect(section(page).locator('[role="alert"]')).toContainText('Phase 3 执行能力尚未启用，无法预览。');
  await expect(page.locator('.agent-capability-row')).toHaveCount(0);
});

/**
 * A strict-schema rejection in the shape the backend answers with (03 §7.3:
 * 422 with a pydantic error list). Shared by P3-FE-10b and the four-locale
 * follow-up P3-FE-10c so both exercise the identical payload.
 * `msg` is what pydantic sends — always English by design; only the framework
 * copy around it is translated.
 */
const STRICT_SCHEMA_REJECTION = [
  { loc: ['body', 'config', 'react', 'max_model_rounds'], msg: 'Input should be a valid integer', type: 'int_type' },
  { loc: ['body', 'config', 'disabled_capabilities', 3], msg: 'Input should be a valid capability', type: 'enum' },
  { loc: ['body', 'config', 'system_prompt'], msg: 'String should have at least 1 character', type: 'min_length' },
];
/**
 * The line `ExecutionConfigSection.locateExecutionErrors` renders for one
 * rejected path: the framework sentence is read out of `language`'s own
 * dictionary and interpolated the way i18next would, so an assertion built here
 * can only be satisfied by that locale's copy.
 */
const locatedLine = (language: string, path: string, msg: string) => tr(language, '字段 {{v0}}：{{v1}}')
  .replace('{{v0}}', path)
  .replace('{{v1}}', msg);

test('P3-FE-10b a strict schema rejection names the execution field path', async ({ page }) => {
  await open(page, {
    previewStatus: 422,
    previewError: STRICT_SCHEMA_REJECTION,
  });
  await page.getByRole('button', { name: '预览能力' }).click();
  const alert = section(page).locator('[role="alert"]');
  await expect(alert).toContainText('react.max_model_rounds');
  await expect(alert).toContainText('disabled_capabilities');
  // Only execution fields are pointed at here; unrelated paths keep their own
  // generic handling, so the panel does not claim responsibility for them.
  await expect(alert).not.toContainText('system_prompt');
});

// 05 M2/A9, 04 §6.1: the 422 field-path location must be located *and*
// readable in every locale, not only in the Chinese source UI.
for (const language of ['zh-CN', 'zh-TW', 'en', 'hi']) {
  test(`P3-FE-10c ${language} frames a 422 field path with its own dictionary copy`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
    await open(page, {
      previewStatus: 422,
      previewError: STRICT_SCHEMA_REJECTION,
    }, language);
    await page.getByRole('button', { name: tr(language, '预览能力') }).click();
    const alert = section(page).locator('[role="alert"]');
    // The framework sentence is this locale's translation of `字段 {{v0}}：{{v1}}`
    // (or the test fails against a fallback); the server's English `msg` inside
    // it is pydantic's own text and stays as sent — translating it is not part
    // of the contract.
    await expect(alert).toContainText(locatedLine(language, 'react.max_model_rounds', 'Input should be a valid integer'));
    await expect(alert).toContainText(locatedLine(language, 'disabled_capabilities', 'Input should be a valid capability'));
    // The contract path stays verbatim inside the sentence, so it can be
    // pointed at in a bug report regardless of the UI language.
    await expect(alert).toContainText('react.max_model_rounds');
    await expect(alert).toContainText('disabled_capabilities');
    // An unrelated path is not claimed, and the structured body is never dumped
    // raw: without the located copy the panel falls back to the generic
    // `请检查必填项和输入格式 (422)` line, which points at nothing.
    await expect(alert).not.toContainText('system_prompt');
    await expect(alert).not.toContainText('"loc"');
    await expect(alert).not.toContainText('422 ·');
    if (language === 'en' || language === 'hi') {
      // No Chinese framework text may survive the lookup.
      expect(await alert.innerText()).not.toMatch(/[㐀-鿿]/);
    }
  });
}

test('P3-FE-11 a rejected save points at the offending execution field', async ({ page }) => {
  await open(page, { saveStatus: 409 });
  await page.getByLabel('Agent 简介').fill('触发一次保存');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(section(page).locator('[role="alert"]')).toContainText('所选 Engine 未注册或已停用，无法预览或发布。');
});

for (const language of ['zh-CN', 'zh-TW', 'en', 'hi']) {
  test(`P3-FE-12 ${language} covers controls, reasons and errors`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
    await open(page, {
      preview: () => previewBody({ terminal_execution: 'probe_timeout', file_operations: 'agent_disabled' }),
    }, language);
    const local = (key: string) => tr(language, key);
    await expect(page.getByRole('button', { name: local('预览能力') })).toBeVisible();
    await expect(page.getByLabel(local('Engine 三元组'))).toBeVisible();
    await expect(page.getByRole('heading', { name: local('React 配置') })).toBeVisible();
    await page.getByRole('button', { name: local('预览能力') }).click();
    await expect(page.locator('.agent-capability-row')).toHaveCount(CAPABILITIES.length);
    await expect(section(page).getByText(local('部署探测超时'))).toBeVisible();
    await expect(section(page).getByText(local('Agent 已禁用'))).toBeVisible();
    await expect(section(page).getByText(local('流式输出'))).toBeVisible();
    await expect(section(page).getByText(local('需要工作区'))).toBeVisible();
    await expect(section(page).getByText(local('生效')).first()).toBeVisible();
    await expect(section(page).getByText(local('不可用')).first()).toBeVisible();
    await expect(section(page).getByText(local('配置字段'))).toBeVisible();
    await expect(section(page).getByText(local('禁用能力只会收窄服务端计算结果，不能授予任何能力。'))).toBeVisible();
    await page.screenshot({ path: `test-results/agent-execution-${language}.png`, fullPage: true });
    if (language === 'en' || language === 'hi') {
      // No untranslated fallback may survive inside the new panel. The reason
      // codes themselves are machine tokens and stay visible next to the label.
      const text = await section(page).innerText();
      expect(text).not.toMatch(/[㐀-鿿]/);
    }
  });
}

// Hints the flags-driven gating renders (03 §8, R-25). The keys are the Chinese
// source text, so locale coverage is asserted through tr() like every other copy.
const OFF_HINT = '当前部署未启用 Phase 3 执行能力，能力预览与能力收窄入口已隐藏；React 配置与历史记录不受影响。';
const MISCONFIG_HINT = '部署配置错误：execution_phase3_enabled 已启用而 execution_orchestrator_enabled 未启用，能力预览会失败，请联系运维核对配置。';

test('P3-FE-14 (M3) phase3 off hides the editing entries declaratively and keeps the React path intact', async ({ page }) => {
  const harness = await open(page, { flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true } });
  // The hint proves the flags response landed: the entry disappears because the
  // switch says so, not because a click errored out afterwards.
  await expect(section(page).getByText(OFF_HINT)).toBeVisible();
  await expect(page.getByRole('button', { name: '预览能力' })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /收窄/ })).toHaveCount(0);
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
  // The read-only Engine view is not an editing entry, so it survives (R-23).
  await expect(page.getByLabel('Engine 三元组')).toHaveValue('react / native / v1');
  // React model-profile and round editing keep working: off + orchestrator-on
  // is the Phase 2 path, and gating it away would itself be a violation.
  await expect(page.getByLabel('Chat 模型方案')).toBeEnabled();
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('8');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect((harness.saves[0].config as Record<string, unknown>).max_model_rounds).toBe(8);
  // History viewing is never gated by the two switches either.
  await page.getByRole('button', { name: '版本历史' }).click();
  await expect(page.getByRole('heading', { name: '发布历史' })).toBeVisible();
  // Stronger than the P3-FE-08 whitelist: nothing Phase 3 was even attempted.
  expect(harness.previews).toEqual([]);
  expect(harness.calls.filter(call => call.startsWith('POST'))).toEqual([]);
  const runCalls = harness.calls.filter(call => /\/runs(\?|$|\/)/.test(call) || /\/conversations/.test(call));
  expect(runCalls).toEqual([]);
});

test('P3-FE-15 (M3) the on + orchestrator-off mismatch warns without any fake success', async ({ page }) => {
  const harness = await open(page, {
    flags: { execution_phase3_enabled: true, execution_orchestrator_enabled: false },
    previewStatus: 409,
    previewError: 'execution_configuration_invalid',
  });
  await expect(section(page).getByText(MISCONFIG_HINT)).toBeVisible();
  // Entries follow execution_phase3_enabled, so the preview stays reachable.
  const preview = page.getByRole('button', { name: '预览能力' });
  await expect(preview).toBeEnabled();
  await preview.click();
  await expect.poll(() => harness.previews.length).toBe(1);
  // The server-side failure is surfaced; a success view is never rendered.
  await expect(section(page).locator('[role="alert"]')).toContainText('执行配置不合法，请检查标记的字段。');
  await expect(page.locator('.agent-capability-row')).toHaveCount(0);
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
});

test('P3-FE-16 (M3) a failed flags read hides the Phase 3 entries fail-closed', async ({ page }) => {
  const harness = await open(page, { flagsStatus: 500 });
  // The read is attempted (fail-closed needs an attempted read, not a silent
  // absence) and it is not repeated as the user keeps working — see `flagsReads`
  // for why the bound is "at most the one doubled mount" instead of `=== 1`.
  const afterOpen = await settleReads(page, harness);
  expect(afterOpen).toBeGreaterThanOrEqual(1);
  await expect(page.getByRole('button', { name: '预览能力' })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /收窄/ })).toHaveCount(0);
  // An unknown deployment state is not announced as a proven off switch.
  await expect(section(page).getByText(OFF_HINT)).toHaveCount(0);
  await expect(section(page).getByText(MISCONFIG_HINT)).toHaveCount(0);
  // Fail-closed covers the Phase 3 entries only; the React editor stays usable.
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('9');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  // A failed read gets no automatic retry, so the editor cannot end up acting on
  // a switch set that never loaded successfully.
  expect(flagsReads(harness), 'a failed flags read must not be re-issued on save').toBe(afterOpen);
});

test('P3-FE-16b the flags pair is read once per editor lifetime, not per preview', async ({ page }) => {
  // 03 §7.4's discipline stated as a request-count invariant: a deterministic
  // response is fetched with the editor, and running the preview — the only
  // Phase 3 action that consumes it — never re-fetches it.
  const harness = await open(page, { preview: () => previewBody() });
  const afterOpen = await settleReads(page, harness);
  expect(afterOpen).toBeGreaterThanOrEqual(1);
  for (let click = 1; click <= 3; click += 1) {
    await page.getByRole('button', { name: '预览能力' }).click();
    await expect.poll(() => harness.previews.length).toBe(click);
    await expect(page.locator('.agent-capability-row')).toHaveCount(CAPABILITIES.length);
    expect(flagsReads(harness), `preview #${click} must not re-read the deployment switches`).toBe(afterOpen);
  }
  // Saving re-renders the editor without remounting it, so it stays out of scope
  // for the read as well.
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('9');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect(flagsReads(harness)).toBe(afterOpen);
});

for (const language of ['zh-CN', 'zh-TW', 'en', 'hi']) {
  test(`P3-FE-17 ${language} translates the Phase 3 not-enabled hint`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
    await open(page, { flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true } }, language);
    await expect(section(page).getByText(tr(language, OFF_HINT))).toBeVisible();
    await expect(page.getByRole('button', { name: tr(language, '预览能力') })).toHaveCount(0);
    if (language === 'en' || language === 'hi') {
      expect(await section(page).innerText()).not.toMatch(/[㐀-鿿]/);
    }
  });
  test(`P3-FE-18 ${language} translates the deployment misconfiguration hint`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
    await open(page, { flags: { execution_phase3_enabled: true, execution_orchestrator_enabled: false } }, language);
    await expect(section(page).getByText(tr(language, MISCONFIG_HINT))).toBeVisible();
    if (language === 'en' || language === 'hi') {
      expect(await section(page).innerText()).not.toMatch(/[㐀-鿿]/);
    }
  });
}

// P3-FE-19 pins the other half of "gating drives visibility, not authorization"
// (03 §8, 04 §6.1, 05 A9/M1/M3): the flags pair may hide the Phase 3 entries,
// but only the server may accept or refuse a draft, and a refusal must not be
// read back as a switch state.
//
// Code choice: `execution_configuration_invalid` is the 409 the *save* path
// actually answers with — `backend/src/agent_platform/business_capabilities/
// agent_config/service.py` raises it from `parse_config`/`validate_execution` —
// while `execution_phase3_disabled` is documented in 03 §7.3 for the preview
// contract only and is not raised on `PUT /agents/{id}`. Using the save-path
// code keeps the mock faithful instead of inventing a contract the design does
// not state; `execution_engine_unavailable` would repeat P3-FE-11.
test('P3-FE-19 (M3) a save the server refuses while phase3 is off stays translated, located and non-unlocking', async ({ page }) => {
  const language = 'hi';
  const local = (key: string) => tr(language, key);
  // Hindi is the furthest script from the Chinese source keys, so a hardcoded
  // sentence in the component could not satisfy the copy assertions below.
  await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
  const harness = await open(page, {
    flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true },
    // A draft that still carries the narrowing written before the rollback.
    draft: legacyDraft({ disabled_capabilities: ['terminal_execution'] }),
    saveStatus: 409,
    saveError: 'execution_configuration_invalid',
  }, language);
  const rounds = page.getByLabel(local('最大模型轮次'));
  await rounds.fill('8');
  await rounds.press('Enter');
  await page.getByRole('button', { name: local('保存草稿'), exact: true }).click();
  // The Phase 2 React save is still attempted: hiding an entry is not the same
  // as disabling a path the switches must leave alone (03 §8, FR-9/AC-10).
  await expect.poll(() => harness.saves.length).toBe(1);
  // The refusal is surfaced inside the execution section, as translated copy
  // plus the stable code, so it can be pointed at (M2).
  const alert = section(page).locator('[role="alert"]');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(local('执行配置不合法，请检查标记的字段。'));
  await expect(alert).toContainText('409 · execution_configuration_invalid');
  // Neither a hardcoded Chinese literal nor the generic failure fallback.
  expect(await alert.innerText()).not.toMatch(/[㐀-鿿]/);
  expect(await alert.innerText()).not.toContain(local('请求失败，请重试或联系管理员'));
  // The sentence is dictionary-driven in every locale, not just this UI.
  for (const each of Object.keys(DICTIONARIES)) {
    expect(tr(each, '执行配置不合法，请检查标记的字段。').trim(), `${each} misses the save-path copy`).toBeTruthy();
  }
  // A server "no" never unlocks an entry: same Phase 3 DOM as P3-FE-14, and the
  // off hint survives, i.e. the flags state was not rewritten by the failure.
  await expect(page.getByRole('button', { name: local('预览能力') })).toHaveCount(0);
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
  await expect(page.locator('.agent-capability-row')).toHaveCount(0);
  // The narrowing checkbox only ever lives in the preview panel, so an empty
  // checkbox set inside the section is the locale-free form of P3-FE-14's check.
  await expect(section(page).getByRole('checkbox')).toHaveCount(0);
  await expect(section(page).getByText(local(OFF_HINT))).toBeVisible();
  await expect(section(page).getByText(local(MISCONFIG_HINT))).toHaveCount(0);
  // Refusing the draft does not clear what the administrator typed.
  await expect(rounds).toHaveValue('8');
  await expect(page.getByLabel(local('Chat 模型方案'))).toHaveValue('6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f');
  await expect(saveState(page)).toContainText(local('有未保存修改'));
  // And nothing Phase 3 was requested before or after the refusal.
  expect(harness.previews).toEqual([]);
  expect(harness.calls.filter(call => call.startsWith('POST') || call.includes('/agents/execution-preview'))).toEqual([]);
});

// 05 M3 closes with two halves, and the acceptance read-out only counted the
// first one so far: the Phase 3 entries must disappear *and* "历史发布与 Run 仍
// 可查看" must hold. P3-FE-14/16 prove the hiding side; these two prove the
// viewing side survives the very same two deployment states, because hiding
// more than the Phase 3 entries would itself be an FR-9/AC-10 violation.
test('P3-FE-20 (M3) phase3 off still opens the conversation records and a past Run', async ({ page }) => {
  const harness = await open(page, { flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true } });
  // The Phase 3 editing entries are gone, exactly as P3-FE-14 established.
  await expect(page.getByRole('button', { name: '预览能力' })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /收窄/ })).toHaveCount(0);
  // The record view and the Run behind it stay reachable.
  await recordsStayOpen(page);
  // Opening a past Run is pure reading: the run event stream was fetched, and
  // not one Phase 3 or write request was attempted.
  expect(harness.calls.filter(call => call === 'GET /runs/run-record/events').length).toBeGreaterThanOrEqual(1);
  expect(harness.calls.filter(call => !call.startsWith('GET'))).toEqual([]);
  expect(harness.previews).toEqual([]);
  expect(harness.saves).toEqual([]);
});

test('P3-FE-21 (M3) a failed flags read still leaves the records and Run viewable', async ({ page }) => {
  const harness = await open(page, { flagsStatus: 500 });
  await settleReads(page, harness);
  // Fail-closed hid the Phase 3 entries without claiming a proven off switch.
  await expect(page.getByRole('button', { name: '预览能力' })).toHaveCount(0);
  await expect(section(page).getByText(OFF_HINT)).toHaveCount(0);
  // The unknown deployment state must not cost the operator their history.
  await recordsStayOpen(page);
  expect(harness.calls.filter(call => call === 'GET /runs/run-record/events').length).toBeGreaterThanOrEqual(1);
  expect(harness.calls.filter(call => !call.startsWith('GET'))).toEqual([]);
  expect(harness.previews).toEqual([]);
});

/**
 * The `known` code table inside `errorText` (`src/i18n/index.ts`). Its values
 * are looked up as dictionary keys at runtime, and `check:i18n` cannot see any
 * of it: `scripts/check-i18n.mjs` walks the AST for `t('literal')` call sites
 * only (line 75: `ts.isCallExpression(node) && … === 't'`), so a table entry is
 * never a scanned call site and a code whose sentence misses a locale passes
 * `check:i18n` silently — the UI then falls back to the Chinese source text.
 *
 * P3-FE-13 is therefore the ONLY guard for that table. T10 must not delete or
 * narrow it, and any new `execution_*` code (or any other domain code) added to
 * `errorText` without all four translations must turn this test red.
 */
function errorTextCodeTable(): Record<string, string> {
  const source = readFileSync(fileURLToPath(new URL('../src/i18n/index.ts', import.meta.url)), 'utf8');
  const block = source.split('const known:Record<string,string>={')[1];
  expect(block, 'errorText must keep its `known` code table in src/i18n/index.ts for P3-FE-13 to cover it').toBeTruthy();
  const table: Record<string, string> = {};
  for (const line of block!.split('\n  };')[0].split('\n')) {
    // Both shapes the table uses: `code:'sentence'`, `code:"sentence"` and `code:t('sentence')`.
    const entry = /^\s*([a-z][a-z0-9_]*):\s*(?:t\()?["']([^"']*)["']\)?,?$/.exec(line);
    if (entry)
      table[entry[1]] = entry[2];
  }
  return table;
}

// Codes whose table sentence is a key in no locale, so the UI shows the Chinese
// source in en/hi. Pre-existing and outside Phase 3 (reported at the T9
// close-up, owned by the i18n follow-up); listed explicitly so a *new*
// untranslated code cannot hide behind it — the moment one appears that is not
// in this list, P3-FE-13 fails.
const UNTRANSLATED_ERROR_COPY = ['model_not_configured'];

test('P3-FE-13 every new execution key exists in all four locales', () => {
  const keys = [
    '执行与能力', '执行配置', 'React 配置', '能力（Effective）', '配置字段',
    'Engine 三元组', '预览能力', '生效', '不可用', '必填', '可选', '已注册', '未注册',
    '流式输出', '持久会话', '会话恢复', '运行取消', '人工审批', '交互式输入',
    '工具调用', '文件操作', '终端执行', '原生事件', '需要工作区',
    '服务端允许', 'Engine 未声明此能力', '部署探测不可用', '部署探测超时', '部署探测结果已过期',
    '工作区不可用', '平台策略拒绝', '租户策略拒绝', 'Agent 已禁用', '执行上下文拒绝', '策略源不可用',
    '禁用能力只会收窄服务端计算结果，不能授予任何能力。',
    '预览结果由服务端计算，不会创建运行，也不会授予执行权限。',
    '运行 Engine 与能力由服务端注册表和策略决定，这里只能查看与收窄。',
    'Phase 3 执行能力尚未启用，无法预览。',
    '所选 Engine 未注册或已停用，无法预览或发布。',
    '执行配置不合法，请检查标记的字段。', '字段 {{v0}}：{{v1}}',
    '能力策略源暂不可用，请稍后重试。',
    '{{v0}} 与 {{v1}} 取值不一致，请保留其中一处后再保存。',
    OFF_HINT,
    MISCONFIG_HINT,
  ];
  for (const key of keys) {
    for (const language of Object.keys(DICTIONARIES)) {
      const value = DICTIONARIES[language][key];
      expect(value, `${language} misses ${key}`).toBeTruthy();
      expect(value!.trim(), `${language} has an empty ${key}`).toBeTruthy();
      // Placeholder sets must match so interpolation cannot leak a raw key.
      expect(JSON.stringify([...value!.matchAll(/{{\s*(\w+)\s*}}/g)].map(m => m[1]).sort()), `${language} placeholders for ${key}`)
        .toBe(JSON.stringify([...key.matchAll(/{{\s*(\w+)\s*}}/g)].map(m => m[1]).sort()));
    }
  }
  // Every code `errorText` maps must resolve to copy the four dictionaries
  // actually carry, not just the ones spot-checked by the key list above.
  const table = errorTextCodeTable();
  expect(Object.keys(table).length, 'the errorText code table was not parsed').toBeGreaterThan(0);
  // 03 §7.3 lists exactly these four stable execution domain codes. Growing the
  // set is fine, but it has to be a deliberate act: add the new code here *and*
  // its sentence to all four locales, or this stays red.
  const executionCodes = Object.keys(table).filter(code => code.startsWith('execution_')).sort();
  expect(executionCodes, 'the execution_* codes in errorText changed shape')
    .toEqual(['execution_configuration_invalid', 'execution_engine_unavailable', 'execution_phase3_disabled', 'execution_policy_unavailable']);
  const untranslated: string[] = [];
  for (const [code, sentence] of Object.entries(table)) {
    const placeholders = (value: string) => JSON.stringify([...value.matchAll(/{{\s*(\w+)\s*}}/g)].map(match => match[1]).sort());
    let missing = false;
    for (const language of Object.keys(DICTIONARIES)) {
      const value = DICTIONARIES[language][sentence];
      if (!value || !value.trim()) {
        missing = true;
        continue;
      }
      expect(placeholders(value), `${language} changes the placeholders of the sentence behind ${code}`).toBe(placeholders(sentence));
      if (language === 'en' || language === 'hi') {
        expect(value, `${language} shows raw Chinese for the code ${code}`).not.toMatch(/[㐀-鿿]/);
      }
    }
    if (missing)
      untranslated.push(code);
  }
  // The known legacy holes are the only tolerated ones; anything else means a
  // code was added to `errorText` without translating it.
  for (const code of untranslated) {
    expect(UNTRANSLATED_ERROR_COPY, `${code} maps to a sentence no locale defines; translate it in all four dictionaries`).toContain(code);
  }
  expect(keys.length).toBeGreaterThanOrEqual(40);
});
