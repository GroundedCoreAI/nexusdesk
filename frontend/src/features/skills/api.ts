import { api, post, put, upload } from '../../shared/api/client';
import {
  normalizeCatalogPage,
  normalizeKnowledgeBases,
  normalizeModelProfiles,
  normalizeReadiness,
  normalizeSkill,
  normalizeSkillPackage,
  normalizeTemplateCatalog,
  normalizeSkillOverview,
  normalizeTestRun,
  normalizeTestRunPage,
  normalizeTools,
  normalizeVersion,
  normalizeVersionPage,
  type CreateSkillRequest,
  type JsonObject,
  type PublishSkillRequest,
  type RollbackSkillRequest,
  type SaveDraftRequest,
  type SkillCatalogPage,
  type SkillDefinition,
  type SkillOverview,
  type SkillPackageInfo,
  type SkillReadiness,
  type SkillRecord,
  type SkillTemplateCatalog,
  type SkillTestInput,
  type SkillTestRun,
  type SkillTestRunPage,
  type SkillVersion,
  type SkillVersionPage,
  type SkillDependencyOptions,
} from './contracts';

const ROOT = '/skills';

export interface SkillCatalogQuery {
  q?: string;
  category?: string;
  status?: string;
  risk?: string;
  weight?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}

export interface SkillListRequest {
  key: string;
  signal?: AbortSignal;
}

function unwrap(value: unknown, key: string): unknown {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (typeof record[key] === 'object' && record[key] !== null) return record[key];
    if (typeof record.data === 'object' && record.data !== null) return record.data;
  }
  return value;
}

function queryString(query: SkillCatalogQuery): string {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.category && query.category !== 'all') params.set('category', query.category);
  if (query.status && query.status !== 'all') params.set('status', query.status);
  if (query.risk && query.risk !== 'all') params.set('risk', query.risk);
  if (query.weight && query.weight !== 'all') params.set('weight', query.weight);
  // Ordering is server-side because the list is paginated server-side; sorting
  // a returned page would only reorder that page.
  if (query.sort) params.set('sort', query.sort);
  params.set('page', String(query.page ?? 1));
  params.set('page_size', String(query.page_size ?? 8));
  return params.toString();
}

function skillPath(key: string, suffix = ''): string {
  return `${ROOT}/${encodeURIComponent(key)}${suffix}`;
}

const STRUCTURED_422 = /^422 · ([\s\S]*)$/;
const SAFE_ERROR_CODE = /^[a-z][a-z0-9_]+$/;
const MAX_SAFE_ERROR_TEXT = 500;

function safeErrorText(value: unknown): string | null {
  return typeof value === 'string' && value.length <= MAX_SAFE_ERROR_TEXT ? value : null;
}

/**
 * The shared client serialises a non-string `detail` as JSON. The skill backend
 * puts `{code, errors:[{loc,type,msg}]}` there. Flatten it to the bare array the
 * shared `validationFieldErrors()` understands, keeping only whitelisted fields
 * so probe markers, `input`, `ctx` and raw exception text never reach the UI.
 */
function structuredSkill422(error: unknown): { code: string; errorsJson: string } | null {
  const message = error instanceof Error ? error.message : String(error);
  const raw = STRUCTURED_422.exec(message)?.[1];
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const detail = parsed as { code?: unknown; errors?: unknown };
  const code = safeErrorText(detail.code);
  if (!code || !SAFE_ERROR_CODE.test(code) || !Array.isArray(detail.errors)) return null;
  const errors = detail.errors.map((item: unknown) => {
    if (typeof item !== 'object' || item === null) return {};
    const entry = item as { loc?: unknown; type?: unknown; msg?: unknown };
    const safe: { loc?: unknown[]; type?: string; msg?: string } = {};
    if (Array.isArray(entry.loc)) {
      safe.loc = entry.loc.filter(
        segment => safeErrorText(segment) !== null || typeof segment === 'number',
      );
    }
    const type = safeErrorText(entry.type);
    const msg = safeErrorText(entry.msg);
    if (type !== null) safe.type = type;
    if (msg !== null) safe.msg = msg;
    return safe;
  });
  return { code, errorsJson: JSON.stringify(errors) };
}

export function skillErrorCode(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return structuredSkill422(error)?.code
    ?? /^(?:\d{3} · )?([a-z][a-z0-9_]+)$/.exec(message)?.[1]
    ?? '';
}

export function skillErrorStatus(error: unknown): number | null {
  const message = error instanceof Error ? error.message : String(error);
  const match = /^(\d{3}) ·/.exec(message);
  return match ? Number(match[1]) : null;
}

export function isSkillRevisionConflict(error: unknown): boolean {
  return skillErrorCode(error) === 'skill_revision_conflict' || skillErrorStatus(error) === 409;
}

export function skillErrorMessage(error: unknown): string {
  const structured = structuredSkill422(error);
  if (structured) return `422 · ${structured.errorsJson}`;
  return error instanceof Error ? error.message : String(error);
}

export async function getSkills(query: SkillCatalogQuery = {}): Promise<SkillCatalogPage> {
  return normalizeCatalogPage(await api<unknown>(`${ROOT}?${queryString(query)}`));
}

export async function getSkillOverview(signal?: AbortSignal): Promise<SkillOverview> {
  return normalizeSkillOverview(await api<unknown>(`${ROOT}/overview`, { signal }));
}

export async function getSkill(key: string, signal?: AbortSignal): Promise<SkillRecord> {
  return normalizeSkill(unwrap(await api<unknown>(skillPath(key), { signal }), 'skill'), key);
}

/**
 * The working package is an optional attachment, so "not found" is a state
 * rather than a failure: the card renders its empty state instead of an error.
 */
export async function getSkillPackage(
  key: string,
  signal?: AbortSignal,
): Promise<SkillPackageInfo | null> {
  try {
    return normalizeSkillPackage(
      unwrap(await api<unknown>(skillPath(key, '/package'), { signal }), 'package'),
    );
  } catch (error) {
    if (skillErrorCode(error) === 'skill_package_not_found') return null;
    throw error;
  }
}

export async function uploadSkillPackage(key: string, file: File): Promise<SkillRecord> {
  const path = `${skillPath(key, '/package')}?filename=${encodeURIComponent(file.name)}`;
  return normalizeSkill(unwrap(await upload<unknown>(path, file), 'skill'), key);
}

export async function importSkillPackage(file: File): Promise<SkillRecord> {
  // Creates the Skill and binds its package in one server-side transaction, so
  // there is no "draft exists without an archive" state to clean up on failure.
  const path = `/skills/import?filename=${encodeURIComponent(file.name)}`;
  return normalizeSkill(unwrap(await upload<unknown>(path, file), 'skill'));
}

export async function deleteSkillPackage(key: string): Promise<SkillRecord> {
  return normalizeSkill(
    unwrap(await api<unknown>(skillPath(key, '/package'), { method: 'DELETE' }), 'skill'),
    key,
  );
}

export async function getSkillTemplates(signal?: AbortSignal): Promise<SkillTemplateCatalog> {
  return normalizeTemplateCatalog(unwrap(await api<unknown>('/skill-templates', { signal }), 'templates'));
}

export async function createSkill(body: CreateSkillRequest): Promise<SkillRecord> {
  return normalizeSkill(unwrap(await post<unknown>(ROOT, body), 'skill'));
}

export async function saveSkillDraft(key: string, body: SaveDraftRequest): Promise<SkillRecord> {
  return normalizeSkill(unwrap(await put<unknown>(skillPath(key, '/draft'), body), 'skill'), key);
}

export async function duplicateSkill(key: string, revision: number, name: string): Promise<SkillRecord> {
  return normalizeSkill(unwrap(await post<unknown>(skillPath(key, '/duplicate'), { revision, name }), 'skill'));
}

export async function getSkillTestRuns(
  key: string,
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
): Promise<SkillTestRunPage> {
  return normalizeTestRunPage(await api<unknown>(
    `${skillPath(key, '/test-runs')}?page=${page}&page_size=${pageSize}`,
    { signal },
  ));
}

export async function runSkillTest(key: string, body: SkillTestInput): Promise<SkillTestRun> {
  return normalizeTestRun(unwrap(await post<unknown>(skillPath(key, '/test-runs'), body), 'run'));
}

export async function getSkillReadiness(key: string, draftRevision: number, signal?: AbortSignal): Promise<SkillReadiness> {
  return normalizeReadiness(await api<unknown>(skillPath(key, '/readiness'), { signal }), draftRevision);
}

export async function getSkillVersions(
  key: string,
  page = 1,
  pageSize = 50,
  signal?: AbortSignal,
): Promise<SkillVersionPage> {
  return normalizeVersionPage(await api<unknown>(
    `${skillPath(key, '/versions')}?page=${page}&page_size=${pageSize}`,
    { signal },
  ));
}

export async function getSkillVersion(key: string, version: number, signal?: AbortSignal): Promise<SkillVersion> {
  return normalizeVersion(unwrap(await api<unknown>(skillPath(key, `/versions/${version}`), { signal }), 'version'));
}

export async function publishSkill(key: string, body: PublishSkillRequest): Promise<SkillVersion> {
  return normalizeVersion(unwrap(await post<unknown>(skillPath(key, '/publish'), body), 'version'));
}

export async function rollbackSkill(key: string, body: RollbackSkillRequest): Promise<SkillVersion> {
  return normalizeVersion(unwrap(await post<unknown>(skillPath(key, '/rollback'), body), 'version'));
}

export async function getSkillActivity(signal?: AbortSignal): Promise<SkillDependencyOptions> {
  const [models, knowledgeBases, tools] = await Promise.allSettled([
    api<unknown>('/model-gateway/profiles', { signal }),
    api<unknown>('/knowledge-bases', { signal }),
    api<unknown>('/tools', { signal }),
  ]);
  const error = (result: PromiseSettledResult<unknown>) =>
    result.status === 'rejected'
      ? (result.reason instanceof Error ? result.reason.message : String(result.reason))
      : '';
  return {
    models: models.status === 'fulfilled' ? normalizeModelProfiles(models.value) : [],
    knowledgeBases: knowledgeBases.status === 'fulfilled' ? normalizeKnowledgeBases(knowledgeBases.value) : [],
    tools: tools.status === 'fulfilled' ? normalizeTools(tools.value) : [],
    errors: {
      models: error(models),
      knowledgeBases: error(knowledgeBases),
      tools: error(tools),
    },
  };
}

export async function getSkillMe(signal?: AbortSignal): Promise<{
  role: string;
  permissions: string[];
}> {
  const value = await api<unknown>('/me', { signal });
  if (typeof value !== 'object' || value === null) return { role: 'viewer', permissions: [] };
  const record = value as Record<string, unknown>;
  return {
    role: typeof record.role === 'string' ? record.role : 'viewer',
    permissions: Array.isArray(record.permissions)
      ? record.permissions.filter((item): item is string => typeof item === 'string')
      : [],
  };
}

export function definitionFromInput(input: JsonObject, fallback: SkillDefinition): SkillDefinition {
  if (typeof input.definition === 'object' && input.definition !== null) {
    return input.definition as SkillDefinition;
  }
  return fallback;
}
