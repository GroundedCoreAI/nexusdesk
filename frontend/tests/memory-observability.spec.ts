import { test, expect, type Page } from '@playwright/test';

/** Full Phase 7 memory_summary payload; maintenance and alerts vary per test. */
function memorySummary(overrides: Record<string, unknown> = {}) {
  return {
    window_hours: 24,
    extraction_daily: [],
    hit_rate: { customer_runs: 10, injected_runs: 6 },
    backlog: { pending: 3, oldest_age_seconds: 7200 },
    governance: [],
    pii_masked: 7,
    reinforce: { tasks_done: 5, tasks_failed: 1, ids_refreshed: 42 },
    decay: { decay_pending: 6, decay_expired: 2, evicted: 9, expired_restored: 1 },
    search: { calls: 8, empty: 3 },
    tasks: {
      pending: 2, running: 1, failed_15m: 0, oldest_pending_age_minutes: 95,
      by_kind: [{ kind: 'memory_extract', avg_ms: 120, p95_ms: 300, done: 5, failed: 1 }],
    },
    embedding: { failed_backlog: 4, retry_scanned_7d: 10, retry_succeeded_7d: 9 },
    search_modes: { vector: 6, text: 2, keyword_fallback: 1, fallback_rate: 0.11 },
    search_quality: { calls: 8, empty: 3, empty_rate: 0.375, avg_returned: 2.5 },
    maintenance: {
      ttl_last_at: '2026-10-26T01:00:00Z', decay_last_at: '2026-10-26T01:05:00Z',
      rule_scan_last_at: '2026-10-26T01:10:00Z', embedding_retry_last_at: '2026-10-26T01:15:00Z',
      heartbeat_last_at: '2026-10-26T01:20:00Z', overdue: [],
    },
    agents: [{ agent_id: 'a1b2c3d4-e5f6-4a7b-8c9d-000000000000', customer_runs: 10, injected_runs: 6, inject_rate: 0.6, items_written: 21, tasks_failed: 0 }],
    injection: { source: 'detail', avg_items: 3.2, by_section: { flag: 1, profile: 2, preference: 2, event: 1 } },
    pending_quality: { confirmed_7d: 4, rejected_7d: 1, confirm_rate: 0.8 },
    ...overrides,
  };
}

async function mockApi(page: Page, memory: unknown, alerts: unknown, seen: string[]) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    seen.push(path + url.search);
    if (path.endsWith('/me')) return route.fulfill({ json: { role: 'viewer', tenant: '测试企业' } });
    if (path.endsWith('/observability/memory/alerts')) return route.fulfill({ json: alerts });
    if (path.endsWith('/observability/memory')) return route.fulfill({ json: memory });
    if (path.endsWith('/observability/summary')) return route.fulfill({ json: {} });
    if (path.endsWith('/observability/runs')) return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 10 } });
    if (path.endsWith('/observability/gateways')) return route.fulfill({ json: { models: [], tools: [], known_usage: [] } });
    if (path.endsWith('/modules')) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
}

test('memory observability renders grouped health sections with overdue emphasis', async ({ page }) => {
  const seen: string[] = [];
  const memory = memorySummary({
    maintenance: {
      ttl_last_at: '2026-10-26T01:00:00Z', decay_last_at: '2026-10-26T01:05:00Z',
      rule_scan_last_at: null, embedding_retry_last_at: '2026-10-26T01:15:00Z',
      heartbeat_last_at: '2026-10-26T01:20:00Z', overdue: ['rule_scan'],
    },
  });
  await mockApi(page, memory, [], seen);
  await page.goto('/#/observability');
  for (const group of ['任务健康', 'Embedding', '检索', '维护任务', 'Agent 维度', '记忆注入', '记忆质量'])
    await expect(page.getByRole('heading', { name: group, exact: true })).toBeVisible();
  // Overdue maintenance job: red banner naming the job + red cell value.
  await expect(page.getByRole('alert').filter({ hasText: '以下维护任务已超期：规则扫描' })).toBeVisible();
  await expect(page.locator('.metric .error-text')).toHaveCount(1);
  // Tabular groups render their rows.
  await expect(page.getByRole('cell', { name: 'memory_extract' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'a1b2c3d4' })).toBeVisible();
  await expect(page.getByRole('cell', { name: '60%' })).toBeVisible();
  // Rates render as percentages; fractional averages keep one decimal.
  await expect(page.getByText('11%')).toBeVisible();
  await expect(page.getByText('2.5')).toBeVisible();
});

test('memory alerts list renders rule labels and em dash for null values', async ({ page }) => {
  const seen: string[] = [];
  const alerts = [
    { rule: 'vector_fallback', at: '2026-10-26T02:00:00Z', value: 0.42, threshold: 0.2, window: '24h' },
    { rule: 'worker_heartbeat', at: '2026-10-26T01:30:00Z', value: null, threshold: null, window: '30m' },
  ];
  await mockApi(page, memorySummary(), alerts, seen);
  await page.goto('/#/observability');
  const panel = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: '记忆告警' }) });
  await expect(panel.getByRole('cell', { name: '向量检索频繁降级' })).toBeVisible();
  await expect(panel.getByRole('cell', { name: '记忆 Worker 心跳失联' })).toBeVisible();
  await expect(panel.getByRole('cell', { name: '0.42' })).toBeVisible();
  await expect(panel.getByRole('cell', { name: '0.2', exact: true })).toBeVisible();
  // Both null columns of the heartbeat row render as an em dash.
  await expect(panel.getByRole('row', { name: /记忆 Worker 心跳失联/ }).getByRole('cell', { name: '—' })).toHaveCount(2);
});

test('memory window switch refetches summary and alerts with window_hours=168', async ({ page }) => {
  const seen: string[] = [];
  await mockApi(page, memorySummary(), [], seen);
  await page.goto('/#/observability');
  await expect(page.getByRole('heading', { name: '记忆观测' })).toBeVisible();
  expect(seen.some(u => u.startsWith('/api/v1/observability/memory?window_hours=24'))).toBeTruthy();
  expect(seen.some(u => u.startsWith('/api/v1/observability/memory/alerts?window_hours=24'))).toBeTruthy();
  await page.getByLabel('统计窗口').click();
  await page.getByText('近 7 天', { exact: true }).click();
  await expect.poll(() => seen.some(u => u.startsWith('/api/v1/observability/memory?window_hours=168'))).toBeTruthy();
  await expect.poll(() => seen.some(u => u.startsWith('/api/v1/observability/memory/alerts?window_hours=168'))).toBeTruthy();
});
