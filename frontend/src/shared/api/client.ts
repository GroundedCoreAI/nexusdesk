export interface PlatformModule { id: string; name: string; description: string; status: string }
export interface AgentConfig {
  reply_language?: "auto" | "zh-CN" | "zh-TW" | "en" | "hi";
  system_prompt: string;
  tool_names: string[];
  knowledge_base_ids: string[];
  max_model_rounds: number;
  model_profile_id?: string | null;
  model_profile_version?: number | null;
  summary_enabled?: boolean;
  memory_enabled?: boolean;
  memory_read_enabled?: boolean;
  memory_write?: boolean;
  memory_types?: Array<"profile" | "preference" | "event">;
  memory_search_enabled?: boolean;
  memory_write_mode?: "auto" | "review";
  memory_inject_max_items?: number | null;
  memory_search_limit?: number | null;
  memory_blacklist_auto_handoff?: boolean;
}
/** Platform-side memory capability caps exposed by GET /agents/memory-config-caps. */
export interface MemoryConfigCaps {
  summary_enabled: boolean;
  memory_inject_enabled: boolean;
  memory_extract_enabled: boolean;
  memory_inject_max_items: number;
  memory_search_limit: number;
  memory_blacklist_auto_handoff: boolean;
}
export interface Agent { created_by?: string | null; industry?:string; tags?:string[]; is_example?:boolean; updated_at?: string; created_at?: string; id: string; name: string; description: string; draft: AgentConfig; draft_revision: number; published_version: number | null; archived?: boolean }
export interface KnowledgeBase { id: string; name: string; document_count: number; enabled: boolean }
export interface Tool { revision?: number; published_version?: number; id: string; name: string; enabled: boolean; source: string; spec: Record<string, unknown> }
export interface Conversation { deleted_agent?: { id: string; name: string; published_version: number | null } | null; source?: "business" | "playground"; last_message?: string | null; revision?: number; id: string; external_id: string; mode: string; agent_id: string | null; assigned_to: string | null; customer_id?: string | null; updated_at: string }
export interface Run { id: string; conversation_id: string; status: string; error_code: string | null; created_at: string; output?: string; ttfc_ms?: number | null }
export interface Message { id: string; seq: number; role: string; content: string; created_at: string; run_id?: string | null }
export interface Action { id: string; status: string; payload: { title: string; description: string }; expires_at: string }
export interface ConversationDetail extends Conversation { messages: Message[]; runs: Run[]; actions: Action[] }
export interface Handoff { revision?: number; id: string; conversation_id: string; external_id: string; reason: string; summary: string; status: string; assignee: string | null }
export interface Ticket { ticket_no?: string; priority?: number; assignee_id?: string | null; customer_id?: string | null; customer_active?: boolean; due_at?: string | null; created_at?: string; updated_at?: string; resolution?: string | null; id: string; title: string; description: string; status: string; note: string; revision: number }
export type ApprovalStatus = 'draft' | 'pending' | 'approved' | 'rejected' | 'cancelled';
export type ApprovalDecision = 'approve' | 'reject';
export interface ApprovalRequest {
  id: string;
  tenant_id: string;
  title: string;
  description: string;
  requested_by: string;
  status: ApprovalStatus;
  revision: number;
  idempotency_key: string | null;
  decision_by: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface ApprovalPage {
  items: ApprovalRequest[];
  total: number;
  page: number;
  page_size: number;
}
export interface ApprovalAuditEvent {
  id: number;
  actor: string;
  action: string;
  resource: string;
  details: Record<string, unknown>;
  ip: string | null;
  created_at: string;
}
export interface ChannelField {
  name: string;
  label: string;
  required?: boolean;
  secret?: boolean;
  type?: "text" | "select";
  options?: { value: string; label: string }[];
  default?: string;
}
export interface ChannelProvider {
  id: string;
  name: string;
  description: string;
  native: boolean;
  config_fields: ChannelField[];
  credential_fields: ChannelField[];
}
export interface Channel {
  id: string;
  name: string;
  agent_id: string;
  enabled: boolean;
  provider: string;
  config: Record<string, unknown>;
  credentials_configured: boolean;
  last_error_code?: string | null;
  last_activity_at?: string | null;
  token?: string | null;
}
export interface ChannelDelivery {
  id: string;
  message_id: string;
  role: string;
  status: string;
  attempts: number;
  http_status: number | null;
  error_code: string | null;
  next_attempt_at: string;
  created_at: string;
  updated_at: string;
}
export interface Document { id: string; title: string; content: string; current_version: number; enabled: boolean }
export interface SearchResult { chunk_id: string; title: string; version: number; excerpt: string; score: number }
export interface Summary { total: number; completed: number; failed: number; cancelled: number; running: number; queued: number; average_seconds: number | null; p95_seconds: number | null; tool_failures: number; tokens: number; ttfc?: { p50_ms: number | null; p95_ms: number | null; samples: number } }
export interface EvaluationCaseSpec { input: string; expected_contains?: string[]; forbidden_contains?: string[]; expected_tools?: string[] | null; mock_tools?: Record<string, unknown>; reference_answers?: string[] }
export interface EvaluationCase { id: string; name: string; spec: EvaluationCaseSpec }
export interface EvaluationResult { case_id?: string; status?: string; rules_passed?: boolean; rule_violations?: string[]; judge?: unknown; judge_error?: string; similarity?: unknown; scoring?: unknown; name: string; passed: boolean; output: string; tools: string[]; error: string | null }
export interface EvaluationEnvironmentKnowledge { id: string; name: string; documents: number; published: number }
export interface EvaluationEnvironment { agent_version: number; model: { profile_id: string | null; version: number | null }; tools: string[]; knowledge: EvaluationEnvironmentKnowledge[]; memory: { enabled: boolean; write: boolean; summary: boolean } }
export interface EvaluationReport { id: string; agent_version: number; created_at: string; results: EvaluationResult[]; environment?: EvaluationEnvironment | null }
export interface EvaluationReportPage { items: EvaluationReport[]; total: number; page: number; page_size: number; versions: number[] }
export interface EvaluationCaseRun { agent_version: number; result: EvaluationResult }
export interface EvaluationTrendPoint { id: string; agent_version: number; created_at: string; total: number; passed: number; pass_rate: number; needs_review: number; errors: number }
export interface EvaluationTrend { points: EvaluationTrendPoint[]; limit: number }
export interface EvaluationImportError { row: number; name: string; error: string }
export interface EvaluationImport { created: number; updated: number; total: number; errors: EvaluationImportError[] }
export interface QualitySummary { agents: number; evaluated: number; reports: number; cases: number; passed: number; failed: number; needs_review: number; errors: number; pass_rate: number | null }
export interface QualityAgentRow {
    agent_id: string; agent_name: string; archived: boolean; published_version: number | null;
    report_id: string | null; agent_version: number | null; created_at: string | null; cases: number;
    total: number; passed: number; failed: number; needs_review: number; errors: number;
    pass_rate: number | null; previous_pass_rate: number | null; delta: number | null; regressions: number;
}
export interface QualityOverview { summary: QualitySummary; agents: QualityAgentRow[] }
export interface QualityReviewItem {
    agent_id: string; agent_name: string; agent_archived: boolean; report_id: string; agent_version: number;
    created_at: string; case_id: string | null; name: string | null; status: string; raw_status: string | null;
    error: string | null; judge_error: string | null; rule_violations: string[];
}
export interface QualityReviews { items: QualityReviewItem[]; total: number; page: number; page_size: number; status: string; counts: Record<string, number> }
export interface QualityRegressionItem {
    agent_id: string; agent_name: string; report_id: string; previous_report_id: string; agent_version: number;
    previous_agent_version: number; created_at: string; case_id: string | null; name: string | null;
    status: string; previous_status: string; error: string | null; judge_error: string | null;
}
export interface QualityRegressions { items: QualityRegressionItem[]; total: number; page: number; page_size: number }
export interface Audit { id: number; actor: string; action: string; resource: string; ip: string | null; created_at: string }

// Phase 2 · customer entity + profile/preference memory (console API contract §5).
export interface CustomerMemoryStats {
  /** active + pending item count (FR-2). */
  total: number;
  profile: number;
  preference: number;
  event: number;
  pending: number;
  /** Active service-flag keys (vip / complaint_risk / blacklist). */
  flags: string[];
  /** max(updated_at) across the customer's items. */
  last_updated_at: string | null;
}
export interface MemoryCustomer { id: string; external_keys: string[]; item_count: number; last_active_at: string | null; created_at: string; memory_stats?: CustomerMemoryStats | null }
export interface MemoryCustomerPage { items: MemoryCustomer[]; total: number; page: number; page_size: number }
export interface MemoryIdentity { id: string; source: string; external_key: string; created_at: string }
export interface MemoryItem { id: string; type: string; key: string; content: string; confidence: number; status: string; source_type: string; source_ref: string | null; prev_content?: string | null; revision?: number; customer_id?: string; protected?: boolean; last_referenced_at?: string | null; reference_count?: number; effective_confidence?: number | null; updated_at: string; created_at?: string }
export interface MemoryCustomerDetail { id: string; created_at: string; identities: MemoryIdentity[]; items: MemoryItem[] }
export interface MemoryPendingItem extends MemoryItem { customer_id: string; customer_external_keys?: string[] }
export interface MemoryPendingPage { items: MemoryPendingItem[]; total: number; page: number; page_size: number }

// Phase 6 · injection explainability + lifecycle visualization (03-technical-design §2/§3).
/** Run-dimension injection record: one row per run that injected memory for a customer. */
export interface MemoryInjection {
  run_id: string;
  injected_at: string;
  /** Number of memory entries injected in that run (flags included). */
  item_count: number;
  /** Owning conversation for the deep link, when resolvable. */
  conversation_id: string | null;
}
/** Item-level detail of one run's injection; content is never stored, key/type come from the live join. */
export interface MemoryInjectionDetail {
  item_id: string;
  /** null once the item is deleted (render as 已删除, C3). */
  key: string | null;
  type: string | null;
  status: string | null;
  /** flag | profile | preference | event (summary is not logged, D2). */
  section: string;
  /** effective_confidence at injection time; null for flags. */
  score: number | null;
  injected_at?: string;
  customer_id?: string;
  item_deleted: boolean;
}
/** Reverse lookup row: one run that injected a given item. */
export interface MemoryItemInjection {
  run_id: string;
  injected_at: string;
  section: string;
  score: number | null;
  conversation_id: string | null;
}
/** memory.* audit event; details never carry memory content or PII (Phase 4 C4). */
export interface MemoryAuditEvent {
  id: number;
  actor: string;
  action: string;
  resource: string;
  details: Record<string, unknown>;
  created_at: string;
}
export interface MemoryInjectionList { items: MemoryInjection[] }
export interface MemoryRunInjections { run_id: string; items: MemoryInjectionDetail[] }
export interface MemoryItemInjectionList { items: MemoryItemInjection[] }
export interface MemoryAuditList { items: MemoryAuditEvent[] }
/** Single-item lifecycle (FR-5): full live fields (null once deleted), audit timeline, injection summary. */
export interface MemoryItemTimeline {
  item: MemoryItem | null;
  timeline: MemoryAuditEvent[];
  injection_count: number;
  last_injected_at: string | null;
}
export interface MemoryCustomerListQuery {
  q?: string;
  page?: number;
  page_size?: number;
  with_stats?: boolean;
  /** Server-side sort: memory total or pending count, descending. */
  sort?: 'total' | 'pending';
  /** Service-flag filter (vip / complaint_risk / blacklist). */
  flag?: string;
}
export function getMemoryCustomers(query: MemoryCustomerListQuery = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  params.set('page', String(query.page ?? 1));
  params.set('page_size', String(query.page_size ?? 20));
  if (query.q) params.set('q', query.q);
  if (query.with_stats) params.set('with_stats', 'true');
  if (query.sort) params.set('sort', query.sort);
  if (query.flag) params.set('flag', query.flag);
  return api<MemoryCustomerPage>(`/memory/customers?${params}`, { signal });
}
export const getCustomerInjections = (customerId: string, limit = 50) => api<MemoryInjectionList>(`/memory/customers/${customerId}/injections?limit=${limit}`);
export const getRunInjections = (runId: string) => api<MemoryRunInjections>(`/memory/runs/${runId}/injections`);
export const getItemInjections = (itemId: string, limit = 20) => api<MemoryItemInjectionList>(`/memory/items/${itemId}/injections?limit=${limit}`);
export const getItemTimeline = (itemId: string, limit = 100) => api<MemoryItemTimeline>(`/memory/items/${itemId}/timeline?limit=${limit}`);
export const getCustomerAudit = (customerId: string, limit = 100) => api<MemoryAuditList>(`/memory/customers/${customerId}/audit?limit=${limit}`);

// Phase 4 · governance observability (GET /observability/memory).
export interface MemoryExtractionDay { day: string; runs: number; added: number; updated: number; pending: number; dropped: number; pii_masked: number }
// Phase 7 · production health sections of GET /observability/memory; these
// follow the request's window_hours while the Phase 4 sections above keep
// their fixed windows.
export interface MemoryTaskKind { kind: string; avg_ms: number | null; p95_ms: number | null; done: number; failed: number }
export interface MemoryAgentRow { agent_id: string | null; customer_runs: number; injected_runs: number; inject_rate: number | null; items_written: number | null; tasks_failed: number | null }
export interface MemorySummary {
  window_hours: number;
  extraction_daily: MemoryExtractionDay[];
  hit_rate: { customer_runs: number; injected_runs: number };
  backlog: { pending: number; oldest_age_seconds: number | null };
  governance: { action: string; n: number }[];
  pii_masked: number;
  reinforce: { tasks_done: number; tasks_failed: number; ids_refreshed: number };
  decay: { decay_pending: number; decay_expired: number; evicted: number; expired_restored: number };
  search: { calls: number; empty: number };
  tasks: { pending: number; running: number; failed_15m: number; oldest_pending_age_minutes: number | null; by_kind: MemoryTaskKind[] };
  embedding: { failed_backlog: number; retry_scanned_7d: number; retry_succeeded_7d: number };
  search_modes: { vector: number; text: number; keyword_fallback: number; fallback_rate: number | null };
  search_quality: { calls: number; empty: number; empty_rate: number | null; avg_returned: number | null };
  maintenance: { ttl_last_at: string | null; decay_last_at: string | null; rule_scan_last_at: string | null; embedding_retry_last_at: string | null; heartbeat_last_at: string | null; overdue: string[] };
  agents: MemoryAgentRow[];
  injection: { source: "detail" | "events"; avg_items: number | null; by_section: { flag: number | null; profile: number | null; preference: number | null; event: number | null } };
  pending_quality: { confirmed_7d: number; rejected_7d: number; confirm_rate: number | null };
}
/** Phase 7 · one memory.alert.* firing (GET /observability/memory/alerts, a bare newest-first array). */
export interface MemoryAlert { rule: string; at: string; value: number | null; threshold: number | null; window: string }
export function getMemorySummary(windowHours?: number, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (windowHours) params.set('window_hours', String(windowHours));
  const query = params.toString();
  return api<MemorySummary>(`/observability/memory${query ? `?${query}` : ''}`, { signal });
}
export const getMemoryAlerts = (windowHours = 24, signal?: AbortSignal) => api<MemoryAlert[]>(`/observability/memory/alerts?window_hours=${windowHours}`, { signal });

export type CapabilityLifecycleStatus = 'registered' | 'starting' | 'ready' | 'degraded' | 'stopped';
export interface CapabilityStatusItem {
  capability_id: string;
  version: string;
  enabled?: boolean;
  config_version?: number | null;
  status: CapabilityLifecycleStatus;
  reason: string | null;
  last_started_at: string | null;
  last_stopped_at: string | null;
  last_failure_at: string | null;
  failure_count: number;
}
export interface CapabilityObservability {
  capabilities: {
    items: CapabilityStatusItem[];
    summary: {
      total: number;
      by_status: Record<CapabilityLifecycleStatus, number>;
      failures: number;
    };
  };
  events: {
    published: number;
    subscribers: number;
    failures: number;
    persistence_failures?: number;
    queue?: Record<string, number>;
  };
}
export interface CapabilityConfigVersion {
  capability_id: string;
  version: number;
  schema_version: string;
  config: Record<string, unknown>;
  created_by: string;
  created_at: string;
  rollback_of: number | null;
}
export interface CapabilityConfigPage { items: CapabilityConfigVersion[] }
export type ExtensionEventStatus = 'pending' | 'running' | 'done' | 'failed';
export interface ExtensionEventTask {
  id: string;
  status: ExtensionEventStatus;
  attempts: number;
  max_attempts: number;
  error: string | null;
  run_after: string;
  created_at: string;
  updated_at: string;
  idempotency_key: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
}
export interface ExtensionEventPage {
  items: ExtensionEventTask[];
  total: number;
  page: number;
  page_size: number;
}
export function getExtensionEvents(status?: ExtensionEventStatus, page = 1, pageSize = 20) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status) params.set('status', status);
  return api<ExtensionEventPage>(`/extensions/events?${params}`);
}
export function getUiExtensions(signal?: AbortSignal) {
  return api<import('../../contracts').UiExtensionManifest[]>('/extensions/ui', { signal });
}
export function enableCapability(capabilityId: string) {
  return post<CapabilityStatusItem>(`/extensions/capabilities/${capabilityId}/enable`);
}
export function disableCapability(capabilityId: string) {
  return post<CapabilityStatusItem>(`/extensions/capabilities/${capabilityId}/disable`);
}
export function retryCapability(capabilityId: string) {
  return post<CapabilityStatusItem>(`/extensions/capabilities/${capabilityId}/retry`);
}
export function getCapabilityConfig(capabilityId: string, signal?: AbortSignal) {
  return api<CapabilityConfigVersion>(`/extensions/capabilities/${capabilityId}/config`, { signal });
}
export function getCapabilityConfigVersions(capabilityId: string, signal?: AbortSignal) {
  return api<CapabilityConfigPage>(`/extensions/capabilities/${capabilityId}/config/versions`, { signal });
}
export function saveCapabilityConfig(
  capabilityId: string,
  config: Record<string, unknown>,
  schemaVersion = 'v1',
) {
  return post<CapabilityConfigVersion>(`/extensions/capabilities/${capabilityId}/config`, {
    schema_version: schemaVersion,
    config,
  });
}
export function rollbackCapabilityConfig(capabilityId: string, version: number) {
  return post<CapabilityConfigVersion>(`/extensions/capabilities/${capabilityId}/config/rollback`, { version });
}
export function getApprovals(
  status: ApprovalStatus | 'all' = 'all',
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({
    status,
    page: String(page),
    page_size: String(pageSize),
  });
  return api<ApprovalPage>(`/approvals?${params}`, { signal });
}
export function getApproval(approvalId: string, signal?: AbortSignal) {
  return api<ApprovalRequest>(`/approvals/${approvalId}`, { signal });
}
export function getApprovalAudit(approvalId: string, limit = 100, signal?: AbortSignal) {
  return api<{ items: ApprovalAuditEvent[]; approval_id: string }>(
    `/approvals/${approvalId}/audit?limit=${limit}`,
    { signal },
  );
}
export function createApproval(body: {
  title: string;
  description?: string;
  idempotency_key?: string;
}) {
  return post<ApprovalRequest>('/approvals', body);
}
export function decideApproval(approvalId: string, decision: ApprovalDecision, revision: number) {
  return post<ApprovalRequest>(`/approvals/${approvalId}/decision`, { decision, revision });
}
export function cancelApproval(approvalId: string, revision: number) {
  return post<ApprovalRequest>(`/approvals/${approvalId}/cancel`, { revision });
}

export function token() { return sessionStorage.getItem('agent-platform-token') || ''; }
export function setToken(value: string) { if (value) sessionStorage.setItem('agent-platform-token', value); else sessionStorage.removeItem('agent-platform-token'); }
async function fail(response: Response, credential: string): Promise<never> {
  let detail: unknown;
  try { detail = (await response.json() as { detail: unknown }).detail; } catch { detail = response.statusText; }
  if (response.status === 401 && credential === token() && ['invalid_api_token','invalid_local_session','invalid_enterprise_session','identity_provider_session_revoked'].includes(String(detail))) {
    window.dispatchEvent(new CustomEvent('nexusdesk:session-expired'));
  }
  throw new Error(`${response.status} · ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const credential = token();
  if (options.body) headers.set('Content-Type', 'application/json');
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const response = await fetch('/api/v1' + path, { ...options, headers });
  if (!response.ok) return fail(response, credential);
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
/** Authenticated binary upload. The body is the raw file, matching the API's streaming routes. */
export async function upload<T>(path: string, file: File): Promise<T> {
  const headers = new Headers({ 'Content-Type': file.type || 'application/octet-stream' });
  const credential = token();
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const response = await fetch('/api/v1' + path, { method: 'POST', headers, body: file });
  if (!response.ok) return fail(response, credential);
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
/** Authenticated download that keeps the server's RFC 5987 filename. */
export async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const credential = token();
  const headers = new Headers();
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const response = await fetch('/api/v1' + path, { headers });
  if (!response.ok) return fail(response, credential);
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get('content-disposition') || '');
  return { blob: await response.blob(), filename: encoded ? decodeURIComponent(encoded[1]) : 'download' };
}
export const post = <T,>(path: string, body: unknown = {}) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
export const retryExtensionEvent = (eventId: string) =>
  post<ExtensionEventTask>(`/extensions/events/${eventId}/retry`);
export const getModules = (signal?: AbortSignal) => api<PlatformModule[]>('/modules', { signal });
