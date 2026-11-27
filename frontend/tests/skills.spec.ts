import { test, expect, type Page } from '@playwright/test';
import type {
  ReadinessCheck,
  SkillPackageInfo,
  SkillReadiness,
  SkillRecord,
  SkillTemplate,
  SkillTestRun,
  SkillVersion,
} from '../src/features/skills/contracts';

interface MockOptions {
  catalogMode?: 'normal' | 'empty' | 'error' | 'slow';
  catalogGate?: Promise<void>;
  detailStatus?: number;
  aiEnabled?: boolean;
  saveConflictOnce?: boolean;
  saveValidationErrors?: unknown[];
  historyMode?: 'normal' | 'error-after-run';
  testStatus?: SkillTestRun['status'];
  testRevision?: number;
  testErrorCode?: string;
  testOutput?: unknown;
  readinessChecks?: ReadinessCheck[];
  readinessReady?: boolean;
  versions?: SkillVersion[];
  skills?: SkillRecord[];
  publishVersion?: SkillVersion;
  rollbackVersion?: SkillVersion;
  packageAttached?: SkillPackageInfo;
  packageRejectCode?: string;
  importRejectCode?: string;
}

interface MockState {
  skills: SkillRecord[];
  versions: SkillVersion[];
  testRuns: SkillTestRun[];
  saveCalls: number;
  lastSaveBody: unknown;
  lastRunBody: unknown;
  lastPublishBody: unknown;
  lastRollbackBody: unknown;
  historyCalls: number;
  createdRun: boolean;
  package: SkillPackageInfo | null;
  uploadCalls: number;
  lastUploadName: string | null;
  importCalls: number;
  lastImportName: string | null;
}

function definition(category: SkillRecord['category'] = 'service') {
  return {
    schema_version: 'v1' as const,
    creation_mode: 'template' as const,
    type: 'instruction' as const,
    trigger: 'agent_auto' as const,
    instructions: 'Read the customer message and return a structured summary.',
    parameters: [{
      name: 'message',
      type: 'string' as const,
      required: true,
      default: null,
      description: 'Customer message to extract.',
    }],
    output: { format: 'json' as const, schema: { type: 'object' } },
    dependencies: {
      model_profile_id: 'profile-1',
      model_profile_version: 1,
      knowledge_base_ids: ['kb-1'],
      tool_names: ['tool-read'],
      handoff_queue: null,
    },
    runtime: {
      timeout_seconds: 30,
      retry_policy: 'one' as const,
      confirmation_required: false,
      idempotency: 'optional' as const,
      error_behavior: 'fail' as const,
      max_amount: null,
    },
    permission_scope: 'workspace' as const,
  };
}

function skillRecord(overrides: Partial<SkillRecord> = {}): SkillRecord {
  return {
    id: 'skill-customer',
    key: 'customer-info-extraction',
    name: '客户信息提取',
    description: '从客户消息中提取联系人和下一步行动',
    category: 'service',
    tags: ['客户信息', '提取'],
    visibility: 'workspace',
    status: 'published',
    draft_revision: 3,
    published_version: 2,
    published_revision: 3,
    current_semver: '1.1.0',
    has_unpublished_changes: false,
    package: null,
    created_by: '张晓雯',
    updated_by: '张晓雯',
    created_at: '2026-11-20T08:00:00Z',
    updated_at: '2026-11-27T05:00:00Z',
    published_at: '2026-11-27T04:00:00Z',
    definition: definition(),
    ...overrides,
  };
}

function version(
  number: number,
  semver: string,
  releaseKind: SkillVersion['release_kind'],
  overrides: Partial<SkillVersion> = {},
): SkillVersion {
  return {
    id: `version-${number}`,
    skill_id: 'skill-customer',
    version: number,
    semver,
    release_kind: releaseKind,
    definition: definition(),
    definition_digest: `digest-${number}`,
    release_notes: `Release ${semver}`,
    source_draft_revision: number + 1,
    test_run_id: 'run-passed',
    rollback_from: null,
    created_by: '张晓雯',
    created_at: '2026-11-27T04:00:00Z',
    ...overrides,
  };
}

function runRecord(
  id: string,
  status: SkillTestRun['status'],
  revision = 3,
  overrides: Partial<SkillTestRun> = {},
): SkillTestRun {
  return {
    id,
    skill_id: 'skill-customer',
    draft_revision: revision,
    status,
    execution_kind: 'live',
    input: { message: '请提取客户信息' },
    input_summary: '{"message":"请提取客户信息"}',
    output: status === 'passed' ? { contact: '李女士', next_action: '回访' } : { diagnostic: status },
    diagnostics: { trace_id: `trace-${id}` },
    reason_code: status === 'blocked' ? 'policy_denied' : null,
    duration_ms: 128,
    executed_by: '张晓雯',
    created_at: '2026-11-27T05:10:00Z',
    ...overrides,
  };
}

function readinessChecks(): ReadinessCheck[] {
  return [
    { code: 'draft_saved', status: 'pass', reason: '当前草稿已保存', destination: 'editor' },
    { code: 'required_fields_valid', status: 'pass', reason: '必填字段有效', destination: 'editor' },
    { code: 'latest_test_passed', status: 'pass', reason: '当前修订已有通过的测试', destination: 'tests' },
    { code: 'dependencies_available', status: 'pass', reason: '全部依赖可用', destination: 'editor' },
    { code: 'permission_granted', status: 'pass', reason: '具备发布权限', destination: 'permission' },
    { code: 'publish_available', status: 'pass', reason: '发布服务可用', destination: 'versions' },
  ];
}

async function installApi(page: Page, options: MockOptions = {}) {
  const customer = skillRecord();
  const finance = skillRecord({
    id: 'skill-finance',
    key: 'invoice-extraction',
    name: '发票信息提取',
    description: '提取发票字段',
    category: 'finance',
    status: 'draft',
    published_version: null,
    published_revision: null,
    current_semver: null,
    has_unpublished_changes: false,
    definition: definition('finance'),
    updated_at: '2026-11-26T05:00:00Z',
  });
  const sales = skillRecord({
    id: 'skill-sales',
    key: 'customer-intent',
    name: '客户意图识别',
    description: '识别客户意图并进行分流',
    category: 'sales',
    status: 'draft',
    published_version: null,
    published_revision: null,
    current_semver: null,
    has_unpublished_changes: true,
    definition: definition('sales'),
    updated_at: '2026-11-25T05:00:00Z',
  });
  const skills = options.skills ?? [customer, finance, sales];
  const templates: SkillTemplate[] = [
    {
      key: 'customer-profile',
      name: '客户信息提取',
      description: '从客户对话中提取结构化联系人信息',
      category: 'service',
      type: 'instruction',
      tags: ['客户', '提取'],
      definition: null,
    },
    {
      key: 'invoice-check',
      name: '发票信息提取',
      description: '提取发票金额与抬头',
      category: 'finance',
      type: 'instruction',
      tags: ['发票'],
      definition: null,
    },
  ];
  const defaultVersions = [
    version(2, '1.1.0', 'minor'),
    version(1, '1.0.0', 'initial'),
  ];
  const state: MockState = {
    skills,
    versions: options.versions ?? defaultVersions,
    testRuns: [
      runRecord('run-failed', 'failed'),
      runRecord('run-error', 'error'),
      runRecord('run-blocked', 'blocked'),
    ],
    saveCalls: 0,
    lastSaveBody: null,
    lastRunBody: null,
    lastPublishBody: null,
    lastRollbackBody: null,
    historyCalls: 0,
    createdRun: false,
    package: options.packageAttached ?? null,
    uploadCalls: 0,
    lastUploadName: null,
    importCalls: 0,
    lastImportName: null,
  };

  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    const method = request.method();

    if (path === '/me') {
      const explicitPermissionTest = options.readinessChecks?.some(
        check => check.code === 'permission_granted' && check.status === 'fail',
      );
      return route.fulfill({
        json: explicitPermissionTest
          ? { role: 'operator', tenant: '测试企业', actor: '张晓雯', permissions: ['skill.read', 'skill.test'] }
          : { role: 'admin', tenant: '测试企业', actor: '张晓雯', permissions: [] },
      });
    }
    if (path === '/notifications/unread-count') return route.fulfill({ json: { count: 12 } });
    if (path === '/extensions/ui') return route.fulfill({ json: [] });
    if (path === '/extensions/capabilities') return route.fulfill({ json: { items: [] } });
    if (path === '/modules' || path === '/tickets') return route.fulfill({ json: [] });
    if (path === '/observability/summary') return route.fulfill({ json: {} });
    if (path === '/agents/catalog') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 12 } });
    if (path === '/model-gateway/profiles') {
      return route.fulfill({
        json: [{ id: 'profile-1', name: '客服推理模型', version: 1, enabled: true }],
      });
    }
    if (path === '/knowledge-bases') {
      return route.fulfill({ json: [{ id: 'kb-1', name: '客服知识库', enabled: true }] });
    }
    if (path === '/tools') {
      return route.fulfill({
        json: [{ name: 'tool-read', display_name: '客户资料读取', enabled: true, effect: 'read' }],
      });
    }
    if (path === '/skill-templates') {
      return route.fulfill({
        json: { items: templates, ai_generation_enabled: options.aiEnabled ?? true, ai_generation_reason: null },
      });
    }

    if (path === '/skills' && method === 'GET') {
      if (options.catalogMode === 'error') {
        return route.fulfill({ status: 503, json: { detail: 'catalog_unavailable' } });
      }
      if (options.catalogMode === 'slow') {
        await (options.catalogGate ?? new Promise(resolve => setTimeout(resolve, 1500)));
      }
      const query = url.searchParams.get('q')?.trim().toLocaleLowerCase() ?? '';
      const category = url.searchParams.get('category') ?? 'all';
      const status = url.searchParams.get('status') ?? 'all';
      const source = options.catalogMode === 'empty' ? [] : state.skills;
      const filtered = source.filter(item => (
        (!query || `${item.name} ${item.description} ${item.tags.join(' ')}`.toLocaleLowerCase().includes(query))
        && (category === 'all' || item.category === category)
        && (status === 'all' || item.status === status)
      ));
      return route.fulfill({
        json: {
          items: filtered,
          total: filtered.length,
          page: 1,
          page_size: 12,
          status_facets: [
            { value: 'published', count: filtered.filter(item => item.status === 'published').length },
            { value: 'draft', count: filtered.filter(item => item.status === 'draft').length },
          ],
          category_facets: ['service', 'finance', 'sales', 'general'].map(category => ({
            value: category,
            count: filtered.filter(item => item.category === category).length,
          })),
        },
      });
    }
    if (path === '/skills' && method === 'POST') {
      const body = request.postDataJSON() as { prompt?: string | null };
      const created = skillRecord({
        id: 'skill-created',
        key: 'new-customer-skill',
        name: body.prompt ? 'AI 创建能力' : '新建客户能力',
        description: body.prompt || '新建能力',
        draft_revision: 1,
        published_version: null,
        published_revision: null,
        current_semver: null,
        status: 'draft',
        definition: definition(),
      });
      state.skills = [created, ...state.skills];
      return route.fulfill({ status: 201, json: { skill: created } });
    }

    // Import is a create-route call, so it is matched before `/{key}` patterns.
    if (path === '/skills/import' && method === 'POST') {
      state.importCalls += 1;
      state.lastImportName = url.searchParams.get('filename');
      if (options.importRejectCode) {
        return route.fulfill({ status: 422, json: { detail: options.importRejectCode } });
      }
      const created = skillRecord({
        id: 'skill-imported',
        key: 'order-status',
        name: 'order-status',
        description: 'Answer order status questions.',
        category: 'general',
        tags: [],
        status: 'draft',
        weight_class: 'executable',
        risk_level: 'r0',
        risk_computed: 'r0',
        risk_reasons: [],
        data_scope: ['code'],
        draft_revision: 1,
        published_version: null,
        published_revision: null,
        current_semver: null,
        has_unpublished_changes: true,
        published_at: null,
        package: packageFixture(),
        definition: { ...definition('general'), creation_mode: 'package' },
      });
      state.skills = [created, ...state.skills];
      state.package = created.package;
      return route.fulfill({ status: 201, json: { skill: created } });
    }

    const packageMatch = /^\/skills\/([^/]+)\/package$/.exec(path);
    if (packageMatch) {
      const key = decodeURIComponent(packageMatch[1]);
      const current = state.skills.find(item => item.key === key);
      if (!current) return route.fulfill({ status: 404, json: { detail: 'skill_not_found' } });
      if (method === 'GET') {
        return state.package
          ? route.fulfill({ json: packageResponse(state.package) })
          : route.fulfill({ status: 404, json: { detail: 'skill_package_not_found' } });
      }
      if (method === 'POST') {
        state.uploadCalls += 1;
        state.lastUploadName = url.searchParams.get('filename');
        if (options.packageRejectCode) {
          return route.fulfill({ status: 422, json: { detail: options.packageRejectCode } });
        }
        state.package = {
          id: 'package-1',
          digest: 'sha256:' + 'a'.repeat(64),
          filename: state.lastUploadName,
          size_bytes: 20480,
          file_count: 3,
          has_scripts: true,
          entrypoint: 'scripts/main.py',
          created_by: '张晓雯',
          created_at: '2026-11-27T06:00:00Z',
          files: [
            { path: 'SKILL.md', size: 1200, sha256: 'b'.repeat(64), executable: false },
            { path: 'scripts/main.py', size: 2048, sha256: 'c'.repeat(64), executable: true },
            { path: 'references/faq.md', size: 330, sha256: 'd'.repeat(64), executable: false },
          ],
        };
        const next = {
          ...current,
          weight_class: 'executable' as const,
          draft_revision: current.draft_revision + 1,
          package: state.package,
        };
        state.skills = state.skills.map(item => item.key === key ? next : item);
        return route.fulfill({ json: { skill: next } });
      }
      if (method === 'DELETE') {
        state.package = null;
        const next = {
          ...current,
          weight_class: 'declarative' as const,
          draft_revision: current.draft_revision + 1,
          package: null,
        };
        state.skills = state.skills.map(item => item.key === key ? next : item);
        return route.fulfill({ json: { skill: next } });
      }
    }

    const detailMatch = /^\/skills\/([^/]+)$/.exec(path);
    if (detailMatch && method === 'GET') {
      if (options.detailStatus === 404) {
        return route.fulfill({ status: 404, json: { detail: 'skill_not_found' } });
      }
      const record = state.skills.find(item => item.key === decodeURIComponent(detailMatch[1]));
      return record
        ? route.fulfill({ json: { skill: record } })
        : route.fulfill({ status: 404, json: { detail: 'skill_not_found' } });
    }

    const draftMatch = /^\/skills\/([^/]+)\/draft$/.exec(path);
    if (draftMatch && method === 'PUT') {
      state.saveCalls += 1;
      state.lastSaveBody = request.postDataJSON();
      if (options.saveValidationErrors) {
        return route.fulfill({
          status: 422,
          json: {
            detail: {
              code: 'skill_definition_invalid',
              errors: options.saveValidationErrors,
            },
          },
        });
      }
      if (options.saveConflictOnce && state.saveCalls === 1) {
        return route.fulfill({ status: 409, json: { detail: 'skill_revision_conflict' } });
      }
      const current = state.skills.find(item => item.key === decodeURIComponent(draftMatch[1]));
      if (!current) return route.fulfill({ status: 404, json: { detail: 'skill_not_found' } });
      const saved = { ...current, ...(request.postDataJSON() as Partial<SkillRecord>), draft_revision: current.draft_revision + 1 };
      state.skills = state.skills.map(item => item.key === current.key ? saved : item);
      return route.fulfill({ json: { skill: saved } });
    }

    const duplicateMatch = /^\/skills\/([^/]+)\/duplicate$/.exec(path);
    if (duplicateMatch && method === 'POST') {
      const current = state.skills.find(item => item.key === decodeURIComponent(duplicateMatch[1])) ?? customer;
      return route.fulfill({
        status: 201,
        json: { skill: { ...current, id: 'skill-duplicate', key: 'duplicate-skill', name: '客户信息提取副本', draft_revision: 1 } },
      });
    }

    const testRunsMatch = /^\/skills\/([^/]+)\/test-runs$/.exec(path);
    if (testRunsMatch && method === 'GET') {
      state.historyCalls += 1;
      if (options.historyMode === 'error-after-run' && state.createdRun) {
        return route.fulfill({ status: 500, json: { detail: 'history_unavailable' } });
      }
      return route.fulfill({ json: { items: state.testRuns, total: state.testRuns.length, page: 1, page_size: 20 } });
    }
    if (testRunsMatch && method === 'POST') {
      state.lastRunBody = request.postDataJSON();
      if (options.testErrorCode) {
        return route.fulfill({ status: 409, json: { detail: options.testErrorCode } });
      }
      const result = runRecord(
        'run-live',
        options.testStatus ?? 'passed',
        options.testRevision ?? 3,
        {
          input: (request.postDataJSON() as { input: Record<string, unknown> }).input,
          ...(options.testOutput === undefined ? {} : { output: options.testOutput }),
        },
      );
      state.testRuns = [result, ...state.testRuns];
      state.createdRun = true;
      return route.fulfill({ status: 201, json: { run: result } });
    }

    const readinessMatch = /^\/skills\/([^/]+)\/readiness$/.exec(path);
    if (readinessMatch) {
      const checks = options.readinessChecks ?? readinessChecks();
      const ready = options.readinessReady ?? checks.every(check => check.status === 'pass');
      const response: SkillReadiness = {
        skill_id: 'skill-customer',
        draft_revision: 3,
        ready,
        checks,
        next_semver: '1.1.1',
      };
      return route.fulfill({ json: response });
    }

    const versionsMatch = /^\/skills\/([^/]+)\/versions$/.exec(path);
    if (versionsMatch && method === 'GET') {
      return route.fulfill({ json: { items: state.versions, total: state.versions.length, page: 1, page_size: 50 } });
    }

    const publishMatch = /^\/skills\/([^/]+)\/publish$/.exec(path);
    if (publishMatch && method === 'POST') {
      state.lastPublishBody = request.postDataJSON();
      const published = options.publishVersion ?? version(3, '1.1.1', 'patch');
      state.versions = [published, ...state.versions];
      return route.fulfill({ status: 201, json: { version: published } });
    }

    const rollbackMatch = /^\/skills\/([^/]+)\/rollback$/.exec(path);
    if (rollbackMatch && method === 'POST') {
      state.lastRollbackBody = request.postDataJSON();
      const rolledBack = options.rollbackVersion ?? version(3, '1.2.0', 'rollback', { rollback_from: 2 });
      state.versions = [rolledBack, ...state.versions];
      return route.fulfill({ status: 201, json: { version: rolledBack } });
    }

    return route.fulfill({ json: {} });
  });
  return state;
}

async function openCatalog(page: Page) {
  await page.goto('/#/skills');
  await expect(page.getByRole('heading', { name: 'Skill 能力库', exact: true })).toBeVisible();
}

test('API-backed catalog, generic key route, and not-found state', async ({ page }) => {
  const state = await installApi(page);
  await openCatalog(page);
  await expect(page.locator('[data-testid="skill-card"]')).toHaveCount(state.skills.length);
  await expect(page.getByText('3 个 Skill', { exact: true })).toBeVisible();

  await page.locator('[data-testid="skill-card"]').first().click();
  await expect(page).toHaveURL(/#\/skills\/customer-info-extraction$/);
  await expect(page.getByRole('heading', { name: '客户信息提取', exact: true })).toBeVisible();
  await expect(page.getByRole('tab')).toHaveCount(6);

  await page.goto('/#/skills/missing-skill');
  await expect(page.getByText('未找到 Skill', { exact: true })).toBeVisible();
  await expect(page.getByText('未找到 Skill「missing-skill」，它可能不存在或已被删除', { exact: true })).toBeVisible();
});

test('catalog loading, empty, and API error states stay honest', async ({ page }) => {
  let releaseCatalog: () => void;
  const catalogGate = new Promise<void>(resolve => {
    releaseCatalog = () => resolve();
  });
  await installApi(page, { catalogMode: 'slow', catalogGate });
  await page.goto('/#/skills');
  await expect(page.getByRole('heading', { name: 'Skill 能力库', exact: true })).toBeVisible();
  await expect(page.locator('[data-testid="skill-catalog-loading"]')).toBeVisible();
  releaseCatalog();
  await expect(page.locator('[data-testid="skill-card"]')).toHaveCount(3);

  await page.unrouteAll();
  await installApi(page, { catalogMode: 'empty' });
  await page.reload();
  await expect(page.getByText('没有符合当前筛选条件的 Skill', { exact: true })).toBeVisible();

  await page.unrouteAll();
  await installApi(page, { catalogMode: 'error' });
  await page.reload();
  await expect(page.getByText('无法加载 Skill 能力库', { exact: true })).toBeVisible();
  await expect(page.locator('.skill-state-actions')
    .getByRole('button', { name: /重\s*试/ })).toBeVisible();
});

test('search and category filters use API results without fixture fallback', async ({ page }) => {
  await installApi(page);
  await openCatalog(page);
  const search = page.getByLabel('搜索 Skill', { exact: true });
  await search.fill('发票');
  await expect(page.locator('[data-testid="skill-card"]')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: '发票信息提取', exact: true })).toBeVisible();

  await search.fill('不存在');
  await expect(page.locator('[data-testid="skill-card"]')).toHaveCount(0);
  await page.getByRole('button', { name: '清除筛选', exact: true }).click();
  await expect(search).toHaveValue('');
  await expect(page.locator('[data-testid="skill-card"]')).toHaveCount(3);

  await page.locator('.skills-category-tabs button').filter({ hasText: '财务' }).click();
  await expect(page.locator('[data-testid="skill-card"]')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: '发票信息提取', exact: true })).toBeVisible();
});

test('create workbench gates AI and creates from a selected template', async ({ page }) => {
  const state = await installApi(page, { aiEnabled: false });
  await page.goto('/#/skills/create');
  await expect(page.getByRole('heading', { name: '创建 Skill', exact: true })).toBeVisible();
  // Three authoring modes plus the import path.
  await expect(page.locator('.create-mode-card')).toHaveCount(4);
  await expect(page.getByText('AI 创建当前不可用', { exact: true })).toBeVisible();
  await expect(page.locator('.create-mode-card').filter({ hasText: '用 AI 创建' })
    .getByRole('button', { name: '生成草稿', exact: true })).toBeDisabled();

  await page.locator('.create-mode-card').filter({ hasText: '从模板创建' }).click();
  const templateCard = page.getByRole('radio').filter({ hasText: '客户信息提取' });
  await templateCard.click();
  await expect(templateCard).toHaveAttribute('aria-checked', 'true');
  await page.locator('.create-mode-card').filter({ hasText: '从模板创建' })
    .getByRole('button', { name: '使用模板', exact: true }).click();
  await expect(page).toHaveURL(/#\/skills\/new-customer-skill\/edit$/);
  await expect(page.getByRole('heading', { name: '基本信息', exact: true })).toBeVisible();
  await expect.poll(() => state.skills.some(item => item.key === 'new-customer-skill')).toBe(true);
});

test('editor saves drafts, blocks dirty navigation, and handles revision conflict', async ({ page }) => {
  let state = await installApi(page);
  await page.goto('/#/skills/customer-info-extraction/edit');
  await expect(page.getByRole('heading', { name: '客户信息提取', exact: true })).toBeVisible();
  const name = page.getByRole('textbox', { name: /^名称/ });
  await name.fill('客户信息提取 v2');
  await expect(page.locator('.skill-editor-actions')
    .getByRole('button', { name: /保存草稿/ })).toBeEnabled();
  await expect(page.getByText('未保存修改', { exact: true })).toBeVisible();

  await page.locator('.skill-editor-actions')
    .getByRole('button', { name: /取\s*消/ }).click();
  await expect(page.locator('.ant-modal-confirm-title').filter({ hasText: '放弃未保存的修改？' })).toBeVisible();
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();

  await page.locator('.skill-editor-actions')
    .getByRole('button', { name: /保存草稿/ }).click();
  await expect.poll(() => state.saveCalls).toBe(1);
  await expect(page.getByText('草稿已保存', { exact: true })).toBeVisible();
  await expect(page.getByText('已保存', { exact: true })).toBeVisible();

  await page.unrouteAll();
  state = await installApi(page, { saveConflictOnce: true });
  await page.goto('/#/skills/customer-info-extraction/edit');
  await page.getByRole('textbox', { name: /^名称/ }).fill('冲突草稿');
  await page.locator('.skill-editor-actions')
    .getByRole('button', { name: /保存草稿/ }).click();
  await expect(page.getByText('草稿已在其他位置变更', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '重新加载服务端草稿', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '另存为新 Skill', exact: true })).toBeVisible();
});

test('P2-IT-09 editor renders structured 422 field errors without leaking raw detail', async ({ page }) => {
  const secret = 'SUPER_SECRET_PROBE_DO_NOT_RENDER_7f3a';
  const state = await installApi(page, {
    saveValidationErrors: [{
      loc: ['definition', 'type'],
      type: 'literal_error',
      msg: "Input should be 'instruction', 'knowledge', 'query', 'action' or 'handoff'",
      input: secret,
      ctx: { expected: 'instruction' },
      url: 'https://internal.example/private/path',
    }],
  });
  await page.goto('/#/skills/customer-info-extraction/edit');
  await expect(page.getByRole('heading', { name: '客户信息提取', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: /^名称/ }).fill('客户信息提取 v3');
  await page.locator('.skill-editor-actions')
    .getByRole('button', { name: /保存草稿/ }).click();

  await expect.poll(() => state.saveCalls).toBe(1);
  const alert = page.locator('.skill-editor-alert').filter({ hasText: '草稿保存失败' });
  await expect(alert).toContainText('字段 definition.type：取值必须是允许值之一');
  await expect(page.locator('body')).not.toContainText(secret);
  await expect(page.locator('body')).not.toContainText('"errors"');
  await expect(page.locator('body')).not.toContainText('skill_definition_invalid');
  await expect(page.getByText('草稿已保存', { exact: true })).toHaveCount(0);
});

test('test workbench preserves results when history refresh fails', async ({ page }) => {
  const state = await installApi(page, { historyMode: 'error-after-run' });
  await page.goto('/#/skills/customer-info-extraction?tab=tests');
  await expect(page.getByRole('heading', { name: '测试工作台', exact: true })).toBeVisible();
  await expect(page.getByText('未通过', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('错误', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('已阻止', { exact: true }).first()).toBeVisible();

  await page.locator('#skill-test-input-message').fill('请提取客户信息');
  await page.locator('.skill-test-heading-actions')
    .getByRole('button', { name: /运行测试/ }).click();
  await expect(page.getByText('已通过', { exact: true }).first()).toBeVisible();
  await expect(page.locator('.skill-test-output pre')).toContainText('"contact": "李女士"');
  await expect(page.getByText('无法加载测试历史', { exact: true })).toBeVisible();
  await expect(page.getByText('已通过', { exact: true }).first()).toBeVisible();
  expect(state.lastRunBody).not.toBeNull();
});

test('blocked test execution and stale results remain explicit', async ({ page }) => {
  const state = await installApi(page, {
    testErrorCode: 'skill_test_execution_blocked',
  });
  await page.goto('/#/skills/customer-info-extraction?tab=tests');
  await page.locator('#skill-test-input-message').fill('请提取客户信息');
  await page.locator('.skill-test-heading-actions')
    .getByRole('button', { name: /运行测试/ }).click();
  await expect(page.getByText('已阻止', { exact: true }).first()).toBeVisible();
  await expect(page.locator('.skill-test-alert')).toContainText('skill_test_execution_blocked');
  expect(state.lastRunBody).not.toBeNull();

  await page.unrouteAll();
  const staleState = await installApi(page, { testStatus: 'passed', testRevision: 2 });
  await page.goto('/#/skills/customer-info-extraction?tab=tests');
  await page.locator('#skill-test-input-message').fill('请提取客户信息');
  await page.locator('.skill-test-heading-actions')
    .getByRole('button', { name: /运行测试/ }).click();
  await expect(page.getByText('结果已过期', { exact: true })).toBeVisible();
  await expect(page.getByText('此结果对应 r2，但当前已保存草稿为 r3', { exact: true })).toBeVisible();
  expect(staleState.testRuns.length).toBeGreaterThan(0);
});

test('readiness blockers disable publish and rollback without permission', async ({ page }) => {
  const failedChecks = readinessChecks().map(check =>
    check.code === 'latest_test_passed' || check.code === 'permission_granted'
      ? { ...check, status: 'fail' as const, reason: '尚未满足' }
      : check,
  );
  await installApi(page, { readinessChecks: failedChecks, readinessReady: false });
  await page.goto('/#/skills/customer-info-extraction?tab=versions');
  await expect(page.getByRole('heading', { name: '发布管理', exact: true })).toBeVisible();
  await expect(page.getByText('2 项检查阻止发布', { exact: true }).first()).toBeVisible();
  const publishButton = page.locator('.skill-release-heading-actions')
    .getByRole('button', { name: /发布/ });
  const rollbackButton = page.locator('.skill-version-row')
    .getByRole('button', { name: /回滚/ });
  await expect(publishButton).toBeDisabled();
  await expect(rollbackButton).toBeDisabled();
  await expect(rollbackButton).toHaveAttribute('title', '无权回滚');
});

test('publish and rollback dialogs create new immutable versions', async ({ page }) => {
  const state = await installApi(page, {
    skills: [skillRecord({ current_semver: null, published_version: null, published_revision: null, published_at: null, status: 'draft' })],
    versions: [],
    readinessChecks: readinessChecks(),
    readinessReady: true,
    publishVersion: version(1, '1.0.0', 'initial'),
  });
  await page.goto('/#/skills/customer-info-extraction?tab=versions');
  await expect(page.getByText('可以发布', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /发布首个版本/ }).click();
  await expect(page.getByRole('dialog')).toContainText('发布 客户信息提取');
  await page.locator('#skill-release-notes').fill('首次发布客户信息提取能力');
  await page.getByRole('button', { name: /确认发布/ }).click();
  await expect(page.getByText('已发布 v1.0.0', { exact: true })).toBeVisible();
  await expect.poll(() => (state.lastPublishBody as { bump?: string } | null)?.bump).toBe('minor');

  await page.unrouteAll();
  const rollbackState = await installApi(page, {
    readinessChecks: readinessChecks(),
    readinessReady: true,
    rollbackVersion: version(3, '1.2.0', 'rollback', { rollback_from: 2 }),
  });
  await page.goto('/#/skills/customer-info-extraction?tab=versions');
  const oldVersion = page.locator('.skill-version-row').filter({ hasText: 'v1.0.0' });
  await oldVersion.getByRole('button', { name: /回滚/ }).click();
  await expect(page.getByRole('dialog')).toContainText('回滚到历史版本');
  await expect(page.getByText('将自动创建为更高版本', { exact: true })).toBeVisible();
  await page.locator('#skill-rollback-notes').fill('恢复稳定版本');
  await page.getByRole('button', { name: /回滚并发布/ }).click();
  await expect(page.getByText('已回滚并创建新版本 v1.2.0', { exact: true })).toBeVisible();
  expect(rollbackState.lastRollbackBody).not.toBeNull();
});

test('detail tabs support keyboard navigation and analytics stays empty', async ({ page }) => {
  await installApi(page);
  await page.goto('/#/skills/customer-info-extraction');
  const tabs = page.getByRole('tab');
  await tabs.filter({ hasText: '概览' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(tabs.filter({ hasText: '能力' })).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('End');
  await expect(tabs.filter({ hasText: '分析' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('分析数据暂不可用', { exact: true })).toBeVisible();
  await expect(page.getByText('等待发布数据', { exact: true })).toBeVisible();
});

test('catalog, detail, and editor avoid document overflow at 1672, 1024, and 390', async ({ page }) => {
  await installApi(page);
  for (const width of [1672, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await openCatalog(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    await page.goto('/#/skills/customer-info-extraction');
    await expect(page.getByRole('heading', { name: '客户信息提取', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    await page.goto('/#/skills/customer-info-extraction/edit');
    await expect(page.getByRole('heading', { name: '客户信息提取', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

test('P2-CM-11 test workbench stacks at 390 and keeps table overflow inside the history panel', async ({ page }) => {
  await installApi(page, {
    testOutput: { long_value: 'x'.repeat(1800) },
  });
  const viewports = [
    { width: 1024, height: 768, columns: 2, placement: 'side-by-side' as const },
    { width: 390, height: 844, columns: 1, placement: 'stacked' as const },
  ];

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto('/#/skills/customer-info-extraction?tab=tests');
    await expect(page.getByRole('heading', { name: '测试工作台', exact: true })).toBeVisible();
    await expect(page.locator('.skill-test-history-table-wrap')).toBeVisible();

    const layout = await page.locator('.skill-test-panes').evaluate(element => {
      const columns = getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/).filter(Boolean);
      const input = element.querySelector<HTMLElement>('.skill-test-input');
      const result = element.querySelector<HTMLElement>('.skill-test-result');
      const inputBox = input?.getBoundingClientRect();
      const resultBox = result?.getBoundingClientRect();
      return {
        columnCount: columns.length,
        inputTop: inputBox?.top ?? 0,
        inputBottom: inputBox?.bottom ?? 0,
        resultTop: resultBox?.top ?? 0,
      };
    });
    expect(layout.columnCount).toBe(viewport.columns);
    if (viewport.placement === 'side-by-side') {
      expect(Math.abs(layout.inputTop - layout.resultTop)).toBeLessThanOrEqual(1);
    } else {
      expect(layout.resultTop).toBeGreaterThan(layout.inputBottom);
    }

    const documentWidths = await page.evaluate(() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    expect(documentWidths.document, `document overflow at ${viewport.width}px`).toBeLessThanOrEqual(documentWidths.viewport);
    expect(documentWidths.body, `body overflow at ${viewport.width}px`).toBeLessThanOrEqual(documentWidths.viewport);

    const panels = await page.evaluate(() => [
      '.skill-test-workbench',
      '.skill-test-input',
      '.skill-test-result',
      '.skill-test-history',
    ].map(selector => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`missing ${selector}`);
      return {
        selector,
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      };
    }));
    for (const panel of panels) {
      expect(panel.scrollWidth, `${panel.selector} leaks horizontal overflow at ${viewport.width}px`)
        .toBeLessThanOrEqual(panel.clientWidth);
    }

    const historyScroll = await page.locator('.skill-test-history-table-wrap').evaluate(element => {
      const history = element as HTMLElement;
      return {
        clientWidth: history.clientWidth,
        scrollWidth: history.scrollWidth,
        overflowX: getComputedStyle(history).overflowX,
      };
    });
    expect(historyScroll.overflowX, `history table should own horizontal scrolling at ${viewport.width}px`).toBe('auto');
    expect(historyScroll.scrollWidth, `history table should overflow internally at ${viewport.width}px`)
      .toBeGreaterThan(historyScroll.clientWidth);

    const scrollPosition = await page.locator('.skill-test-history-table-wrap').evaluate(element => {
      const history = element as HTMLElement;
      history.scrollLeft = history.scrollWidth - history.clientWidth;
      return {
        panelScrollLeft: history.scrollLeft,
        documentScrollX: window.scrollX,
      };
    });
    expect(scrollPosition.panelScrollLeft).toBeGreaterThan(0);
    expect(scrollPosition.documentScrollX).toBe(0);
  }

  await page.locator('#skill-test-input-message').fill('请提取客户信息');
  await page.locator('.skill-test-heading-actions').getByRole('button', { name: /运行测试/ }).click();
  await expect(page.locator('.skill-test-output pre')).toBeVisible();
  await expect(page.locator('.skill-test-result')).toContainText('已通过');

  const longResult = await page.locator('.skill-test-output pre').evaluate(element => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    overflowX: getComputedStyle(element).overflowX,
    overflowWrap: getComputedStyle(element).overflowWrap,
  }));
  expect(longResult.overflowX).toBe('auto');
  expect(longResult.overflowWrap).toBe('anywhere');
  expect(longResult.scrollWidth).toBeLessThanOrEqual(longResult.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);
});

test('P2-CM-12 publish and rollback dialogs trap focus and restore the trigger', async ({ page }) => {
  await installApi(page, {
    readinessChecks: readinessChecks(),
    readinessReady: true,
  });
  await page.goto('/#/skills/customer-info-extraction?tab=versions');
  const publishTrigger = page.locator('.skill-release-heading-actions')
    .getByRole('button', { name: /发布/ });
  await expect(publishTrigger).toBeEnabled();
  await publishTrigger.click();

  const publishDialog = page.getByRole('dialog');
  await expect(publishDialog).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);
  const focusGaps: string[] = [];
  const collectFocusGaps = async (dialogName: string, key: 'Tab' | 'Shift+Tab', steps: number) => {
    for (let step = 1; step <= steps; step += 1) {
      await page.keyboard.press(key);
      await page.waitForTimeout(50);
      const focus = await page.evaluate(() => {
        const active = document.activeElement as HTMLElement | null;
        return {
          insideDialog: Boolean(active?.closest('[role="dialog"]')),
          tag: active?.tagName ?? '',
          id: active?.id ?? '',
          className: active?.className ?? '',
          text: active?.textContent?.trim().slice(0, 80) ?? '',
        };
      });
      if (!focus.insideDialog) {
        focusGaps.push(`${dialogName} ${key} #${step}: ${JSON.stringify(focus)}`);
      }
    }
  };
  await collectFocusGaps('publish', 'Tab', 10);
  await collectFocusGaps('publish', 'Shift+Tab', 8);
  await publishDialog.getByRole('button', { name: /取\s*消/ }).click();
  await expect(publishDialog).toBeHidden();
  await expect(publishTrigger).toBeFocused();

  const rollbackTrigger = page.locator('.skill-version-row').filter({ hasText: 'v1.0.0' })
    .getByRole('button', { name: /回滚/ });
  await expect(rollbackTrigger).toBeEnabled();
  await rollbackTrigger.click();
  const rollbackDialog = page.getByRole('dialog');
  await expect(rollbackDialog).toContainText('回滚到历史版本');
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);
  await collectFocusGaps('rollback', 'Tab', 10);
  await rollbackDialog.getByRole('button', { name: /取\s*消/ }).click();
  await expect(rollbackDialog).toBeHidden();
  await expect(rollbackTrigger).toBeFocused();
  expect(focusGaps.join('\n'), 'dialog focus escaped to the background').toBe('');
});

test('P2-CM-12 editor focuses the first validation error and icon actions have accessible names', async ({ page }) => {
  const state = await installApi(page);
  await page.goto('/#/skills/customer-info-extraction/edit');
  await expect(page.getByRole('heading', { name: '客户信息提取', exact: true })).toBeVisible();

  const name = page.locator('#skill-name');
  await name.fill('');
  const save = page.locator('.skill-editor-actions').getByRole('button', { name: /保存草稿/ });
  await expect(save).toBeEnabled();
  await save.click();

  await expect(name).toBeFocused();
  await expect(name).toHaveAttribute('aria-invalid', 'true');
  await expect(name).toHaveAttribute('aria-describedby', 'skill-name-error');
  await expect(page.locator('#skill-name-error')).toHaveAttribute('role', 'alert');
  await expect(page.locator('#skill-name-error')).toHaveText('请填写 Skill 名称');
  await expect(page.getByText('1 个字段需要处理', { exact: true })).toBeVisible();
  await expect(name).toBeInViewport();
  expect(state.saveCalls).toBe(0);

  await page.getByRole('tab').filter({ hasText: '参数' }).click();
  const firstParameter = page.locator('.skill-parameter-row').first();
  await expect(firstParameter.getByRole('button', { name: '上移', exact: true })).toHaveAccessibleName('上移');
  await expect(firstParameter.getByRole('button', { name: '下移', exact: true })).toHaveAccessibleName('下移');
  await expect(firstParameter.getByRole('button', { name: '移除参数', exact: true })).toHaveAccessibleName('移除参数');
  await expect(page.locator('.skill-breadcrumb').getByRole('button', { name: '返回 Skill 能力库' }))
    .toHaveAccessibleName('返回 Skill 能力库');
});

test('P2-CM-12 test results expose a discoverable live region for passed, failed, and blocked', async ({ page }) => {
  const state = await installApi(page);
  await page.goto('/#/skills/customer-info-extraction?tab=tests');
  await expect(page.getByRole('heading', { name: '测试工作台', exact: true })).toBeVisible();
  await expect(page.locator('.skill-test-history-table-wrap')).toBeVisible();

  const liveResult = page.locator('.skill-test-result[aria-live="polite"]');
  await expect(liveResult).toHaveAttribute('aria-live', 'polite');
  await expect(liveResult).toHaveAttribute('aria-labelledby', 'skill-test-result-title');

  const failedRow = page.locator('.skill-test-history-table tbody tr').filter({ hasText: '未通过' });
  await failedRow.getByRole('button', { name: '查看', exact: true }).click();
  await expect(liveResult).toContainText('未通过');

  const blockedRow = page.locator('.skill-test-history-table tbody tr').filter({ hasText: '已阻止' });
  await blockedRow.getByRole('button', { name: '查看', exact: true }).click();
  await expect(liveResult).toContainText('已阻止');

  await page.locator('#skill-test-input-message').fill('请提取客户信息');
  await page.locator('.skill-test-heading-actions').getByRole('button', { name: /运行测试/ }).click();
  await expect(liveResult.locator('.skill-test-status-passed')).toHaveText('已通过');
  expect(state.lastRunBody).not.toBeNull();
});

test('P2-CM-07 en, hi, and zh-TW render the key test and release labels', async ({ page }) => {
  await installApi(page);
  await page.goto('/#/skills');
  const locales = [
    {
      language: 'en',
      testHeading: 'Test workbench',
      runTest: 'Run test',
      releaseHeading: 'Release management',
      publish: 'Publish',
      versionsTab: 'Versions',
    },
    {
      language: 'hi',
      testHeading: 'परीक्षण वर्कबेंच',
      runTest: 'परीक्षण चलाएँ',
      releaseHeading: 'रिलीज़ प्रबंधन',
      publish: 'प्रकाशित करें',
      versionsTab: 'संस्करण',
    },
    {
      language: 'zh-TW',
      testHeading: '測試工作台',
      runTest: '執行測試',
      releaseHeading: '發佈管理',
      publish: '發佈',
      versionsTab: '版本',
    },
  ] as const;

  for (const labels of locales) {
    await page.evaluate(({ language, hash }) => {
      localStorage.setItem('agent-platform-language', language);
      window.location.hash = hash;
    }, {
      language: labels.language,
      hash: '#/skills/customer-info-extraction?tab=tests',
    });
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', labels.language);
    await expect(page.getByRole('heading', { name: labels.testHeading, exact: true })).toBeVisible();
    await expect(page.locator('.skill-test-heading-actions button').filter({ hasText: labels.runTest }))
      .toBeVisible();

    await page.getByRole('tab', { name: labels.versionsTab, exact: true }).click();
    await expect(page.getByRole('heading', { name: labels.releaseHeading, exact: true })).toBeVisible();
    await expect(page.locator('.skill-release-heading-actions button').filter({ hasText: labels.publish }))
      .toBeVisible();
  }
});

function packageFixture(overrides: Partial<SkillPackageInfo> = {}): SkillPackageInfo {
  return {
    id: 'package-1',
    digest: 'sha256:' + 'a'.repeat(64),
    filename: 'customer-skill.zip',
    size_bytes: 20480,
    file_count: 3,
    has_scripts: true,
    entrypoint: 'scripts/main.py',
    created_by: '张晓雯',
    created_at: '2026-11-27T06:00:00Z',
    files: [
      { path: 'SKILL.md', size: 1200, sha256: 'b'.repeat(64), executable: false },
      { path: 'scripts/main.py', size: 2048, sha256: 'c'.repeat(64), executable: true },
      { path: 'references/faq.md', size: 330, sha256: 'd'.repeat(64), executable: false },
    ],
    ...overrides,
  };
}

/** The package endpoint nests the file list under `manifest`, like the server does. */
function packageResponse(info: SkillPackageInfo) {
  const { files, ...rest } = info;
  return { package: { ...rest, manifest: { schema: 'skill-package/v1', files } } };
}

async function uploadPackage(page: Page, name = 'customer-skill.zip') {
  await page.locator('.skill-package-file').setInputFiles({
    name,
    mimeType: 'application/zip',
    buffer: Buffer.from('PK\x03\x04'),
  });
}

test('P3-UI-01 editor uploads a package and shows the re-tiered result', async ({ page }) => {
  const state = await installApi(page);
  await page.goto('/#/skills/customer-info-extraction/edit?section=runtime');
  await expect(page.getByRole('heading', { name: '运行安全' })).toBeVisible();
  await expect(page.getByText('拖入 .zip 或点击选择')).toBeVisible();

  await uploadPackage(page);

  // The name the operator dropped in is what the card echoes back, not the digest.
  await expect(page.locator('.skill-package-copy strong')).toHaveText('customer-skill.zip');
  expect(state.uploadCalls).toBe(1);
  expect(state.lastUploadName).toBe('customer-skill.zip');
  await expect(page.getByText('3 个文件 · 入口 scripts/main.py')).toBeVisible();
  await expect(page.locator('.skill-package-heading')).toContainText('含脚本');
  await expect(page.locator('.skill-package-tags')).toContainText('L3');

  await page.getByRole('button', { name: '文件清单' }).click();
  await expect(page.locator('.skill-package-files li')).toHaveCount(3);
  await expect(page.locator('.skill-package-files')).toContainText('scripts/main.py');
  await expect(page.locator('.skill-package-files li').filter({ hasText: 'scripts/main.py' }))
    .toContainText('脚本');
});

test('P3-UI-02 rejected package reports the actionable code, not the raw body', async ({ page }) => {
  const state = await installApi(page, { packageRejectCode: 'skill_package_missing_manifest' });
  await page.goto('/#/skills/customer-info-extraction/edit?section=runtime');

  await uploadPackage(page, 'broken.zip');

  await expect(page.getByText('技能包未通过校验')).toBeVisible();
  await expect(page.getByText('包内未找到 SKILL.md，请确认它在根目录或唯一的顶层目录下')).toBeVisible();
  // Nothing was bound, so the drop zone stays and no summary appears.
  await expect(page.locator('.skill-package-summary')).toHaveCount(0);
  await expect(page.getByText('拖入 .zip 或点击选择')).toBeVisible();
  expect(state.uploadCalls).toBe(1);
});

test('P3-UI-03 resources tab shows the package read-only without management actions', async ({ page }) => {
  await installApi(page, { packageAttached: packageFixture() });
  await page.goto('/#/skills/customer-info-extraction?tab=resources');

  await expect(page.locator('.skill-package-copy strong')).toHaveText('customer-skill.zip');
  await expect(page.getByRole('button', { name: '替换' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '移除' })).toHaveCount(0);
  await expect(page.locator('.skill-package-file')).toHaveCount(0);

  await page.getByRole('button', { name: '文件清单' }).click();
  await expect(page.locator('.skill-package-files li')).toHaveCount(3);
});

// Regression guard for the login page's own weight. `login.css` used to open
// with a cross-origin `@import` for Inter + Noto Sans SC; when that host is
// slow or blocked the stylesheet never settles, the `load` event stalls, and the
// page renders blank for tens of seconds. No route mocking here on purpose — the
// page must stand on its own and finish loading with local requests only.
test('P3-UI-04 the login surface loads without any cross-origin request', async ({ page }) => {
  const external: string[] = [];
  page.on('request', request => {
    const host = new URL(request.url()).hostname;
    if (host !== '127.0.0.1' && host !== 'localhost') external.push(request.url());
  });

  await page.goto('/#/login');
  await expect(page.locator('.login-page')).toBeVisible();

  expect(external).toEqual([]);
});

test('P3-UI-05 importing a zip creates the Skill and opens its runtime section', async ({ page }) => {
  const state = await installApi(page);
  await page.goto('/#/skills/create');

  // The import entry is a creation path, so it lives next to the other modes.
  await page.getByRole('heading', { name: '导入压缩包' }).click();
  const action = page.getByRole('button', { name: '导入并创建', exact: true });
  await expect(action).toBeDisabled();

  await page.locator('.skill-package-file').setInputFiles({
    name: 'order-skill.zip',
    mimeType: 'application/zip',
    buffer: Buffer.from('PK\x03\x04'),
  });
  await expect(page.locator('.skill-package-drop.is-chosen')).toContainText('order-skill.zip');
  await expect(action).toBeEnabled();

  await action.click();

  await expect(page).toHaveURL(/#\/skills\/order-status\/edit\?section=runtime/);
  expect(state.importCalls).toBe(1);
  expect(state.lastImportName).toBe('order-skill.zip');

  // The archive the server bound is the one the editor now shows.
  await expect(page.locator('.skill-package-copy strong')).toHaveText('customer-skill.zip');
  await expect(page.locator('.skill-package-tags')).toContainText('L3');
});

test('P3-UI-06 a rejected import explains the zip and stays on the create page', async ({ page }) => {
  const state = await installApi(page, { importRejectCode: 'skill_package_missing_manifest' });
  await page.goto('/#/skills/create');

  await page.getByRole('heading', { name: '导入压缩包' }).click();
  await page.locator('.skill-package-file').setInputFiles({
    name: 'broken.zip',
    mimeType: 'application/zip',
    buffer: Buffer.from('PK\x03\x04'),
  });
  await page.getByRole('button', { name: '导入并创建', exact: true }).click();

  await expect(page.getByText('包内未找到 SKILL.md，请确认它在根目录或唯一的顶层目录下'))
    .toBeVisible();
  // Nothing was created, so there is nowhere to navigate to.
  await expect(page).toHaveURL(/#\/skills\/create$/);
  expect(state.importCalls).toBe(1);
});
