import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Phase 6-2 · T-13 — FE-1~FE-10. Contract-level UI evidence against a mocked
// `/api/v1/**`; no real backend is needed. The four governance invariants under
// test: admin-only tab, on-demand mount, fail-closed empty/error states, and
// zero Secret/raw-sample text in the DOM.

type Dict = Record<string, string>;
const locale = (name: string) => JSON.parse(readFileSync(fileURLToPath(new URL(`../src/i18n/locales/${name}.json`, import.meta.url)), 'utf8')) as Dict;
const DICTIONARIES: Record<string, Dict> = {
  'zh-CN': locale('zh-CN'), 'zh-TW': locale('zh-TW'), en: locale('en'), hi: locale('hi'),
};
function tr(language: string, key: string): string {
  const value = DICTIONARIES[language]?.[key];
  expect(value, `locale ${language} is missing ${key}`).toBeTruthy();
  return value;
}

const GOV_KEYS = [
  'fencing-denials', 'cleanup-failures', 'outbox', 'replay-gaps',
  'usage-conflicts', 'parser-diagnostics', 'credential-audit',
] as const;
type GovKey = typeof GOV_KEYS[number];
const GOV_PREFIX = '/observability/execution/';

const page1 = { total: 25, page: 1, page_size: 10 };

/** Representative, Secret-free rows for each governance endpoint (03 §2). */
function defaultGovernance(): Record<GovKey, unknown> {
  return {
    'fencing-denials': {
      ...page1,
      items: Array.from({ length: 10 }, (_, i) => ({
        run_id: `run-fence-${i + 1}`, operation: 'write', reason: 'stale_owner',
        stale_owner: 'owner-old', stale_lease_epoch: 1, current_owner: 'owner-new',
        current_lease_epoch: 2, created_at: '2026-11-22T01:00:00Z',
        tenant_id: 'tenant-a', scope: { business_id: 'retail-biz', workspace_id: 'cn-ws' },
      })),
    },
    'cleanup-failures': {
      ...page1,
      items: [{
        run_id: 'run-cleanup-1', category: 'failed', cleanup_status: 'failed',
        cleanup_updated_at: '2026-11-22T02:00:00Z', cancel_requested_at: null,
        cancel_confirmed_at: null, tenant_id: 'tenant-b', scope: null,
      }],
    },
    outbox: {
      pending_count: 3, oldest_available_at: '2026-11-22T00:00:00Z', stall_seconds: 3661,
      last_errors: [{
        run_id: 'run-outbox-1', seq: 7, attempts: 3,
        available_at: '2026-11-22T00:00:00Z', last_error: 'delivery_timeout',
      }],
      published_24h: 42, ...page1, total: 1,
    },
    'replay-gaps': {
      ...page1,
      items: [{
        id: 'gap-1', run_id: 'run-gap-1', requested_cursor_seq: 5, retention_floor_seq: 10,
        reason_code: 'cursor_below_floor', created_at: '2026-11-22T03:00:00Z',
        tenant_id: 'tenant-c', scope: null,
      }],
    },
    'usage-conflicts': {
      ...page1,
      items: [{
        run_id: 'run-usage-1', tenant_id: 'tenant-d', source: 'model.completed',
        source_event_id: 'evt-1', supersedes_id: null, usage: { tokens: 100 },
        cost: { usd: 0.1 }, is_estimate: false, kind: 'duplicate',
      }],
    },
    'parser-diagnostics': {
      ...page1,
      items: [{
        bucket_start: '2026-11-22T04:00:00Z', category: 'malformed', reason_code: 'bad_json',
        count: 5, tenant_id: null, run_id: null,
      }],
    },
    'credential-audit': {
      ...page1,
      items: [{
        id: 1, credential_ref: 'cred-1', action: 'revoked', outcome: 'success',
        reason_code: 'manual', actor: 'admin', created_at: '2026-11-22T05:00:00Z',
        tenant_id: 'tenant-e',
      }],
    },
  };
}

function emptyGovernance(): Record<GovKey, unknown> {
  return {
    'fencing-denials': { items: [], ...page1, total: 0 },
    'cleanup-failures': { items: [], ...page1, total: 0 },
    outbox: {
      pending_count: 0, oldest_available_at: null, stall_seconds: null,
      last_errors: [], published_24h: 0, ...page1, total: 0,
    },
    'replay-gaps': { items: [], ...page1, total: 0 },
    'usage-conflicts': { items: [], ...page1, total: 0 },
    'parser-diagnostics': { items: [], ...page1, total: 0 },
    'credential-audit': { items: [], ...page1, total: 0 },
  };
}

const SUMMARY = {
  total: 0, completed: 0, failed: 0, cancelled: 0, running: 0, queued: 0,
  average_seconds: null, p95_seconds: null, tokens: 0,
  ttfc: { p50_ms: null, p95_ms: null, samples: 0 },
};
const MEMORY = {
  window_hours: 24, extraction_daily: [], hit_rate: { customer_runs: 0, injected_runs: 0 },
  backlog: { pending: 0, oldest_age_seconds: null }, governance: [], pii_masked: 0,
  reinforce: { tasks_done: 0, tasks_failed: 0, ids_refreshed: 0 },
  decay: { decay_pending: 0, decay_expired: 0, evicted: 0, expired_restored: 0 },
  search: { calls: 0, empty: 0 },
  tasks: { pending: 0, running: 0, failed_15m: 0, oldest_pending_age_minutes: null, by_kind: [] },
  embedding: { failed_backlog: 0, retry_scanned_7d: 0, retry_succeeded_7d: 0 },
  search_modes: { vector: 0, text: 0, keyword_fallback: 0, fallback_rate: null },
  search_quality: { calls: 0, empty: 0, empty_rate: null, avg_returned: null },
  maintenance: {
    ttl_last_at: null, decay_last_at: null, rule_scan_last_at: null,
    embedding_retry_last_at: null, heartbeat_last_at: null, overdue: [],
  },
  agents: [],
  injection: { source: 'detail', avg_items: null, by_section: { flag: null, profile: null, preference: null, event: null } },
  pending_quality: { confirmed_7d: 0, rejected_7d: 0, confirm_rate: null },
};
const CAPABILITIES = {
  capabilities: {
    items: [],
    summary: { total: 0, by_status: { registered: 0, starting: 0, ready: 0, degraded: 0, stopped: 0 }, failures: 0 },
  },
  events: { published: 0, subscribers: 0, failures: 0, queue: { pending: 0, failed: 0 } },
};
const CHECKLIST = {
  overall_status: 'healthy', generated_at: '2026-11-22T05:00:00Z', scan_age_seconds: 0,
  counts: { P0: 0, P1: 0, P2: 0, P3: 0 },
  groups: [{
    id: 'workers', title: 'Workers', status: 'fail',
    items: [{
      check_id: 'worker.runtime.heartbeat', type: 'required', status: 'fail', severity: 'P1',
      title: 'Worker heartbeat', summary: '', evidence: {}, checked_at: '2026-11-22T05:00:00Z',
      first_seen_at: null, changed_at: null, stale: false, action: null,
    }],
  }],
};
const CREDENTIALS = {
  items: [{
    credential_ref: 'cred-1', tenant_id: 'tenant-e', name: '生产密钥', credential_type: 'api_key',
    key_version: 'v1', version: 1, status: 'revoked', allowed_engines: [], allowed_workspaces: [],
    created_at: '2026-11-20T00:00:00Z', updated_at: '2026-11-22T05:00:00Z',
    rotated_at: null, revoked_at: '2026-11-22T05:00:00Z',
  }],
};

interface Options {
  role?: string;
  governance?: Partial<Record<GovKey, unknown>>;
  /** Status code applied to every governance endpoint (e.g. 403). */
  govStatus?: number;
  govError?: unknown;
  checklist?: unknown;
  notifications?: unknown;
  credentials?: unknown;
}
interface Harness { calls: string[] }

/** Every `/api/v1` call, including the query, as `METHOD /path?query`. */
async function mock(page: Page, options: Options): Promise<Harness> {
  const harness: Harness = { calls: [] };
  const governance = { ...defaultGovernance(), ...(options.governance || {}) };
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    const call = `${method} ${path}${url.search}`;
    harness.calls.push(call);
    if (path === '/me') return route.fulfill({ json: { role: options.role ?? 'admin', tenant: '测试企业' } });
    if (path.startsWith(GOV_PREFIX)) {
      const key = path.slice(GOV_PREFIX.length) as GovKey;
      if (options.govStatus) return route.fulfill({ status: options.govStatus, json: { detail: options.govError ?? 'insufficient_role' } });
      return route.fulfill({ json: (governance[key] ?? { items: [], ...page1, total: 0 }) });
    }
    if (path === '/notifications/checklist') return route.fulfill({ json: options.checklist ?? CHECKLIST });
    if (path === '/notifications') return route.fulfill({ json: options.notifications ?? { items: [], total: 0 } });
    if (path === '/execution-credentials') return route.fulfill({ json: options.credentials ?? CREDENTIALS });
    // Overview panels stay mount-safe so the governance assertions are isolated.
    if (path === '/observability/summary') return route.fulfill({ json: SUMMARY });
    if (path === '/observability/memory') return route.fulfill({ json: MEMORY });
    if (path === '/observability/memory/alerts') return route.fulfill({ json: [] });
    if (path === '/observability/runs') return route.fulfill({ json: { items: [], ...page1 } });
    if (path === '/observability/gateways') return route.fulfill({ json: { models: [], tools: [], known_usage: [], window_hours: 24 } });
    if (path === '/extensions/capabilities') return route.fulfill({ json: CAPABILITIES });
    if (path === '/extensions/events') return route.fulfill({ json: { items: [], ...page1 } });
    if (path === '/audit') return route.fulfill({ json: { items: [], ...page1, action_types: [] } });
    if (path === '/modules') return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  return harness;
}

async function open(page: Page, options: Options = {}, language = 'zh-CN'): Promise<Harness> {
  await page.addInitScript(value => localStorage.setItem('agent-platform-language', value), language);
  const harness = await mock(page, options);
  await page.goto('/#/observability');
  // A second load guarantees the freshly registered route handler is used when
  // a test re-opens the same hash after `unrouteAll()`.
  await page.reload();
  await expect(page.locator('.module-observability')).toBeVisible();
  return harness;
}
const govCalls = (harness: Harness) => harness.calls.filter(call => call.includes(GOV_PREFIX));
const scope = (page: Page) => page.locator('.module-observability');
async function openGovernance(page: Page, language = 'zh-CN', options: Options = {}) {
  const harness = await open(page, options, language);
  await page.getByRole('tab', { name: tr(language, '执行治理') }).click();
  return harness;
}

test('FE-1 the 执行治理 tab is admin-only; 运行总览 is always present', async ({ page }) => {
  await open(page, { role: 'admin' });
  await expect(page.getByRole('tab', { name: '运行总览' })).toBeVisible();
  await expect(page.getByRole('tab', { name: '执行治理' })).toBeVisible();
  await page.unrouteAll();
  await open(page, { role: 'viewer' });
  await expect(page.getByRole('tab', { name: '运行总览' })).toBeVisible();
  await expect(page.getByRole('tab', { name: '执行治理' })).toHaveCount(0);
  await page.unrouteAll();
  await open(page, { role: 'operator' });
  await expect(page.getByRole('tab', { name: '执行治理' })).toHaveCount(0);
});

test('FE-2 no governance request is issued by a viewer or by the overview tab', async ({ page }) => {
  const viewer = await open(page, { role: 'viewer' });
  // Settle the StrictMode double mount; no governance call is ever legal here.
  await page.waitForTimeout(600);
  expect(govCalls(viewer)).toEqual([]);
  expect(viewer.calls.some(c => c.includes('/execution-credentials'))).toBe(false);
  await page.unrouteAll();
  const admin = await open(page, { role: 'admin' });
  await expect(page.getByRole('heading', { name: '记忆观测' })).toBeVisible();
  await page.waitForTimeout(600);
  expect(govCalls(admin)).toEqual([]);
  expect(admin.calls.some(c => c.includes('/execution-credentials'))).toBe(false);
});

test('FE-3 activation mounts all signals; leaving the tab unmounts and stops polling', async ({ page }) => {
  const harness = await open(page, { role: 'admin' });
  await page.getByRole('tab', { name: '执行治理' }).click();
  await expect(scope(page).getByRole('heading', { name: 'Fencing 拒绝' })).toBeVisible();
  for (const key of GOV_KEYS) {
    await expect.poll(() => harness.calls.some(c => c.includes(`${GOV_PREFIX}${key}`))).toBe(true);
  }
  // SIG-8 status + SIG-2 Worker status reuse existing routes.
  expect(harness.calls.some(c => c.includes('/execution-credentials'))).toBe(true);
  expect(harness.calls.some(c => c.includes('/notifications/checklist'))).toBe(true);
  await page.getByRole('tab', { name: '运行总览' }).click();
  await expect(scope(page).getByRole('heading', { name: 'Fencing 拒绝' })).toHaveCount(0);
  const baseline = govCalls(harness).length;
  await page.waitForTimeout(700);
  expect(govCalls(harness).length).toBe(baseline);
});

test('FE-4 all eight governance signals render with representative rows', async ({ page }) => {
  await openGovernance(page);
  for (const title of [
    'Fencing 拒绝', 'Worker 状态', '清理失败与取消未确认', 'Outbox 投递状态',
    'SSE 重放缺口', 'Usage 冲突与修正链', 'Parser 诊断', '凭据吊销与审计',
  ]) {
    await expect(scope(page).getByRole('heading', { name: title, exact: true })).toBeVisible();
  }
  await expect(scope(page).getByRole('cell', { name: 'run-fence-1', exact: true })).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: 'tenant-a' }).first()).toBeVisible();
  // Real backend scope is the object {business_id, workspace_id}.
  await expect(scope(page).getByRole('cell', { name: 'retail-biz / cn-ws' }).first()).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: 'delivery_timeout' })).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: 'cursor_below_floor' })).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: '格式错误' })).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: 'run-usage-1' })).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: '生产密钥' })).toBeVisible();
  await expect(scope(page).getByText('3', { exact: true }).first()).toBeVisible();
  await expect(scope(page).getByText('3661.0s')).toBeVisible();
  await expect(scope(page).getByText('42', { exact: true }).first()).toBeVisible();
});

test('FE-5 filters change the server query for category/kind/action', async ({ page }) => {
  const harness = await openGovernance(page);
  const query = (endpoint: string, param: string) => harness.calls.some(c =>
    c.startsWith(`GET ${GOV_PREFIX}${endpoint}?`) && c.includes(param));
  // credential-audit defaults to action=revoked.
  await expect.poll(() => query('credential-audit', 'action=revoked')).toBe(true);
  await page.getByLabel('清理类别').click();
  await page.locator('.ant-select-item-option-content', { hasText: '取消未确认' }).click();
  await expect.poll(() => query('cleanup-failures', 'category=unconfirmed_cancel')).toBe(true);
  await page.getByLabel('冲突类别').click();
  await page.locator('.ant-select-item-option-content', { hasText: '重复来源' }).click();
  await expect.poll(() => query('usage-conflicts', 'kind=duplicate')).toBe(true);
  await page.getByLabel('诊断类别').click();
  await page.locator('.ant-select-item-option-content', { hasText: '格式错误' }).click();
  await expect.poll(() => query('parser-diagnostics', 'category=malformed')).toBe(true);
  // A filter never turns into a non-GET request.
  expect(govCalls(harness).filter(c => !c.startsWith('GET'))).toEqual([]);
});

test('FE-6 pagination is server-side and advances the page parameter', async ({ page }) => {
  const harness = await openGovernance(page);
  await expect.poll(() => harness.calls.some(c => c.includes(`${GOV_PREFIX}fencing-denials?`) && c.includes('page=1'))).toBe(true);
  await expect.poll(() => harness.calls.some(c => c.includes(`${GOV_PREFIX}fencing-denials?`) && c.includes('page_size=10'))).toBe(true);
  await scope(page).locator('.ant-pagination-next').first().click();
  await expect.poll(() => harness.calls.some(c =>
    c.startsWith(`GET ${GOV_PREFIX}fencing-denials?`) && /[?&]page=2(&|$)/.test(c))).toBe(true);
});

test('FE-7 empty responses fail closed into a stable empty state', async ({ page }) => {
  await open(page, { role: 'admin', governance: emptyGovernance() });
  await page.getByRole('tab', { name: '执行治理' }).click();
  await expect(scope(page).getByRole('heading', { name: 'Fencing 拒绝' })).toBeVisible();
  expect(await scope(page).getByText('暂无治理数据').count()).toBeGreaterThanOrEqual(7);
  await expect(scope(page).getByRole('cell', { name: 'run-fence-1' })).toHaveCount(0);
  await expect(scope(page).getByRole('alert')).toHaveCount(0);
  // Outbox metrics show no fabricated pending/stall/published values.
  await expect(scope(page).getByText('3661.0s')).toHaveCount(0);
  await expect(scope(page).getByText('42', { exact: true })).toHaveCount(0);
});

test('FE-8 a 403 on every governance endpoint fails closed without data', async ({ page }) => {
  await open(page, { role: 'admin', govStatus: 403, govError: 'insufficient_role' });
  await page.getByRole('tab', { name: '执行治理' }).click();
  await expect(scope(page).getByRole('heading', { name: 'Fencing 拒绝' })).toBeVisible();
  await expect(scope(page).getByRole('alert').first()).toBeVisible();
  await expect(scope(page).getByRole('cell', { name: 'run-fence-1' })).toHaveCount(0);
  await expect(scope(page).getByRole('cell', { name: 'cursor_below_floor' })).toHaveCount(0);
  // Fail-closed never synthesizes a healthy metric.
  await expect(scope(page).getByText('3661.0s')).toHaveCount(0);
});

test('FE-9 Secret, key and raw-sample canaries never reach the DOM', async ({ page }) => {
  await openGovernance(page, 'zh-CN', {
    governance: {
      'fencing-denials': {
        ...page1, total: 1,
        items: [{
          run_id: 'run-fence-1', operation: 'write', reason: 'sk-SECRET-CANARY-FE9',
          stale_owner: null, stale_lease_epoch: null, current_owner: null, current_lease_epoch: null,
          created_at: '2026-11-22T01:00:00Z', tenant_id: 'tenant-a',
          scope: { business_id: 'API_KEY_CANARY_SCOPE', workspace_id: 'cn-ws' },
        }],
      },
      outbox: {
        pending_count: 1, oldest_available_at: null, stall_seconds: 1,
        last_errors: [{
          run_id: 'run-outbox-1', seq: 1, attempts: 1, available_at: '2026-11-22T00:00:00Z',
          last_error: 'RAW_SAMPLE_CANARY leaked',
        }],
        published_24h: 0, ...page1, total: 1,
      },
      'credential-audit': {
        ...page1, total: 1,
        items: [{
          id: 9, credential_ref: 'cred-1', action: 'revoked', outcome: 'success',
          reason_code: 'PASSWORD_CANARY_CODE', actor: 'admin',
          created_at: '2026-11-22T05:00:00Z', tenant_id: 'tenant-e',
        }],
      },
    },
    credentials: { items: [{ ...CREDENTIALS.items[0], name: '生产密钥 sk-KEY-CANARY-FE9' }] },
  });
  const text = await scope(page).innerText();
  for (const canary of [
    'sk-SECRET-CANARY-FE9', 'RAW_SAMPLE_CANARY',
    'API_KEY_CANARY_SCOPE', 'PASSWORD_CANARY_CODE', 'sk-KEY-CANARY-FE9',
  ]) {
    expect(text, `canary ${canary} leaked into the DOM`).not.toContain(canary);
  }
  expect(text).toContain('已隐藏');
});

test('FE-10 four locales translate the tab; hashRouter and global nav stay unchanged', async ({ page }) => {
  for (const language of ['zh-CN', 'zh-TW', 'en', 'hi']) {
    await page.unrouteAll();
    // English/Hindi copy checks must not be polluted by Chinese fixture data.
    const harness = await open(page, { role: 'admin', credentials: { items: [] } }, language);
    const governanceTab = page.getByRole('tab', { name: tr(language, '执行治理') });
    await expect(governanceTab).toBeVisible();
    await governanceTab.click();
    await expect(scope(page).getByRole('heading', { name: tr(language, 'Fencing 拒绝') })).toBeVisible();
    await expect(scope(page).getByText(tr(language, '暂无治理数据')).first()).toBeVisible();
    // A page-local tab never rewrites the URL hash.
    expect(new URL(page.url()).hash).toBe('#/observability');
    if (language === 'en' || language === 'hi') {
      expect(await scope(page).innerText()).not.toMatch(/[㐀-鿿]/);
    }
    expect(govCalls(harness).length).toBeGreaterThan(0);
  }
  // R-7: no new route or global navigation entry was introduced.
  const router = readFileSync(fileURLToPath(new URL('../src/app/hashRouter.ts', import.meta.url)), 'utf8');
  expect(router).not.toMatch(/observability\/:/);
  expect(router).toContain("'observability'");
  const app = readFileSync(fileURLToPath(new URL('../src/app/App.tsx', import.meta.url)), 'utf8');
  expect(app).not.toContain("['执行治理'");
  expect(app).not.toContain("'governance'");
});
