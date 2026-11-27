export const SKILL_CATEGORIES = ['service', 'finance', 'sales', 'general'] as const;
export type SkillCategory = typeof SKILL_CATEGORIES[number];

export const SKILL_TYPES = ['instruction', 'knowledge', 'query', 'action', 'handoff'] as const;
export type SkillType = typeof SKILL_TYPES[number];

export const SKILL_TRIGGERS = ['agent_auto', 'manual'] as const;
export type SkillTrigger = typeof SKILL_TRIGGERS[number];

export const SKILL_OUTPUT_FORMATS = ['text', 'json'] as const;
export type SkillOutputFormat = typeof SKILL_OUTPUT_FORMATS[number];

export const SKILL_PARAMETER_TYPES = ['string', 'number', 'integer', 'boolean', 'object', 'array'] as const;
export type SkillParameterType = typeof SKILL_PARAMETER_TYPES[number];

export const SKILL_RETRY_POLICIES = ['none', 'one', 'two'] as const;
export type SkillRetryPolicy = typeof SKILL_RETRY_POLICIES[number];

export const SKILL_IDEMPOTENCY = ['none', 'optional', 'required'] as const;
export type SkillIdempotency = typeof SKILL_IDEMPOTENCY[number];

export const SKILL_ERROR_BEHAVIORS = ['fail', 'fallback', 'handoff'] as const;
export type SkillErrorBehavior = typeof SKILL_ERROR_BEHAVIORS[number];

// `package` is provenance, not a form the user fills in: it is written by
// importing an archive, so the create page never posts it as a mode.
export const SKILL_CREATION_MODES = ['ai', 'template', 'professional', 'package'] as const;
export type SkillCreationMode = typeof SKILL_CREATION_MODES[number];

// Modes `POST /skills` accepts. Mirrors the server-side narrowing: a packaged
// Skill is created by `/skills/import`, never through the generic create body.
export const SKILL_CREATE_MODES = ['ai', 'template', 'professional'] as const;
export type SkillCreateMode = typeof SKILL_CREATE_MODES[number];

export const SKILL_STATUSES = ['draft', 'published', 'archived'] as const;
export type SkillStatus = typeof SKILL_STATUSES[number];

export const SKILL_WEIGHT_CLASSES = ['declarative', 'packaged', 'executable'] as const;
export type SkillWeightClass = typeof SKILL_WEIGHT_CLASSES[number];

export const SKILL_RISK_LEVELS = ['r0', 'r1', 'r2', 'r3'] as const;
export type SkillRiskLevel = typeof SKILL_RISK_LEVELS[number];

export interface SkillRiskReason {
  code: string;
  level: SkillRiskLevel;
}

export const TEST_RUN_STATUSES = ['passed', 'failed', 'error', 'blocked'] as const;
export type TestRunStatus = typeof TEST_RUN_STATUSES[number];
export type TestExecutionKind = 'live' | 'contract';
export type ReadinessStatus = 'pass' | 'fail' | 'warning';
export type ReadinessDestination = 'editor' | 'tests' | 'versions' | 'permission' | string;
export type VersionBump = 'major' | 'minor' | 'patch';
export type ReleaseKind = 'initial' | 'major' | 'minor' | 'patch' | 'rollback';

export type JsonObject = Record<string, unknown>;

export interface SkillParameter {
  name: string;
  type: SkillParameterType;
  required: boolean;
  default: unknown;
  description: string;
}

export interface SkillDependencies {
  model_profile_id: string | null;
  model_profile_version: number | null;
  knowledge_base_ids: string[];
  tool_names: string[];
  handoff_queue: string | null;
}

export interface SkillRuntime {
  timeout_seconds: number;
  retry_policy: SkillRetryPolicy;
  confirmation_required: boolean;
  idempotency: SkillIdempotency;
  error_behavior: SkillErrorBehavior;
  max_amount: number | null;
}

export interface SkillOutput {
  format: SkillOutputFormat;
  schema: JsonObject | null;
}

export interface SkillDefinition {
  schema_version: 'v1';
  creation_mode: SkillCreationMode;
  type: SkillType;
  trigger: SkillTrigger;
  instructions: string;
  parameters: SkillParameter[];
  output: SkillOutput;
  dependencies: SkillDependencies;
  runtime: SkillRuntime;
  permission_scope: 'workspace';
}

export interface SkillPackageBrief {
  digest: string;
  filename: string | null;
  size_bytes: number | null;
  file_count: number | null;
  has_scripts: boolean;
  entrypoint: string | null;
  created_at: string | null;
}

export interface SkillPackageFile {
  path: string;
  size: number;
  sha256: string;
  executable: boolean;
}

export interface SkillPackageInfo extends SkillPackageBrief {
  id: string;
  created_by: string;
  files: SkillPackageFile[];
}

export interface SkillSummary {
  id: string;
  key: string;
  name: string;
  description: string;
  category: SkillCategory;
  tags: string[];
  visibility: 'workspace';
  status: SkillStatus;
  weight_class: SkillWeightClass;
  risk_level: SkillRiskLevel;
  risk_computed: SkillRiskLevel;
  risk_reasons: SkillRiskReason[];
  data_scope: string[];
  draft_revision: number;
  published_version: number | null;
  published_revision: number | null;
  current_semver: string | null;
  has_unpublished_changes: boolean;
  package: SkillPackageBrief | null;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  /** Behavioural facts. Null means "not measured", never "zero". */
  usage_count: number | null;
  success_rate: number | null;
  rating_avg: number | null;
  rating_count: number | null;
}

export interface SkillStat {
  value: number | null;
  /** Percent change for counts, absolute delta for the rating. Null = no base. */
  change: number | null;
}

export interface SkillOverviewStats {
  total: SkillStat;
  published: SkillStat;
  in_use: SkillStat;
  rating: SkillStat;
}

export interface SkillPopularItem {
  key: string;
  name: string;
  category: SkillCategory;
  status: SkillStatus;
  runs: number;
  success_rate: number | null;
}

export interface SkillOverview {
  stats: SkillOverviewStats;
  popular: SkillPopularItem[];
}

export interface SkillRecord extends SkillSummary {
  definition: SkillDefinition;
}

export interface SkillCatalogFacet {
  value: string;
  count: number;
}

export interface SkillCatalogPage {
  items: SkillSummary[];
  total: number;
  page: number;
  page_size: number;
  status_facets: SkillCatalogFacet[];
  category_facets: SkillCatalogFacet[];
  risk_facets: SkillCatalogFacet[];
  weight_facets: SkillCatalogFacet[];
}

export interface SkillTemplate {
  key: string;
  name: string;
  description: string;
  category: SkillCategory;
  type: SkillType;
  tags: string[];
  definition: SkillDefinition | null;
}

export interface SkillTemplateCatalog {
  items: SkillTemplate[];
  ai_generation_enabled: boolean | null;
  ai_generation_reason: string | null;
}

export interface CreateSkillRequest {
  mode: SkillCreateMode;
  prompt: string | null;
  template_key: string | null;
  definition: SkillDefinition | null;
}

export interface SaveDraftRequest {
  revision: number;
  name: string;
  description: string;
  category: SkillCategory;
  tags: string[];
  visibility: 'workspace';
  risk_level?: SkillRiskLevel;
  definition: SkillDefinition;
}

export interface SkillTestInput {
  draft_revision: number;
  input: JsonObject;
  scenario: string;
  client_request_id: string;
}

export interface SkillTestRun {
  id: string;
  skill_id: string;
  draft_revision: number;
  status: TestRunStatus;
  execution_kind: TestExecutionKind;
  input: JsonObject;
  input_summary: string;
  output: unknown;
  diagnostics: JsonObject;
  reason_code: string | null;
  duration_ms: number;
  executed_by: string;
  created_at: string;
}

export interface SkillTestRunPage {
  items: SkillTestRun[];
  total: number;
  page: number;
  page_size: number;
}

export interface ReadinessCheck {
  code: string;
  status: ReadinessStatus;
  reason: string;
  destination: ReadinessDestination | null;
}

export interface SkillReadiness {
  skill_id: string;
  draft_revision: number;
  ready: boolean;
  checks: ReadinessCheck[];
  next_semver: string | null;
}

export interface SkillVersion {
  id: string;
  skill_id: string;
  version: number;
  semver: string;
  release_kind: ReleaseKind;
  definition: SkillDefinition | null;
  definition_digest: string;
  release_notes: string;
  source_draft_revision: number;
  test_run_id: string | null;
  rollback_from: number | null;
  created_by: string;
  created_at: string;
}

export interface SkillVersionPage {
  items: SkillVersion[];
  total: number;
  page: number;
  page_size: number;
}

export interface PublishSkillRequest {
  revision: number;
  bump: VersionBump;
  release_notes: string;
}

export interface RollbackSkillRequest {
  revision: number;
  target_version: number;
  release_notes: string;
}

export interface SkillPermissions {
  read: boolean;
  manage: boolean;
  test: boolean;
  publish: boolean;
  role: string;
}

export interface ModelProfileOption {
  id: string;
  name: string;
  version: number;
  enabled: boolean;
}

export interface KnowledgeBaseOption {
  id: string;
  name: string;
  enabled: boolean;
}

export interface ToolOption {
  id: string;
  name: string;
  enabled: boolean;
  effect: 'read' | 'write' | 'unknown';
}

export interface SkillDependencyOptions {
  models: ModelProfileOption[];
  knowledgeBases: KnowledgeBaseOption[];
  tools: ToolOption[];
  errors: {
    models: string;
    knowledgeBases: string;
    tools: string;
  };
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function recordOf(value: unknown): JsonObject {
  return isObject(value) ? value : {};
}

function arrayOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringOf(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function numberOf(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function booleanOf(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? value as T
    : fallback;
}

function uniqueStrings(value: unknown): string[] {
  return [...new Set(arrayOf(value).filter((item): item is string => typeof item === 'string').map(item => item.trim()).filter(Boolean))];
}

function jsonObject(value: unknown): JsonObject | null {
  return isObject(value) ? value : null;
}

function normalizeParameter(value: unknown): SkillParameter | null {
  const raw = recordOf(value);
  const name = stringOf(raw.name).trim();
  if (!name) return null;
  return {
    name,
    type: oneOf(raw.type, SKILL_PARAMETER_TYPES, 'string'),
    required: booleanOf(raw.required, false),
    default: raw.default ?? null,
    description: stringOf(raw.description),
  };
}

export function emptySkillDefinition(mode: SkillCreationMode = 'professional'): SkillDefinition {
  return {
    schema_version: 'v1',
    creation_mode: mode,
    type: 'instruction',
    trigger: 'agent_auto',
    instructions: '',
    parameters: [],
    output: { format: 'text', schema: null },
    dependencies: {
      model_profile_id: null,
      model_profile_version: null,
      knowledge_base_ids: [],
      tool_names: [],
      handoff_queue: null,
    },
    runtime: {
      timeout_seconds: 30,
      retry_policy: 'none',
      confirmation_required: false,
      idempotency: 'none',
      error_behavior: 'fail',
      max_amount: null,
    },
    permission_scope: 'workspace',
  };
}

export function normalizeDefinition(value: unknown): SkillDefinition {
  const raw = recordOf(value);
  const dependencies = recordOf(raw.dependencies);
  const runtime = recordOf(raw.runtime);
  const output = recordOf(raw.output);
  const fallback = emptySkillDefinition(oneOf(raw.creation_mode, SKILL_CREATION_MODES, 'professional'));
  return {
    schema_version: 'v1',
    creation_mode: oneOf(raw.creation_mode, SKILL_CREATION_MODES, fallback.creation_mode),
    type: oneOf(raw.type, SKILL_TYPES, fallback.type),
    trigger: oneOf(raw.trigger, SKILL_TRIGGERS, fallback.trigger),
    instructions: stringOf(raw.instructions ?? raw.prompt),
    parameters: arrayOf(raw.parameters).map(normalizeParameter).filter((item): item is SkillParameter => item !== null),
    output: {
      format: oneOf(output.format, SKILL_OUTPUT_FORMATS, 'text'),
      schema: jsonObject(output.schema ?? output.json_schema),
    },
    dependencies: {
      model_profile_id: stringOf(dependencies.model_profile_id) || null,
      model_profile_version: nullableNumber(dependencies.model_profile_version),
      knowledge_base_ids: uniqueStrings(dependencies.knowledge_base_ids),
      tool_names: uniqueStrings(dependencies.tool_names),
      handoff_queue: stringOf(dependencies.handoff_queue) || null,
    },
    runtime: {
      timeout_seconds: numberOf(runtime.timeout_seconds, 30),
      retry_policy: oneOf(runtime.retry_policy, SKILL_RETRY_POLICIES, 'none'),
      confirmation_required: booleanOf(runtime.confirmation_required, false),
      idempotency: oneOf(runtime.idempotency, SKILL_IDEMPOTENCY, 'none'),
      error_behavior: oneOf(runtime.error_behavior, SKILL_ERROR_BEHAVIORS, 'fail'),
      max_amount: nullableNumber(runtime.max_amount),
    },
    permission_scope: 'workspace',
  };
}

export function normalizeSkillSummary(value: unknown, fallbackKey = ''): SkillSummary {
  const raw = recordOf(value);
  const publishedVersion = nullableNumber(raw.published_version ?? raw.current_version);
  const publishedRevision = nullableNumber(raw.published_revision);
  const draftRevision = numberOf(raw.draft_revision ?? raw.revision, 1);
  const riskLevel = oneOf(raw.risk_level, SKILL_RISK_LEVELS, 'r0');
  return {
    id: stringOf(raw.id ?? raw.skill_id),
    key: stringOf(raw.key ?? raw.skill_key, fallbackKey),
    name: stringOf(raw.name),
    description: stringOf(raw.description),
    category: oneOf(raw.category, SKILL_CATEGORIES, 'general'),
    tags: uniqueStrings(raw.tags),
    visibility: 'workspace',
    status: oneOf(raw.status, SKILL_STATUSES, publishedVersion ? 'published' : 'draft'),
    weight_class: oneOf(raw.weight_class, SKILL_WEIGHT_CLASSES, 'declarative'),
    risk_level: riskLevel,
    risk_computed: oneOf(raw.risk_computed, SKILL_RISK_LEVELS, riskLevel),
    risk_reasons: normalizeRiskReasons(raw.risk_reasons),
    data_scope: uniqueStrings(raw.data_scope),
    draft_revision: draftRevision,
    published_version: publishedVersion,
    published_revision: publishedRevision,
    current_semver: stringOf(raw.current_semver ?? raw.semver ?? raw.published_semver) || null,
    has_unpublished_changes: booleanOf(
      raw.has_unpublished_changes,
      publishedRevision !== null && draftRevision !== publishedRevision,
    ),
    package: normalizePackageBrief(raw.package),
    created_by: stringOf(raw.created_by),
    updated_by: stringOf(raw.updated_by ?? raw.created_by),
    created_at: stringOf(raw.created_at),
    updated_at: stringOf(raw.updated_at ?? raw.created_at),
    published_at: stringOf(raw.published_at) || null,
    usage_count: nullableNumber(raw.usage_count),
    success_rate: nullableNumber(raw.success_rate),
    rating_avg: nullableNumber(raw.rating_avg),
    rating_count: nullableNumber(raw.rating_count),
  };
}

export function normalizeSkillOverview(value: unknown): SkillOverview {
  const raw = recordOf(value);
  const stats = recordOf(raw.stats);
  const stat = (key: string): SkillStat => {
    const entry = recordOf(stats[key]);
    return { value: nullableNumber(entry.value), change: nullableNumber(entry.change) };
  };
  return {
    stats: {
      total: stat('total'),
      published: stat('published'),
      in_use: stat('in_use'),
      rating: stat('rating'),
    },
    popular: Array.isArray(raw.popular)
      ? raw.popular.filter(isObject).map(entry => {
          const item = recordOf(entry);
          return {
            key: stringOf(item.key),
            name: stringOf(item.name ?? item.key),
            category: oneOf(item.category, SKILL_CATEGORIES, 'general'),
            status: oneOf(item.status, SKILL_STATUSES, 'draft'),
            runs: numberOf(item.runs, 0),
            success_rate: nullableNumber(item.success_rate),
          };
        })
      : [],
  };
}

export function normalizeSkill(value: unknown, fallbackKey = ''): SkillRecord {
  const raw = recordOf(value);
  return {
    ...normalizeSkillSummary(raw, fallbackKey),
    definition: normalizeDefinition(raw.definition ?? raw.draft_definition),
  };
}

export function normalizePackageBrief(value: unknown): SkillPackageBrief | null {
  if (!isObject(value)) return null;
  const raw = recordOf(value);
  const digest = stringOf(raw.digest);
  if (!digest) return null;
  return {
    digest,
    filename: stringOf(raw.filename) || null,
    size_bytes: nullableNumber(raw.size_bytes),
    file_count: nullableNumber(raw.file_count),
    has_scripts: booleanOf(raw.has_scripts, false),
    entrypoint: stringOf(raw.entrypoint) || null,
    created_at: stringOf(raw.created_at) || null,
  };
}

export function normalizeSkillPackage(value: unknown): SkillPackageInfo | null {
  const brief = normalizePackageBrief(value);
  if (!brief) return null;
  const raw = recordOf(value);
  const manifest = recordOf(raw.manifest);
  return {
    ...brief,
    id: stringOf(raw.id),
    created_by: stringOf(raw.created_by),
    files: arrayOf(manifest.files).flatMap(item => {
      const file = recordOf(item);
      const path = stringOf(file.path);
      if (!path) return [];
      return [{
        path,
        size: numberOf(file.size, 0),
        sha256: stringOf(file.sha256),
        executable: booleanOf(file.executable, false),
      }];
    }),
  };
}

function normalizeRiskReasons(value: unknown): SkillRiskReason[] {
  return arrayOf(value).flatMap(item => {
    const raw = recordOf(item);
    const code = stringOf(raw.code);
    return code ? [{ code, level: oneOf(raw.level, SKILL_RISK_LEVELS, 'r1') }] : [];
  });
}

function normalizeFacets(value: unknown): SkillCatalogFacet[] {
  if (isObject(value)) {
    return Object.entries(value).flatMap(([facet, count]) =>
      typeof count === 'number' ? [{ value: facet, count }] : []);
  }
  return arrayOf(value).flatMap(item => {
    const raw = recordOf(item);
    const facetValue = stringOf(raw.value ?? raw.key ?? raw.id);
    return facetValue ? [{ value: facetValue, count: numberOf(raw.count, 0) }] : [];
  });
}

export function normalizeCatalogPage(value: unknown): SkillCatalogPage {
  const raw = recordOf(value);
  const sourceItems = Array.isArray(value) ? value : arrayOf(raw.items ?? raw.skills);
  return {
    items: sourceItems.map(item => normalizeSkillSummary(item)),
    total: numberOf(raw.total, sourceItems.length),
    page: numberOf(raw.page, 1),
    page_size: numberOf(raw.page_size ?? raw.pageSize, sourceItems.length || 1),
    status_facets: normalizeFacets(raw.status_facets ?? raw.status_facets_by_value),
    category_facets: normalizeFacets(raw.category_facets ?? raw.category_facets_by_value),
    risk_facets: normalizeFacets(raw.risk_facets ?? raw.risk_facets_by_value),
    weight_facets: normalizeFacets(raw.weight_facets ?? raw.weight_facets_by_value),
  };
}

function normalizeTemplate(value: unknown): SkillTemplate | null {
  const raw = recordOf(value);
  const key = stringOf(raw.key ?? raw.template_key ?? raw.id);
  if (!key) return null;
  return {
    key,
    name: stringOf(raw.name, key),
    description: stringOf(raw.description),
    category: oneOf(raw.category, SKILL_CATEGORIES, 'general'),
    type: oneOf(raw.type, SKILL_TYPES, 'instruction'),
    tags: uniqueStrings(raw.tags),
    definition: isObject(raw.definition) ? normalizeDefinition(raw.definition) : null,
  };
}

export function normalizeTemplateCatalog(value: unknown): SkillTemplateCatalog {
  const raw = recordOf(value);
  const sourceItems = Array.isArray(value) ? value : arrayOf(raw.items ?? raw.templates);
  const enabledValue = raw.ai_generation_enabled ?? raw.ai_enabled;
  return {
    items: sourceItems.map(normalizeTemplate).filter((item): item is SkillTemplate => item !== null),
    ai_generation_enabled: typeof enabledValue === 'boolean' ? enabledValue : null,
    ai_generation_reason: stringOf(raw.ai_generation_reason) || null,
  };
}

function normalizeTestStatus(value: unknown): TestRunStatus {
  if (value === 'pass' || value === 'succeeded' || value === 'success') return 'passed';
  if (value === 'fail' || value === 'failure') return 'failed';
  return oneOf(value, TEST_RUN_STATUSES, 'error');
}

export function normalizeTestRun(value: unknown): SkillTestRun {
  const raw = recordOf(value);
  return {
    id: stringOf(raw.id ?? raw.run_id),
    skill_id: stringOf(raw.skill_id),
    draft_revision: numberOf(raw.draft_revision, 1),
    status: normalizeTestStatus(raw.status),
    execution_kind: oneOf(raw.execution_kind, ['live', 'contract'] as const, 'contract'),
    input: recordOf(raw.input),
    input_summary: stringOf(raw.input_summary),
    output: raw.output ?? null,
    diagnostics: recordOf(raw.diagnostics),
    reason_code: stringOf(raw.reason_code) || null,
    duration_ms: numberOf(raw.duration_ms, 0),
    executed_by: stringOf(raw.executed_by),
    created_at: stringOf(raw.created_at),
  };
}

export function normalizeTestRunPage(value: unknown): SkillTestRunPage {
  const raw = recordOf(value);
  const sourceItems = Array.isArray(value) ? value : arrayOf(raw.items ?? raw.runs);
  return {
    items: sourceItems.map(normalizeTestRun),
    total: numberOf(raw.total, sourceItems.length),
    page: numberOf(raw.page, 1),
    page_size: numberOf(raw.page_size, sourceItems.length || 1),
  };
}

function normalizeReadinessStatus(value: unknown): ReadinessStatus {
  if (value === 'passed' || value === 'ok') return 'pass';
  if (value === 'failed' || value === 'blocked') return 'fail';
  return oneOf(value, ['pass', 'fail', 'warning'] as const, 'fail');
}

function normalizeReadinessCheck(value: unknown): ReadinessCheck {
  const raw = recordOf(value);
  return {
    code: stringOf(raw.code ?? raw.check_code, 'unknown'),
    status: normalizeReadinessStatus(raw.status),
    reason: stringOf(raw.reason ?? raw.detail),
    destination: stringOf(raw.destination ?? raw.action) || null,
  };
}

export function normalizeReadiness(value: unknown, draftRevision: number): SkillReadiness {
  const raw = recordOf(value);
  const checks = arrayOf(raw.checks ?? raw.items).map(normalizeReadinessCheck);
  return {
    skill_id: stringOf(raw.skill_id),
    draft_revision: numberOf(raw.draft_revision, draftRevision),
    ready: booleanOf(raw.ready, checks.length > 0 && checks.every(check => check.status === 'pass')),
    checks,
    next_semver: stringOf(raw.next_semver ?? raw.suggested_semver) || null,
  };
}

function normalizeReleaseKind(value: unknown): ReleaseKind {
  return oneOf(value, ['initial', 'major', 'minor', 'patch', 'rollback'] as const, 'patch');
}

export function normalizeVersion(value: unknown): SkillVersion {
  const raw = recordOf(value);
  return {
    id: stringOf(raw.id ?? raw.version_id),
    skill_id: stringOf(raw.skill_id),
    version: numberOf(raw.version, 1),
    semver: stringOf(raw.semver ?? raw.version_name, '0.0.0'),
    release_kind: normalizeReleaseKind(raw.release_kind ?? raw.kind),
    definition: isObject(raw.definition) ? normalizeDefinition(raw.definition) : null,
    definition_digest: stringOf(raw.definition_digest ?? raw.digest),
    release_notes: stringOf(raw.release_notes ?? raw.notes),
    source_draft_revision: numberOf(raw.source_draft_revision ?? raw.draft_revision, 1),
    test_run_id: stringOf(raw.test_run_id) || null,
    rollback_from: nullableNumber(raw.rollback_from),
    created_by: stringOf(raw.created_by),
    created_at: stringOf(raw.created_at),
  };
}

export function normalizeVersionPage(value: unknown): SkillVersionPage {
  const raw = recordOf(value);
  const sourceItems = Array.isArray(value) ? value : arrayOf(raw.items ?? raw.versions);
  return {
    items: sourceItems.map(normalizeVersion),
    total: numberOf(raw.total, sourceItems.length),
    page: numberOf(raw.page, 1),
    page_size: numberOf(raw.page_size, sourceItems.length || 1),
  };
}

export function normalizeModelProfiles(value: unknown): ModelProfileOption[] {
  const sourceItems = Array.isArray(value) ? value : recordOf(value).items;
  return arrayOf(sourceItems).flatMap(item => {
    const raw = recordOf(item);
    const id = stringOf(raw.id ?? raw.profile_id);
    if (!id) return [];
    return [{
      id,
      name: stringOf(raw.name, id),
      version: numberOf(raw.published_version ?? raw.version, 1),
      enabled: booleanOf(raw.enabled, true),
    }];
  });
}

export function normalizeKnowledgeBases(value: unknown): KnowledgeBaseOption[] {
  const sourceItems = Array.isArray(value) ? value : recordOf(value).items;
  return arrayOf(sourceItems).flatMap(item => {
    const raw = recordOf(item);
    const id = stringOf(raw.id ?? raw.kb_id);
    if (!id) return [];
    return [{ id, name: stringOf(raw.name, id), enabled: booleanOf(raw.enabled, true) }];
  });
}

export function normalizeTools(value: unknown): ToolOption[] {
  const sourceItems = Array.isArray(value) ? value : recordOf(value).items;
  return arrayOf(sourceItems).flatMap(item => {
    const raw = recordOf(item);
    const id = stringOf(raw.name ?? raw.id);
    if (!id) return [];
    const spec = recordOf(raw.spec);
    const effect = oneOf(spec.effect ?? raw.effect, ['read', 'write', 'unknown'] as const, 'unknown');
    return [{
      id,
      name: stringOf(raw.display_name ?? raw.name, id),
      enabled: booleanOf(raw.enabled, true),
      effect,
    }];
  });
}

export function nextSemver(current: string | null, bump: VersionBump): string {
  if (!current) return '1.0.0';
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(current);
  if (!match) return '1.0.0';
  const major = Number(match[1]);
  const minor = Number(match[2]);
  const patch = Number(match[3]);
  if (bump === 'major') return `${major + 1}.0.0`;
  if (bump === 'minor') return `${major}.${minor + 1}.0`;
  return `${major}.${minor}.${patch + 1}`;
}

export function buildInputSummary(input: JsonObject): string {
  try {
    const compact = JSON.stringify(input);
    return compact.length > 160 ? `${compact.slice(0, 157)}...` : compact;
  } catch {
    return '';
  }
}
