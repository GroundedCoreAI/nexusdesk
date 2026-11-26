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
// GET /agents/execution-config-flags (03 §7.4): the two booleans plus the issue
// #162 non-sensitive Codex metadata. Both on is the regular deployment state.
// The allowlist pins 0.169.0 (the installed/verified version) while the newest
// npm version 0.171.0 is catalogue-only — the exact scenario from issue #162.
const CODEX_CATALOGUE = [
  { version: '0.171.0', source: 'npm-registry', verified: true },
  { version: '0.169.0', source: 'installed-cli', verified: false },
];
const FLAGS = {
  execution_phase3_enabled: true,
  execution_orchestrator_enabled: true,
  allowed_codex_versions: ['0.169.0'],
  codex_version_catalogue: CODEX_CATALOGUE,
};
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

/** The registered Stage A Codex triple and a publishable typed Codex block. */
const CODEX_ENGINE = { engine_id: 'codex', protocol_id: 'cli_exec', adapter_version: 'v1' };
const CODEX_BLOCK = {
  protocol: 'cli_exec', version: '0.169.0', executable: 'codex', timeout_seconds: 600,
  approval_mode: 'never', sandbox_mode: 'read-only', credential_ref: null as string | null,
  path_env: '/usr/local/bin:/usr/bin:/bin',
};
/** A published-agent draft on the Codex engine, with React aliases still set. */
function codexDraft(overrides: Record<string, unknown> = {}) {
  return legacyDraft({ engine: CODEX_ENGINE, codex: { ...CODEX_BLOCK }, ...overrides });
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
  /** Flags endpoint body; defaults to both on plus the #162 Codex metadata. */
  flags?: {
    execution_phase3_enabled: boolean;
    execution_orchestrator_enabled: boolean;
    allowed_codex_versions?: string[];
    codex_version_catalogue?: Array<{ version: string; source: string; verified: boolean }>;
  };
  /** Status code the flags endpoint answers with, to exercise fail-closed gating. */
  flagsStatus?: number;
  /** Admin-only credential metadata behind GET /execution-credentials (T-07). */
  credentials?: unknown;
  /** Gateway models page; default has one tool-calling model on a ready connection. */
  gatewayModels?: unknown;
  /** Gateway connections page; default has a Codex-capable HTTPS connection. */
  gatewayConnections?: unknown;
  /** Gateway profiles page; omit to use the default chat profile. */
  gatewayProfiles?: unknown;
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
    // Admin-only metadata endpoint: `public_metadata()` only, never a secret.
    if (path === '/execution-credentials') {
      return route.fulfill({ json: options.credentials ?? { items: [] } });
    }
    if (path === '/agents/agent-1' && method === 'PUT') {
      const body = request.postDataJSON() as Record<string, unknown>;
      harness.saves.push(body);
      if (options.saveStatus) {
        return route.fulfill({ status: options.saveStatus, json: { detail: options.saveError ?? 'execution_engine_unavailable' } });
      }
      // Mirrors the real service: the stored draft is the validated model, so it
      // carries the canonical execution fields plus the legacy root aliases.
      // A CLI engine draft has no React block at all — echoing one here would
      // hide a wire-shape regression the real normalizer would reject.
      const config = body.config as Record<string, unknown>;
      const engineId = (config.engine as Record<string, unknown> | undefined)?.engine_id ?? 'react';
      const react = (config.react ?? {}) as Record<string, unknown>;
      const canonical: Record<string, unknown> = {
        ...config,
        engine: config.engine ?? ENGINE,
        disabled_capabilities: config.disabled_capabilities ?? [],
      };
      canonical.react = engineId === 'react'
        ? {
            model_profile_id: react.model_profile_id ?? config.model_profile_id ?? null,
            model_profile_version: react.model_profile_version ?? config.model_profile_version ?? null,
            max_model_rounds: react.max_model_rounds ?? config.max_model_rounds ?? 6,
          }
        : undefined;
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
    if (path.startsWith('/model-gateway/catalog/profiles')) {
      return route.fulfill({ json: options.gatewayProfiles ?? {
        items: [{ id: '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f', name: '线上方案', enabled: true, published_version: 3, spec: { operation: 'chat', model_id: 'model-ready' } }], total: 1,
      } });
    }
    if (path.startsWith('/model-gateway/catalog/models')) {
      return route.fulfill({ json: options.gatewayModels ?? {
        items: [{ id: 'model-ready', name: 'Ready', enabled: true, published_version: 1, spec: { tool_calling: true, connection_id: 'conn-ready' } }], total: 1,
      } });
    }
    if (path.startsWith('/model-gateway/catalog/connections')) {
      return route.fulfill({ json: options.gatewayConnections ?? {
        items: [{ id: 'conn-ready', name: 'Ready', enabled: true, published_version: 1, spec: { base_url: 'https://api.example.com', execution_credential_ref: CREDENTIAL_REF } }], total: 1,
      } });
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
  await expect(section(page)).toBeVisible();
  // The engine triple is a wire identity, never a field a customer has to read.
  await expect(page.getByLabel('Engine 三元组')).toHaveCount(0);
  await expect(section(page).getByText('对话模型（平台内置）', { exact: true })).toBeVisible();
  await expect(page.getByLabel('最大模型轮次')).toHaveValue('6');
  await expect(saveState(page)).not.toContainText('有未保存修改');
  expect(harness.calls.filter(call => call.startsWith('PUT') || call.startsWith('POST'))).toEqual([]);
  await page.locator('#agent-execution').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/agent-execution-legacy-open.png' });
});

test('P3-FE-02 a legal new execution config saves, and re-saving adds no churn', async ({ page }) => {
  const harness = await open(page, {});
  // Make one edit so the save button has something to persist.
  await page.getByLabel('Agent 简介').fill('一次合法的执行配置');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const saved = harness.saves[0].config as Record<string, unknown>;
  expect(saved.max_model_rounds).toBe(6);
  for (const forged of ['effective', 'effective_capabilities', 'declared', 'available', 'policy', 'policy_version', 'probe']) {
    expect(saved, `draft payload must not carry ${forged}`).not.toHaveProperty(forged);
  }
  await expect(saveState(page)).not.toContainText('有未保存修改');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.waitForTimeout(500);
  expect(harness.saves.length).toBe(1);
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('8');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(2);
  const again = harness.saves[1].config as Record<string, unknown>;
  expect(again.max_model_rounds).toBe(8);
  expect((again.react as Record<string, unknown>).max_model_rounds).toBe(8);
  await expect(saveState(page)).not.toContainText('有未保存修改');
});

test('P3-FE-03 conflicting aliases are located instead of silently resolved', async ({ page }) => {
  const harness = await open(page, {
    draft: legacyDraft({ max_model_rounds: 9, react: { model_profile_id: '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f', model_profile_version: 3, max_model_rounds: 4 } }),
  });
  await expect(section(page).locator('[role="alert"]')).toContainText('max_model_rounds');
  await expect(section(page).locator('[role="alert"]')).toContainText('react.max_model_rounds');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(0);
  await expect(saveState(page)).not.toContainText('有未保存修改');
});

test('P3-FE-04 an unregistered engine is reported against the engine field', async ({ page }) => {
  await open(page, { draft: legacyDraft({ engine: { engine_id: 'codex', protocol_id: 'native', adapter_version: 'v1' } }) });
  await expect(section(page).locator('[role="alert"]')).toContainText('engine.engine_id');
  await expect(saveState(page)).not.toContainText('有未保存修改');
});

test('P5-FE-01 (G1) the runtime selector publishes a typed Codex block without React aliases', async ({ page }) => {
  const harness = await open(page, {});
  await page.getByLabel('运行方式').click();
  await page.locator('.ant-select-item-option-content', { hasText: '代码任务（命令行）' }).click();
  await expect(page.getByLabel('Codex 模型方案（模型网关）')).toBeVisible();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const saved = harness.saves[0].config as Record<string, unknown>;
  expect((saved.engine as Record<string, unknown>).engine_id).toBe('codex');
  expect((saved.codex as Record<string, unknown>).version).toBe('0.169.0');
  expect(saved.react).toBeUndefined();
  expect(saved.model_profile_id).toBeNull();
  expect(saved.max_model_rounds).toBe(6);
});

test('P5-FE-02 phase3 off hides the runtime selector and keeps Codex details read-only', async ({ page }) => {
  await open(page, {
    flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true },
    draft: legacyDraft({ engine: CODEX_ENGINE, codex: { ...CODEX_BLOCK, path_env: '/usr/bin' } }),
  });
  await expect(page.getByLabel('运行方式')).toHaveCount(0);
  await expect(page.getByLabel('Codex 版本')).toHaveCount(0);
  await expect(page.getByLabel('Codex PATH')).toHaveCount(0);
  await expect(section(page).locator('input[aria-label="Codex 凭据引用（UUID）"]')).toHaveCount(0);
  await expect(page.getByLabel('Codex 模型方案（模型网关）')).toBeDisabled();
});

const FIELD_422 = [
  { loc: ['body', 'config', 'codex', 'version'], msg: 'String should have at least 1 character', type: 'string_too_short' },
  { loc: ['body', 'config', 'system_prompt'], msg: 'Field required', type: 'missing' },
];
const CREDENTIAL_REF = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CREDENTIAL_META = {
  credential_ref: CREDENTIAL_REF, tenant_id: 'test', name: 'DeepSeek 生产密钥',
  credential_type: 'api_key', key_version: 'v1', version: 2, status: 'active',
  allowed_engines: ['codex'], allowed_workspaces: ['*'],
  created_at: '2026-11-20T00:00:00Z', updated_at: '2026-11-20T00:00:00Z',
  rotated_at: null, revoked_at: null,
};
const DUPLICATE_META = { ...CREDENTIAL_META, credential_ref: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' };

test('P7-UI-01 a Codex save carries neither legacy React aliases nor a react block', async ({ page }) => {
  const harness = await open(page, { draft: codexDraft() });
  await page.getByLabel('Agent 简介').fill('触发一次保存');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const config = harness.saves[0].config as Record<string, unknown>;
  expect(config.react).toBeUndefined();
  expect(config.model_profile_id).toBeNull();
  expect(config.model_profile_version).toBeNull();
  expect(config.max_model_rounds).toBe(6);
  expect((config.codex as Record<string, unknown>).version).toBe('0.169.0');
  await expect(section(page).locator('[role="alert"]')).toHaveCount(0);
});

test('P7-UI-02 switching React -> Codex -> React -> Codex loses nothing', async ({ page }) => {
  const harness = await open(page, {});
  const choose = async (label: string) => {
    await page.getByLabel('运行方式').click();
    await page.locator('.ant-select-item-option-content', { hasText: label }).click();
  };
  await choose('代码任务（命令行）');
  await expect(page.getByLabel('Chat 模型方案')).toHaveCount(0);
  await expect(section(page).locator('[role="alert"]')).toHaveCount(0);
  await choose('对话模型（平台内置）');
  await expect(section(page).locator('[role="alert"]')).toHaveCount(0);
  await expect(page.getByLabel('Chat 模型方案')).toHaveValue('6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f');
  await choose('代码任务（命令行）');
  await expect(page.getByLabel('Codex 版本')).toHaveCount(0);
  await page.getByLabel('Agent 简介').fill('保存时自动纠正 Codex 版本');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const config = harness.saves[0].config as Record<string, unknown>;
  expect(config.react).toBeUndefined();
  expect((config.codex as Record<string, unknown>).version).toBe('0.169.0');
});

test('P7-UI-03 (bug 1) a structured 422 names each field instead of a vague sentence', async ({ page }) => {
  const harness = await open(page, { saveStatus: 422, saveError: FIELD_422 });
  await page.getByLabel('Agent 简介').fill('触发一次保存');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const alert = page.locator('.agent-workspace > .alert.error');
  await expect(alert).toContainText('请检查以下字段的必填项与输入格式');
  await expect(alert).toContainText('codex.version');
  await expect(alert).toContainText('不能为空');
  await expect(alert).toContainText('system_prompt');
  await expect(alert).toContainText('此项为必填');
  await expect(alert).not.toContainText('请检查必填项和输入格式 (422)');
  await expect(alert).not.toContainText('422 ·');
});

test('UI-01 the Engine triple is gone and only the active engine configuration is shown', async ({ page }) => {
  await open(page, {});
  await expect(page.getByLabel('Engine 三元组')).toHaveCount(0);
  await expect(section(page).getByText(/native \/ v1|cli_exec \/ v1/)).toHaveCount(0);
  // React engine: rounds visible, codex model picker absent.
  await expect(page.getByLabel('最大模型轮次')).toBeVisible();
  await expect(page.getByLabel('Codex 模型方案（模型网关）')).toHaveCount(0);
  await page.getByLabel('运行方式').click();
  await page.locator('.ant-select-item-option-content', { hasText: '代码任务（命令行）' }).click();
  // Codex engine: model picker visible, React rounds absent.
  await expect(page.getByLabel('Codex 模型方案（模型网关）')).toBeVisible();
  await expect(page.getByLabel('最大模型轮次')).toHaveCount(0);
  await page.locator('#agent-execution').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/agent-execution-codex.png' });
});

test('UI-02 the customer never sees a credential picker, a credential source or a secret', async ({ page }) => {
  const harness = await open(page, {
    draft: codexDraft({ codex: { ...CODEX_BLOCK, credential_ref: CREDENTIAL_REF } }),
    credentials: { items: [CREDENTIAL_META, DUPLICATE_META] },
  });
  // No free-text UUID, no library dropdown, no provenance card, no metadata fields.
  await expect(section(page).locator('input[aria-label="Codex 凭据引用（UUID）"]')).toHaveCount(0);
  await expect(section(page).locator('.agent-codex-credential-select')).toHaveCount(0);
  await expect(section(page).locator('.agent-credential-source')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '凭据来源（只读）' })).toHaveCount(0);
  await expect(page.getByLabel('密钥版本')).toHaveCount(0);
  // The runtime identity is resolved from the selected gateway profile's
  // connection at run time, so no legacy credential name is displayed here.
  await expect(section(page).getByText('运行身份', { exact: true })).toHaveCount(0);
  const text = await section(page).innerText();
  expect(text).not.toContain('sk-');
  expect(text).not.toContain('encrypted_secret');
  expect(harness.calls.filter(call => call === 'GET /execution-credentials').length).toBeGreaterThan(0);
  expect(harness.calls.filter(call => /execution-credentials/.test(call) && !call.startsWith('GET'))).toEqual([]);
});

test('UI-03 a valid platform credential is bound automatically without a customer choice', async ({ page }) => {
  const harness = await open(page, {
    draft: codexDraft(),
    credentials: { items: [CREDENTIAL_META] },
  });
  await page.getByLabel('Agent 简介').fill('自动绑定凭据');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const codex = (harness.saves[0].config as Record<string, unknown>).codex as Record<string, unknown>;
  expect(codex.credential_ref).toBe(CREDENTIAL_REF);
  // The auto-bound reference stays in the published config for the legacy
  // lane, but the credential name is no longer shown as a runtime identity.
  await expect(section(page).getByText('DeepSeek 生产密钥')).toHaveCount(0);
});

test('UI-04 the capability preview, its narrowing checkboxes and the config schema are gone', async ({ page }) => {
  await open(page, { preview: () => previewBody(), credentials: { items: [] } });
  await expect(page.getByRole('button', { name: '预览能力' })).toHaveCount(0);
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
  await expect(page.locator('.agent-capability-row')).toHaveCount(0);
  await expect(page.locator('.agent-schema-row')).toHaveCount(0);
  await expect(section(page).getByText('配置字段')).toHaveCount(0);
  await expect(section(page).getByRole('checkbox')).toHaveCount(0);
  const harness = await editor(page, {});
  await page.reload();
  expect(harness.calls.filter(call => call === 'POST /agents/execution-preview')).toEqual([]);
});

test('UI-05 only Codex-capable gateway profiles are offered; a demo connection is filtered out', async ({ page }) => {
  const PROFILE = '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f';
  // Same shape as the acceptance host: one published chat profile whose model
  // sits on a demo connection with no execution_credential_ref and no HTTPS URL.
  await open(page, {
    draft: codexDraft(),
    gatewayProfiles: { items: [{ id: PROFILE, name: '客服快速问答', enabled: true, published_version: 1, spec: { operation: 'chat', model_id: 'demo-model' } }], total: 1 },
    gatewayModels: { items: [{ id: 'demo-model', name: 'Demo', enabled: true, published_version: 1, spec: { tool_calling: true, connection_id: 'demo-conn' } }], total: 1 },
    gatewayConnections: { items: [{ id: 'demo-conn', name: 'Demo', enabled: true, published_version: null, spec: { base_url: '', protocol: 'demo' } }], total: 1 },
  });
  const picker = page.getByLabel('Codex 模型方案（模型网关）');
  await expect(picker).toBeVisible();
  // The unusable profile never reaches the option list; only the unbound entry remains.
  await picker.click();
  await expect(page.locator('.ant-select-item-option-content', { hasText: '客服快速问答' })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(section(page).getByText('暂无可用于代码任务的模型方案：模型网关连接尚未配置运行凭据或工具调用能力，请联系管理员。')).toBeVisible();
});

test('UI-06 a capable gateway profile stays selectable', async ({ page }) => {
  const harness = await open(page, { draft: codexDraft() });
  const picker = page.getByLabel('Codex 模型方案（模型网关）');
  await picker.click();
  await expect(page.locator('.ant-select-item-option-content', { hasText: '线上方案 · v3' })).toBeVisible();
  await page.locator('.ant-select-item-option-content', { hasText: '线上方案 · v3' }).click();
  await expect(section(page).getByText('暂无可用于代码任务的模型方案：模型网关连接尚未配置运行凭据或工具调用能力，请联系管理员。')).toHaveCount(0);
  await page.getByLabel('Agent 简介').fill('绑定可用的模型方案');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const codex = (harness.saves[0].config as Record<string, unknown>).codex as Record<string, unknown>;
  expect(codex.model_profile_id).toBe('6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f');
  expect(codex.model_profile_version).toBe(3);
});

test('UI-07 the credential-invalid error points at configuration instead of a removed picker', async ({ page }) => {
  await open(page, { saveStatus: 409, saveError: 'codex_credential_invalid' });
  await page.getByLabel('Agent 简介').fill('触发一次发布拒绝');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(section(page).locator('[role="alert"]')).toContainText(
    'Codex 运行凭据无效或未配置，发布已阻止，请联系管理员核对凭据库或模型网关连接配置。');
  await expect(section(page).locator('[role="alert"]')).not.toContainText('请重新选择有效凭据');
});

test('P3-FE-11 a rejected save points at the offending execution field', async ({ page }) => {
  await open(page, { saveStatus: 409 });
  await page.getByLabel('Agent 简介').fill('触发一次保存');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(section(page).locator('[role="alert"]')).toContainText('所选 Engine 未注册或已停用，无法预览或发布。');
});

const OFF_HINT = '当前部署未启用代码执行能力，运行方式不可切换；平台对话模型不受影响。';
const MISCONFIG_HINT = '执行服务暂不可用，请联系运维核对部署配置。';

test('P3-FE-14 (M3) phase3 off hides the runtime selector and keeps the React path intact', async ({ page }) => {
  const harness = await open(page, { flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true } });
  await expect(section(page).getByText(OFF_HINT)).toBeVisible();
  await expect(page.getByLabel('运行方式')).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /收窄/ })).toHaveCount(0);
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
  await expect(page.getByLabel('Chat 模型方案')).toBeEnabled();
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('8');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect((harness.saves[0].config as Record<string, unknown>).max_model_rounds).toBe(8);
  await page.getByRole('button', { name: '版本历史' }).click();
  await expect(page.getByRole('heading', { name: '发布历史' })).toBeVisible();
  expect(harness.previews).toEqual([]);
  expect(harness.calls.filter(call => call.startsWith('POST'))).toEqual([]);
  const runCalls = harness.calls.filter(call => /\/runs(\?|$|\/)/.test(call) || /\/conversations/.test(call));
  expect(runCalls).toEqual([]);
});

test('P3-FE-15 (M3) the on + orchestrator-off mismatch warns without any fake success', async ({ page }) => {
  await open(page, {
    flags: { execution_phase3_enabled: true, execution_orchestrator_enabled: false },
  });
  await expect(section(page).getByText(MISCONFIG_HINT)).toBeVisible();
  await expect(section(page).getByLabel('运行方式')).toBeEnabled();
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
});

test('P3-FE-16 (M3) a failed flags read hides the runtime selector fail-closed', async ({ page }) => {
  const harness = await open(page, { flagsStatus: 500 });
  const afterOpen = await settleReads(page, harness);
  expect(afterOpen).toBeGreaterThanOrEqual(1);
  await expect(page.getByLabel('运行方式')).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /收窄/ })).toHaveCount(0);
  await expect(section(page).getByText(OFF_HINT)).toHaveCount(0);
  await expect(section(page).getByText(MISCONFIG_HINT)).toHaveCount(0);
  const rounds = page.getByLabel('最大模型轮次');
  await rounds.fill('9');
  await rounds.press('Enter');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect(flagsReads(harness)).toBe(afterOpen);
});

test('P3-FE-16b the flags pair is read once per editor lifetime', async ({ page }) => {
  const harness = await open(page, {});
  const afterOpen = await settleReads(page, harness);
  expect(afterOpen).toBeGreaterThanOrEqual(1);
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
    await expect(page.getByLabel(tr(language, '运行方式'))).toHaveCount(0);
    if (language === 'en' || language === 'hi') {
      // Only platform copy must be translated; a mock profile name is user data.
      const hint = section(page).getByText(tr(language, OFF_HINT));
      expect(await hint.innerText()).not.toMatch(/[㐀-鿿]/);
    }
  });
  test(`P3-FE-18 ${language} translates the deployment misconfiguration hint`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
    await open(page, { flags: { execution_phase3_enabled: true, execution_orchestrator_enabled: false } }, language);
    await expect(section(page).getByText(tr(language, MISCONFIG_HINT))).toBeVisible();
    if (language === 'en' || language === 'hi') {
      const hint = section(page).getByText(tr(language, MISCONFIG_HINT));
      expect(await hint.innerText()).not.toMatch(/[㐀-鿿]/);
    }
  });
}

test('P3-FE-19 (M3) a save the server refuses while phase3 is off stays translated, located and non-unlocking', async ({ page }) => {
  const language = 'hi';
  const local = (key: string) => tr(language, key);
  await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
  const harness = await open(page, {
    flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true },
    draft: legacyDraft({ disabled_capabilities: ['terminal_execution'] }),
    saveStatus: 409,
    saveError: 'execution_configuration_invalid',
  }, language);
  const rounds = page.getByLabel(local('最大模型轮次'));
  await rounds.fill('8');
  await rounds.press('Enter');
  await page.getByRole('button', { name: local('保存草稿'), exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const alert = section(page).locator('[role="alert"]');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(local('执行配置不合法，请检查标记的字段。'));
  await expect(alert).toContainText('409 · execution_configuration_invalid');
  expect(await alert.innerText()).not.toMatch(/[㐀-鿿]/);
  expect(await alert.innerText()).not.toContain(local('请求失败，请重试或联系管理员'));
  await expect(page.getByLabel(local('运行方式'))).toHaveCount(0);
  await expect(page.locator('.agent-capability-preview')).toHaveCount(0);
  await expect(section(page).getByRole('checkbox')).toHaveCount(0);
  await expect(section(page).getByText(local(OFF_HINT))).toBeVisible();
  await expect(section(page).getByText(local(MISCONFIG_HINT))).toHaveCount(0);
  await expect(rounds).toHaveValue('8');
  await expect(page.getByLabel(local('Chat 模型方案'))).toHaveValue('6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f');
  await expect(saveState(page)).toContainText(local('有未保存修改'));
  expect(harness.previews).toEqual([]);
  expect(harness.calls.filter(call => call.startsWith('POST') || call.includes('/agents/execution-preview'))).toEqual([]);
});

test('P3-FE-20 (M3) phase3 off still opens the conversation records and a past Run', async ({ page }) => {
  const harness = await open(page, { flags: { execution_phase3_enabled: false, execution_orchestrator_enabled: true } });
  await expect(page.getByLabel('运行方式')).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /收窄/ })).toHaveCount(0);
  await recordsStayOpen(page);
  expect(harness.calls.filter(call => call === 'GET /runs/run-record/events').length).toBeGreaterThanOrEqual(1);
  expect(harness.calls.filter(call => !call.startsWith('GET'))).toEqual([]);
  expect(harness.previews).toEqual([]);
  expect(harness.saves).toEqual([]);
});

test('P3-FE-21 (M3) a failed flags read still leaves the records and Run viewable', async ({ page }) => {
  const harness = await open(page, { flagsStatus: 500 });
  await settleReads(page, harness);
  await expect(page.getByLabel('运行方式')).toHaveCount(0);
  await expect(section(page).getByText(OFF_HINT)).toHaveCount(0);
  await recordsStayOpen(page);
  expect(harness.calls.filter(call => call === 'GET /runs/run-record/events').length).toBeGreaterThanOrEqual(1);
  expect(harness.calls.filter(call => !call.startsWith('GET'))).toEqual([]);
  expect(harness.previews).toEqual([]);
});

// The stable error codes and every sentence they resolve to must exist in all
// four locales; check:i18n only scans t('literal') call sites, not this table.
function errorTextCodeTable(): Record<string, string> {
  const source = readFileSync(fileURLToPath(new URL('../src/i18n/index.ts', import.meta.url)), 'utf8');
  const block = source.split('const known:Record<string,string>={')[1];
  expect(block, 'errorText must keep its `known` code table').toBeTruthy();
  const table: Record<string, string> = {};
  for (const line of block!.split('\n  };')[0].split('\n')) {
    const entry = /^\s*([a-z][a-z0-9_]*):\s*(?:t\()?["']([^"']*)["']\)?,?$/.exec(line);
    if (entry)
      table[entry[1]] = entry[2];
  }
  return table;
}
const UNTRANSLATED_ERROR_COPY = ['model_not_configured'];

test('P3-FE-13 every new execution key exists in all four locales', () => {
  const keys = [
    '模型与运行', '运行方式', '最大模型轮次', 'Codex 模型方案（模型网关）',
    '对话模型（平台内置）', '代码任务（命令行）',
    '选择运行方式，再配置该方式的模型方案；密钥、路径等细节由平台统一处理。',
    '一次回答中最多调用模型的次数，范围 1–30。',
    '代码任务在此处选择 Codex 模型方案，其余运行细节由平台统一处理；此处无需绑定 Chat 方案。',
    '未绑定（使用部署默认）', '执行配置不合法，请检查标记的字段。', '字段 {{v0}}：{{v1}}',
    '所选 Engine 未注册或已停用，无法预览或发布。',
    '{{v0}} 与 {{v1}} 取值不一致，请保留其中一处后再保存。',
    OFF_HINT, MISCONFIG_HINT,
    '请检查以下字段的必填项与输入格式', '此项为必填', '不能为空',
    '需要填写整数', '需要填写数字', '需要填写文本', '需要填写布尔值',
    '需要填写有效的 UUID', '不支持此字段，请删除',
    '文本长度不能超过 {{v0}} 个字符', '文本长度至少 {{v0}} 个字符',
    '数值不能小于 {{v0}}', '数值不能大于 {{v0}}',
    '取值必须是允许值之一', '取值格式不正确',
    '当前 Engine 不支持旧版 React 字段，请清除模型方案或切回 React Engine',
    '执行凭据已失效或不在允许范围内，请联系运维核对凭据库并重新绑定有效凭据。',
    'Codex 模型方案无效或不支持工具调用，请检查模型网关配置。',
    'Codex 运行凭据无效或未配置，发布已阻止，请联系管理员核对凭据库或模型网关连接配置。',
    '暂无可用于代码任务的模型方案：模型网关连接尚未配置运行凭据或工具调用能力，请联系管理员。',
    'Codex 运行凭据无效或未配置，发布已阻止，请联系管理员核对凭据库或模型网关连接配置。',
    '暂无可用于代码任务的模型方案：模型网关连接尚未配置运行凭据或工具调用能力，请联系管理员。',
    '运行遇到未分类的内部故障，请重试或联系管理员。',
  ];
  for (const key of keys) {
    for (const language of Object.keys(DICTIONARIES)) {
      const value = DICTIONARIES[language][key];
      expect(value, `${language} misses ${key}`).toBeTruthy();
      expect(value!.trim(), `${language} has an empty ${key}`).toBeTruthy();
      expect(JSON.stringify([...value!.matchAll(/{{\s*(\w+)\s*}}/g)].map(m => m[1]).sort()), `${language} placeholders for ${key}`)
        .toBe(JSON.stringify([...key.matchAll(/{{\s*(\w+)\s*}}/g)].map(m => m[1]).sort()));
    }
  }
  const table = errorTextCodeTable();
  expect(Object.keys(table).length, 'the errorText code table was not parsed').toBeGreaterThan(0);
  const executionCodes = Object.keys(table).filter(code => code.startsWith('execution_')).sort();
  expect(executionCodes).toEqual([
    'execution_configuration_invalid',
    'execution_credential_unavailable',
    'execution_engine_unavailable',
    'execution_error',
    'execution_phase3_disabled',
    'execution_policy_unavailable',
  ]);
  const untranslated: string[] = [];
  for (const [code, sentence] of Object.entries(table)) {
    const placeholders = (value: string) => JSON.stringify([...value.matchAll(/{{\s*(\w+)\s*}}/g)].map(match => match[1]).sort());
    let missing = false;
    for (const language of Object.keys(DICTIONARIES)) {
      const value = DICTIONARIES[language][sentence];
      if (!value || !value.trim()) { missing = true; continue; }
      expect(placeholders(value), `${language} changes the placeholders of ${code}`).toBe(placeholders(sentence));
      if (language === 'en' || language === 'hi') expect(value).not.toMatch(/[㐀-鿿]/);
    }
    if (missing) untranslated.push(code);
  }
  for (const code of untranslated) expect(UNTRANSLATED_ERROR_COPY).toContain(code);
  expect(keys.length).toBeGreaterThanOrEqual(39);
});

test('I161-01 (issue #161) engine round trip keeps the React Chat binding through save, publish and reload', async ({ page }) => {
  const PROFILE = '6f6f6f6f-6f6f-4f6f-8f6f-6f6f6f6f6f6f';
  const harness = await open(page, { draft: legacyDraft() });
  const choose = async (label: string) => {
    await page.getByLabel('运行方式').click();
    await page.locator('.ant-select-item-option-content', { hasText: label }).click();
  };
  await expect(page.getByLabel('Chat 模型方案')).toHaveValue(PROFILE);
  await choose('代码任务（命令行）');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  const savedCodex = harness.saves[0].config as Record<string, unknown>;
  expect((savedCodex.engine as Record<string, unknown>).engine_id).toBe('codex');
  expect(savedCodex.react).toBeUndefined();
  expect(savedCodex.model_profile_id).toBeNull();
  expect((savedCodex.codex as Record<string, unknown>).version).toBe('0.169.0');
  await choose('对话模型（平台内置）');
  await expect(page.getByLabel('Chat 模型方案')).toHaveValue(PROFILE);
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(2);
  const savedReact = harness.saves[1].config as Record<string, unknown>;
  expect(savedReact.model_profile_id).toBe(PROFILE);
  expect((savedReact.react as Record<string, unknown>).model_profile_id).toBe(PROFILE);
  await page.getByRole('button', { name: '发布', exact: true }).click();
  await expect.poll(() => harness.calls.filter(call => call === 'POST /agents/agent-1/publish').length).toBe(1);
  await page.reload();
  await expect(page.getByLabel('Agent 名称', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Chat 模型方案')).toHaveValue(PROFILE);
});

test('I161-02 (issue #161) publishing a React draft with no Chat profile is blocked', async ({ page }) => {
  const harness = await open(page, { draft: legacyDraft({ model_profile_id: null, model_profile_version: null }) });
  await page.getByRole('button', { name: '发布', exact: true }).click();
  const alert = page.locator('.agent-workspace > .alert.error');
  await expect(alert).toContainText('请先选择已发布的 Chat 配置方案');
  expect(harness.calls.filter(call => call === 'POST /agents/agent-1/publish')).toHaveLength(0);
});

test('I162-01 Codex version, executable and timeout controls are gone', async ({ page }) => {
  await open(page, { draft: codexDraft() });
  await expect(page.getByLabel('Codex 版本')).toHaveCount(0);
  await expect(page.locator('.agent-codex-version-select')).toHaveCount(0);
  await expect(page.getByLabel('Codex 可执行文件')).toHaveCount(0);
  await expect(page.getByLabel('Codex 超时（秒）')).toHaveCount(0);
  await expect(page.getByLabel('Codex PATH')).toHaveCount(0);
  await expect(section(page).locator('input[aria-label="Codex 凭据引用（UUID）"]')).toHaveCount(0);
  await expect(section(page).locator('.agent-codex-credential-select')).toHaveCount(0);
  await expect(page.getByLabel('Codex 模型方案（模型网关）')).toBeVisible();
});

test('I162-02 selecting the codex engine saves the flag allowlist version', async ({ page }) => {
  const allowed = '0.168.0';
  const harness = await open(page, { flags: { ...FLAGS, allowed_codex_versions: [allowed] } });
  await page.getByLabel('运行方式').click();
  await page.locator('.ant-select-item-option-content', { hasText: '代码任务（命令行）' }).click();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect(((harness.saves[0].config as Record<string, unknown>).codex as Record<string, unknown>).version).toBe(allowed);
});

test('I162-03 a stale codex version is corrected to the allowlist on save', async ({ page }) => {
  const harness = await open(page, {
    draft: codexDraft({ codex: { ...CODEX_BLOCK, version: '0.150.0' } }),
    flags: { ...FLAGS, allowed_codex_versions: ['0.169.0'] },
  });
  await page.getByLabel('Agent 简介').fill('保存时自动纠正 Codex 版本');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect(((harness.saves[0].config as Record<string, unknown>).codex as Record<string, unknown>).version).toBe('0.169.0');
});

test('I162-04 an empty allowlist fabricates no version (fail-closed)', async ({ page }) => {
  const harness = await open(page, {
    draft: codexDraft({ codex: { ...CODEX_BLOCK, version: '' } }),
    flags: { ...FLAGS, allowed_codex_versions: [] },
  });
  await page.getByLabel('Agent 简介').fill('空白名单不得编造版本');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => harness.saves.length).toBe(1);
  expect(((harness.saves[0].config as Record<string, unknown>).codex as Record<string, unknown>).version).toBe('');
});
