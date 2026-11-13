export interface PlatformModule { id: string; name: string; description: string; status: string }
export type ServiceApplicationStatus = 'draft' | 'review' | 'published' | 'offline';
export type ScenarioStatus = 'draft' | 'review' | 'published' | 'offline';
export type ScenarioTemplate = 'consult' | 'query' | 'action';
export type ScenarioEntryType = 'natural_language' | 'service_catalog' | 'object_card' | 'external_link';
export type ScenarioObjectMode = 'none' | 'implicit' | 'optional' | 'required' | 'multiple';
export type ScenarioHandlerType = 'direct' | 'knowledge' | 'query' | 'action' | 'agent' | 'human' | 'tracking';
export type ScenarioDecisionKind = 'select_object' | 'confirm_object' | 'select_intent' | 'confirm_action' | 'handoff';
export type ApplicationCapabilityType = 'direct' | 'knowledge' | 'query' | 'action' | 'agent' | 'human' | 'tracking';
export type ApplicationChannelStatus = 'active' | 'canary' | 'disabled';
export interface ApplicationScenarioReference {
  key: string;
  version?: number | null;
  enabled?: boolean;
}
export interface ApplicationCapability {
  key: string;
  type: ApplicationCapabilityType;
  label: string;
  description?: string;
  enabled?: boolean;
  priority?: number;
  when?: Record<string, unknown>;
  agent_id?: string | null;
  agent_version?: number | null;
  agent_name?: string | null;
  queue?: string | null;
  tool?: string | null;
  config?: Record<string, unknown>;
}
export interface ApplicationChannel {
  key: string;
  name: string;
  type?: string;
  status?: ApplicationChannelStatus;
  config?: Record<string, unknown>;
}
export interface ApplicationServiceCategory {
  name: string;
  order: number;
}
export interface ScenarioEntry {
  key: string;
  type: ScenarioEntryType;
  label: string;
  description?: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
}
export interface ScenarioCandidateStrategy {
  sort?: string;
  limit?: number;
  filters?: string[];
  empty_state: string;
  unavailable_state: string;
}
export interface ScenarioBusinessObject {
  type: string;
  provider: string;
  required: boolean;
  mode: ScenarioObjectMode;
  candidate_strategy: ScenarioCandidateStrategy;
  permission_policy?: string;
  config?: Record<string, unknown>;
}
export interface ScenarioFactField {
  key: string;
  label: string;
  source: string;
  format?: string;
  order?: number;
  masked?: boolean;
  audiences?: string[];
  refresh?: string;
  config?: Record<string, unknown>;
}
export interface ScenarioDecisionOption {
  value: string;
  label: string;
  description?: string;
  next?: string | null;
}
export interface ScenarioUserDecision {
  key: string;
  kind: ScenarioDecisionKind;
  label: string;
  required?: boolean;
  options?: ScenarioDecisionOption[];
  allow_free_text?: boolean;
  allow_skip?: boolean;
  confirm?: boolean;
  correctable?: boolean;
  when?: Record<string, unknown>;
}
export interface ScenarioRecommendation {
  key: string;
  label: string;
  message: string;
  when?: Record<string, unknown>;
}
export interface ScenarioHandlerCondition {
  object_statuses?: string[];
  message_terms?: string[];
  decision_keys?: string[];
  requires_object?: boolean | null;
}
export interface ScenarioHandler {
  key: string;
  type: ScenarioHandlerType;
  label: string;
  priority?: number;
  enabled?: boolean;
  when?: ScenarioHandlerCondition;
  agent_id?: string | null;
  agent_version?: number | null;
  agent_name?: string | null;
  queue?: string | null;
  tool?: string | null;
  reply?: string | null;
  config?: Record<string, unknown>;
}
export interface ScenarioConfig {
  schema_version: 'v1';
  name: string;
  description: string;
  domain: string;
  category: string;
  template: ScenarioTemplate;
  channels: string[];
  entries: ScenarioEntry[];
  facts: ScenarioFactField[];
  object: ScenarioBusinessObject | null;
  decisions: ScenarioUserDecision[];
  recommendations: ScenarioRecommendation[];
  handlers: ScenarioHandler[];
  fallback_order: string[];
  matching: { keywords: string[]; intents: string[]; negative_keywords: string[] };
  config: Record<string, unknown>;
}
export interface ServiceApplicationConfig {
  schema_version: 'v1';
  name: string;
  description: string;
  service_categories: ApplicationServiceCategory[];
  scenarios: ApplicationScenarioReference[];
  capabilities: ApplicationCapability[];
  default_execution_order: string[];
  channels: ApplicationChannel[];
}
export interface ServiceApplicationSummary {
  id: string;
  key: string;
  name: string;
  description: string;
  status: ServiceApplicationStatus;
  revision: number;
  published_version: number | null;
  config: ServiceApplicationConfig;
  scenario_count: number;
  capability_count: number;
  channel_count: number;
  has_unpublished_changes: boolean;
  archived?: boolean;
  created_at?: string;
  updated_at?: string;
}
export interface ServiceApplicationPage { items: ServiceApplicationSummary[]; total: number }
export interface ServiceApplicationOverview {
  applications: number;
  by_status: Record<ServiceApplicationStatus, number>;
  scenarios: number;
  capabilities: number;
  channels: number;
  simulations: number;
}
export interface ServiceApplicationVersion {
  id: string;
  version: number;
  config: ServiceApplicationConfig;
  source_version: number | null;
  created_by: string;
  created_at: string;
  published: boolean;
}
export interface ServiceApplicationVersionPage {
  items: ServiceApplicationVersion[];
  published_version: number | null;
}
export type ServiceReadinessState = 'ready' | 'simulate_only' | 'blocked';
export type ServiceReadinessCheckStatus = 'pass' | 'warning' | 'blocked';
export type ServiceReadinessCheckSeverity = 'blocking' | 'warning' | 'info';
export interface ServiceReadinessCheck {
  key: string;
  title: string;
  detail: string;
  status: ServiceReadinessCheckStatus;
  severity: ServiceReadinessCheckSeverity;
}
export interface ServiceReadinessCounts {
  pass: number;
  warning: number;
  blocked: number;
}
export interface ServiceScenarioReadiness {
  key: string;
  name: string;
  version: number | null;
  scenario_status: string;
  status: ServiceReadinessState;
  label: string;
  description: string;
  checks: ServiceReadinessCheck[];
  counts: ServiceReadinessCounts;
  can_publish: boolean;
  can_simulate: boolean;
}
export interface ServiceApplicationReadiness {
  key: string;
  name: string;
  revision: number;
  application_status: string;
  status: ServiceReadinessState;
  label: string;
  description: string;
  checks: ServiceReadinessCheck[];
  counts: ServiceReadinessCounts;
  can_publish: boolean;
  can_simulate: boolean;
  scenarios: ServiceScenarioReadiness[];
}
export interface ServiceScenarioMetrics {
  volume: number;
  auto_resolved: number;
  handoffs: number;
  auto_resolve_rate: number;
  handoff_rate: number;
}
export interface ServiceScenarioSummary {
  id: string;
  key: string;
  name: string;
  description: string;
  domain: string;
  category?: string;
  template: ScenarioTemplate;
  status: ScenarioStatus;
  revision: number;
  published_version: number | null;
  config: ScenarioConfig;
  published_config?: ScenarioConfig | null;
  has_unpublished_changes?: boolean;
  metrics?: ServiceScenarioMetrics;
  created_at?: string;
  updated_at?: string;
}
export interface ServiceScenarioPage { items: ServiceScenarioSummary[]; total: number }
export interface ServiceScenarioVersion {
  id: string;
  version: number;
  config: ScenarioConfig;
  source_version: number | null;
  created_by: string;
  created_at: string;
  published: boolean;
}
export interface ServiceScenarioVersionPage {
  items: ServiceScenarioVersion[];
  published_version: number | null;
}
export interface SimulatedObjectInput {
  id: string;
  type: string;
  status?: string;
  facts?: Record<string, unknown>;
  accessible?: boolean;
  exists?: boolean;
}
export interface SimulationRequestInput {
  message: string;
  entry: ScenarioEntryType;
  object?: SimulatedObjectInput | null;
  selected_decision?: string | null;
  selected_handler?: string | null;
  scenario_key?: string | null;
  application_version?: number | null;
}
export interface SimulationStep {
  step: 'scene' | 'object' | 'facts' | 'decision' | 'handler' | 'result';
  status: string;
  reason?: string;
  [key: string]: unknown;
}
export interface SimulationFact {
  key: string;
  label: string;
  source: string;
  value: unknown;
  format?: string;
  order?: number;
  masked?: boolean;
  audiences?: string[];
  refresh?: string;
}
export interface SimulationDecision {
  key: string;
  kind: ScenarioDecisionKind;
  label: string;
  required: boolean;
  options: ScenarioDecisionOption[];
  confirm: boolean;
  correctable: boolean;
  selected: boolean;
  when?: Record<string, unknown>;
}
export interface SimulationTrace {
  schema_version: 'v1';
  scenario_key: string;
  scenario_name: string;
  scenario_version: number | null;
  scenario_status: ScenarioStatus;
  resolved_by: 'target' | 'keyword' | 'none';
  steps: SimulationStep[];
  object_ref?: Record<string, unknown> | null;
  facts: SimulationFact[];
  decisions: SimulationDecision[];
  recommendations: ScenarioRecommendation[];
  handler?: Record<string, unknown> | null;
  result: { status: string; reason?: string; reason_code?: string; content: string; [key: string]: unknown };
  fallback_path: string[];
  explanation: string[];
  simulated?: boolean;
  trace_id?: string | null;
  application_key?: string;
  application_revision?: number;
  application_source?: string;
  application_version?: number | null;
}
export interface ServiceTraceItem {
  id: string;
  scenario_key: string;
  scenario_version: number | null;
  simulation: boolean;
  entry: ScenarioEntryType;
  message_length: number;
  message_excerpt: string;
  object_ref: Record<string, unknown> | null;
  facts: Array<Record<string, unknown>>;
  decisions: Array<Record<string, unknown>>;
  handler_type: string | null;
  outcome: string;
  reason_code: string;
  result_summary: string;
  trace: SimulationTrace;
  created_by: string;
  created_at: string;
}
export interface ServiceTracePage { items: ServiceTraceItem[] }
export type IndustryPackMaturity = 'alpha' | 'beta' | 'ga';
export interface IndustryPackSummary {
  pack_key: string;
  name: string;
  description: string;
  pack_version: string;
  maturity: IndustryPackMaturity;
  digest: string;
  object_count: number;
  scenario_count: number;
  application_key: string | null;
  installation_count: number;
}
export interface IndustryPackCatalog {
  items: IndustryPackSummary[];
  total: number;
}
export interface IndustryPackDetail extends IndustryPackSummary {
  manifest: Record<string, unknown>;
  compiled_application: Record<string, unknown> | null;
  installations: IndustryPackInstallation[];
}
export type IndustryPackInstallationStatus = 'installed' | 'upgrading' | 'conflicted' | 'blocked';
export interface IndustryPackInstallation {
  id: string;
  pack_key: string;
  pack_version: string;
  pack_digest: string;
  maturity: IndustryPackMaturity;
  application_key: string;
  status: IndustryPackInstallationStatus;
  scenario_template_versions: Record<string, string>;
  scenario_template_digests: Record<string, string>;
  installed_scenarios: Record<string, string>;
  revision: number;
  installed_by: string;
  created_at: string | null;
  updated_at: string | null;
}
export interface IndustryPackInstallationPage {
  items: IndustryPackInstallation[];
  total: number;
}
export interface IndustryPackInstallInput {
  pack_version?: string;
  application_key?: string;
  install_scenarios?: boolean;
}
export interface IndustryPackInstallResult {
  created: boolean;
  installation: IndustryPackInstallation;
}
export type IndustryPackUpgradeStatus = 'clean' | 'conflicted' | 'blocked';
export interface IndustryPackMergeConflict {
  path: string;
  base?: unknown;
  local?: unknown;
  incoming?: unknown;
}
export interface IndustryPackScenarioUpgrade {
  template_key: string;
  scenario_key: string;
  status: IndustryPackUpgradeStatus;
  conflicts: IndustryPackMergeConflict[];
  auto_merged_fields: string[];
  kept_local_fields: string[];
  incoming_fields: string[];
  current_revision: number | null;
  merged_config: Record<string, unknown> | null;
  detail: string;
}
export interface IndustryPackUpgradePreview {
  id: string;
  installation_id: string;
  from_version: string;
  to_version: string;
  status: IndustryPackUpgradeStatus;
  scenarios: IndustryPackScenarioUpgrade[];
  application: Record<string, unknown> | null;
  application_conflicts: IndustryPackMergeConflict[];
  created_at: string | null;
}
export interface IndustryPackUpgradeResult {
  applied: boolean;
  installation: IndustryPackInstallation;
  preview_id: string;
  upgraded_scenarios: string[];
  application_key: string;
}
export type ServiceProviderKind = 'object' | 'tool' | 'human_queue';
export interface ServiceProvider {
  id: string;
  key: string;
  kind: ServiceProviderKind;
  name: string;
  description: string;
  enabled: boolean;
  config: Record<string, unknown>;
  source: string;
  source_ref: string | null;
  revision: number;
  created_at: string | null;
  updated_at: string | null;
}
export interface ServiceProviderPage {
  items: ServiceProvider[];
  total: number;
}
export interface ServiceProviderInput {
  key: string;
  kind: ServiceProviderKind;
  name: string;
  description: string;
  enabled: boolean;
  config: Record<string, unknown>;
}
export interface AgentScenarioReference {
  key: string;
  name: string;
  domain: string;
  status: ScenarioStatus;
  version: number | null;
  handler_key: string;
  handler_label: string;
  binding: string;
  agent_version: number | null;
  configured_version: number | null;
  metrics: ServiceScenarioMetrics;
  volume: number;
}
export interface AgentScenarioReferencePage { items: AgentScenarioReference[] }
/** Exact engine/protocol/adapter triple stored under `engine` in the draft JSONB. */
export interface EngineIdentity {
  engine_id: string;
  protocol_id: string;
  adapter_version: string;
}
/** Typed React settings; the three root draft fields below are its legacy aliases. */
export interface ReactExecutionConfig {
  model_profile_id: string | null;
  model_profile_version: number | null;
  max_model_rounds: number;
}
/** The 11 capability names the execution contract recognises, in CAPABILITY_ORDER. */
export const EXECUTION_CAPABILITY_NAMES = [
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
] as const;
export type ExecutionCapabilityName = typeof EXECUTION_CAPABILITY_NAMES[number];
/** Stable public reason codes (03-technical-design.md §4.1); never a secret or a path. */
export type ExecutionReasonCode =
  | 'allowed'
  | 'not_declared'
  | 'probe_unavailable'
  | 'probe_timeout'
  | 'probe_stale'
  | 'workspace_unavailable'
  | 'platform_denied'
  | 'tenant_denied'
  | 'agent_disabled'
  | 'execution_denied'
  | 'policy_unavailable';
/** One row of the preview response: exactly `name/effective/reason_code` (R-21). */
export interface EffectiveCapabilityView {
  name: ExecutionCapabilityName;
  effective: boolean;
  reason_code: ExecutionReasonCode;
}
export interface ExecutionPreviewField {
  name: string;
  type: string;
  required: boolean;
}
/** `POST /agents/execution-preview` response; the endpoint is read-only by contract. */
export interface ExecutionPreview {
  engine: EngineIdentity;
  config_schema: {
    schema_version: string;
    fields: ExecutionPreviewField[];
  };
  capabilities: EffectiveCapabilityView[];
}
export interface AgentConfig {
  reply_language?: "auto" | "zh-CN" | "zh-TW" | "en" | "hi";
  system_prompt: string;
  tool_names: string[];
  knowledge_base_ids: string[];
  max_model_rounds: number;
  model_profile_id?: string | null;
  model_profile_version?: number | null;
  /** Absent on drafts written before Phase 3; the server supplies the default. */
  engine?: EngineIdentity;
  react?: ReactExecutionConfig | null;
  disabled_capabilities?: ExecutionCapabilityName[];
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
/** The only engine triple the Phase 3 registry ships for production traffic. */
export const SUPPORTED_ENGINES: EngineIdentity[] = [{ engine_id: 'react', protocol_id: 'native', adapter_version: 'v1' }];
export const DEFAULT_ENGINE: EngineIdentity = SUPPORTED_ENGINES[0];
const DEFAULT_REACT: ReactExecutionConfig = { model_profile_id: null, model_profile_version: null, max_model_rounds: 6 };
const REACT_ALIASES: Array<keyof ReactExecutionConfig> = ['model_profile_id', 'model_profile_version', 'max_model_rounds'];
/** Semantic view of the execution part of a draft; never mutates the draft. */
export interface ExecutionView {
  engine: EngineIdentity;
  engineKnown: boolean;
  react: ReactExecutionConfig | null;
  disabledCapabilities: ExecutionCapabilityName[];
  /** Draft fields whose root alias disagrees with the same field under `react`. */
  conflicts: string[];
}
/**
 * Merge the Phase 3 execution fields with the legacy root aliases.
 *
 * Reading a pre-Phase-3 draft must not fabricate fields: the defaults below
 * exist only in this returned view, so an untouched draft stays untouched
 * (03-technical-design.md §3.2, 05-acceptance-plan.md M1). Equal aliases collapse
 * into one canonical value, divergent aliases are reported instead of guessed.
 */
export function readExecution(config: AgentConfig): ExecutionView {
  const engine = config.engine ?? DEFAULT_ENGINE;
  const react = config.react;
  const legacy = config as unknown as Record<string, unknown>;
  const modern = (react ?? {}) as unknown as Record<string, unknown>;
  const merged = { ...DEFAULT_REACT } as Record<string, unknown>;
  const conflicts: string[] = [];
  for (const field of REACT_ALIASES) {
    const legacyValue = field in legacy ? legacy[field] : undefined;
    const modernValue = react && field in modern ? modern[field] : undefined;
    if (legacyValue !== undefined && modernValue !== undefined && JSON.stringify(legacyValue) !== JSON.stringify(modernValue)) {
      conflicts.push(field);
    }
    const value = modernValue !== undefined ? modernValue : legacyValue;
    if (value !== undefined) merged[field] = value;
  }
  return {
    engine,
    engineKnown: SUPPORTED_ENGINES.some(item => item.engine_id === engine.engine_id && item.protocol_id === engine.protocol_id && item.adapter_version === engine.adapter_version),
    react: engine.engine_id === 'react' ? merged as unknown as ReactExecutionConfig : null,
    disabledCapabilities: config.disabled_capabilities ? [...config.disabled_capabilities] : [],
    conflicts,
  };
}
/**
 * Write React settings back to the places the draft already uses.
 *
 * A draft may carry the legacy root fields, the typed `react` object, or both
 * (the service echoes the canonical form with the aliases filled in). Updating
 * only one of them would create an alias conflict the server rejects, so every
 * existing location is kept in step and no new key is introduced.
 */
export function patchReactConfig(config: AgentConfig, patch: Partial<ReactExecutionConfig>): AgentConfig {
  const next: AgentConfig = { ...config };
  const root = next as unknown as Record<string, unknown>;
  const react: Record<string, unknown> = { ...(config.react as unknown as Record<string, unknown> | undefined) };
  const keepsReact = !!config.react;
  for (const field of REACT_ALIASES) {
    if (!(field in patch)) continue;
    const value = (patch as Record<string, unknown>)[field];
    const inReact = keepsReact && field in react;
    // Neither alias exists: write the legacy root field, which every server
    // version accepts, instead of expanding the draft's shape on a first edit.
    if (inReact) react[field] = value;
    if (field in config || !inReact) root[field] = value;
  }
  if (keepsReact) next.react = react as unknown as ReactExecutionConfig;
  return next;
}
/** Narrow one capability; unchecking only removes a prior local narrowing. */
export function toggleDisabledCapability(config: AgentConfig, name: ExecutionCapabilityName, disabled: boolean): AgentConfig {
  const current = config.disabled_capabilities ?? [];
  const values = disabled ? [...new Set([...current, name])] : current.filter(item => item !== name);
  // An empty narrowing list is the server default, so it is not written at all.
  const next = values.slice().sort((left, right) => EXECUTION_CAPABILITY_NAMES.indexOf(left) - EXECUTION_CAPABILITY_NAMES.indexOf(right));
  return { ...config, disabled_capabilities: next.length ? next : undefined };
}
/**
 * Ask the server what a draft *would* resolve to. The request body is the strict
 * `{agent_id, config}` pair: effective/declared/available/policy fields are
 * computed server-side and are never sent, and the response grants nothing.
 */
export function previewExecution(agentId: string | null, config: AgentConfig) {
  return post<ExecutionPreview>('/agents/execution-preview', { agent_id: agentId, config });
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
/**
 * Deployment-side Phase 3 switches exposed by GET /agents/execution-config-flags
 * (03-technical-design.md §7.4, R-25). The strict response carries exactly these
 * two booleans, named verbatim like the backend settings, and nothing else; the
 * frontend only uses them to decide which Phase 3 editing entries to show. It is
 * a presentation hint — the server remains the authorization boundary.
 */
export interface ExecutionConfigFlags {
  execution_phase3_enabled: boolean;
  execution_orchestrator_enabled: boolean;
}
export interface Agent { created_by?: string | null; industry?:string; tags?:string[]; is_example?:boolean; updated_at?: string; created_at?: string; id: string; name: string; description: string; draft: AgentConfig; draft_revision: number; published_version: number | null; archived?: boolean }
export interface KnowledgeBase { id: string; name: string; document_count: number; enabled: boolean }
export interface Tool { revision?: number; published_version?: number; id: string; name: string; enabled: boolean; source: string; display_name?: string | null; relative_path?: string | null; archived?: boolean; spec: Record<string, unknown> }
export interface Conversation { deleted_agent?: { id: string; name: string; published_version: number | null } | null; source?: "business" | "playground"; last_message?: string | null; revision?: number; id: string; external_id: string; mode: string; agent_id: string | null; assigned_to: string | null; customer_id?: string | null; updated_at: string }
export interface Run { id: string; conversation_id: string; status: string; error_code: string | null; created_at: string; output?: string; ttfc_ms?: number | null }
export interface Message { id: string; seq: number; role: string; content: string; created_at: string; run_id?: string | null }
export interface Action { id: string; status: string; payload: { title: string; description: string }; expires_at: string }
export interface ConversationDetail extends Conversation { messages: Message[]; runs: Run[]; actions: Action[] }
export interface Handoff { revision?: number; id: string; conversation_id: string; external_id: string; reason: string; summary: string; status: string; assignee: string | null }
/** Operator-facing context aggregated by GET /handoffs/{id}/context. */
export interface HandoffContextFact {
  key: string;
  label: string;
  value: unknown;
  format: string;
  masked: boolean;
}
export interface HandoffContextDecisionOption { value: string; label: string }
export interface HandoffContextDecision {
  key: string;
  kind: string;
  label: string;
  required: boolean;
  confirm: boolean;
  state: 'selected' | 'pending' | string;
  options: HandoffContextDecisionOption[];
}
export interface HandoffContextAction {
  id: string;
  kind: string;
  status: string;
  valid: boolean;
  summary: string;
  created_at: string | null;
  expires_at: string | null;
}
export interface HandoffContextRun {
  id: string;
  status: string;
  error_code: string | null;
  cancel_requested: boolean;
  created_at: string | null;
  finished_at: string | null;
}
export interface HandoffContextRouting {
  disposition: string;
  action: string;
  execution_tier: string | null;
  reason_code: string;
  matched_rule_id: string | null;
  decider: string | null;
  created_at: string | null;
}
export interface HandoffContextTrace {
  id: string;
  scenario_key: string;
  scenario_version: number | null;
  simulation: boolean;
  entry: string | null;
  handler_type: string | null;
  outcome: string | null;
  reason_code: string | null;
  result_summary: string;
  message_excerpt: string;
  created_at: string | null;
}
export interface HandoffContext {
  handoff: {
    id: string;
    conversation_id: string;
    status: string;
    assignee: string | null;
    reason: string;
    summary: string;
    revision?: number | null;
    created_at: string | null;
    closed_at: string | null;
  };
  conversation: {
    id: string;
    external_id: string;
    mode: string | null;
    source: string | null;
    assigned_to: string | null;
    has_customer: boolean;
    summary: string;
    created_at: string | null;
    updated_at: string | null;
  } | null;
  application: { key: string; name: string | null; version: number | null; source: string | null } | null;
  scenario: {
    key: string;
    name: string;
    version: number | null;
    status: string | null;
    resolved_by: string | null;
    handler_type: string | null;
    outcome: string | null;
    reason_code: string | null;
  } | null;
  object: { type: string | null; id: string; status: string } | null;
  facts: HandoffContextFact[];
  decisions: HandoffContextDecision[];
  actions: HandoffContextAction[];
  runs: HandoffContextRun[];
  routing: HandoffContextRouting[];
  traces: HandoffContextTrace[];
}
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
export const createServiceApplication = (key: string, config: ServiceApplicationConfig) =>
  post<ServiceApplicationSummary>('/service-apps', { key, config });
export const updateServiceApplication = (key: string, config: ServiceApplicationConfig, revision: number) =>
  put<ServiceApplicationSummary>(`/service-apps/${key}`, { config, revision });
export const updateServiceCatalog = (
  key: string,
  categories: ApplicationServiceCategory[],
  categoryChanges: Record<string, string>,
  revision: number,
) =>
  put<ServiceApplicationSummary>(`/service-apps/${key}/service-catalog`, {
    revision,
    categories,
    category_changes: categoryChanges,
  });
export const getServiceApplicationReadiness = (key: string, signal?: AbortSignal) =>
  api<ServiceApplicationReadiness>(`/service-apps/${key}/readiness`, { signal });
export const publishServiceApplication = (key: string, revision: number) =>
  post<ServiceApplicationSummary>(`/service-apps/${key}/publish`, { revision });
export const setServiceApplicationStatus = (
  key: string,
  status: Exclude<ServiceApplicationStatus, 'published'>,
  revision: number,
) => post<ServiceApplicationSummary>(`/service-apps/${key}/status`, { status, revision });
export const rollbackServiceApplication = (key: string, version: number, revision: number) =>
  post<ServiceApplicationSummary>(`/service-apps/${key}/rollback`, { version, revision });
/** Soft delete: the application disappears from every list except `?archived=true`. */
export const archiveServiceApplication = (key: string, revision: number) =>
  post<ServiceApplicationSummary>(`/service-apps/${key}/archive`, { revision });
export const restoreServiceApplication = (key: string) =>
  post<ServiceApplicationSummary>(`/service-apps/${key}/restore`, {});
/**
 * Hard delete. Only archived applications can be purged, and the version
 * history goes with them; execution traces are kept.
 */
export const deleteServiceApplication = (key: string) =>
  api<{ key: string; deleted: boolean }>(`/service-apps/${key}`, { method: 'DELETE' });
export const simulateServiceApplication = (key: string, body: SimulationRequestInput) =>
  post<SimulationTrace>(`/service-apps/${key}/simulate`, body);
export const getIndustryPacks = (signal?: AbortSignal) =>
  api<IndustryPackCatalog>('/industry-packs', { signal });
export const getIndustryPack = (packKey: string, signal?: AbortSignal) =>
  api<IndustryPackDetail>(`/industry-packs/${encodeURIComponent(packKey)}`, { signal });
export const getIndustryPackInstallations = (signal?: AbortSignal) =>
  api<IndustryPackInstallationPage>('/industry-packs/installations', { signal });
export const installIndustryPack = (packKey: string, body: IndustryPackInstallInput) =>
  post<IndustryPackInstallResult>(`/industry-packs/${encodeURIComponent(packKey)}/install`, body);
export const previewIndustryPackUpgrade = (
  installationId: string,
  targetVersion?: string,
) =>
  post<IndustryPackUpgradePreview>(
    `/industry-packs/installations/${encodeURIComponent(installationId)}/upgrade-preview`,
    targetVersion ? { target_version: targetVersion } : {},
  );
export const applyIndustryPackUpgrade = (
  installationId: string,
  previewId: string,
  targetVersion?: string,
) =>
  post<IndustryPackUpgradeResult>(
    `/industry-packs/installations/${encodeURIComponent(installationId)}/upgrade`,
    {
      preview_id: previewId,
      ...(targetVersion ? { target_version: targetVersion } : {}),
    },
  );
export function getServiceProviders(
  kind?: ServiceProviderKind,
  query = '',
  signal?: AbortSignal,
) {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);
  if (query.trim()) params.set('q', query.trim());
  const suffix = params.toString();
  return api<ServiceProviderPage>(`/service-providers${suffix ? `?${suffix}` : ''}`, { signal });
}
export const createServiceProvider = (body: ServiceProviderInput) =>
  post<ServiceProvider>('/service-providers', body);
export const updateServiceProvider = (
  kind: ServiceProviderKind,
  key: string,
  body: ServiceProviderInput & { revision: number },
) =>
  put<ServiceProvider>(
    `/service-providers/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
    body,
  );
export const updateServiceScenario = (key: string, config: ScenarioConfig, revision: number) =>
  put<ServiceScenarioSummary>(`/service-scenarios/${key}`, { config, revision });
export const createServiceScenario = (key: string, config: ScenarioConfig) =>
  post<ServiceScenarioSummary>('/service-scenarios', { key, config });
export const publishServiceScenario = (key: string, revision: number) =>
  post<ServiceScenarioSummary>(`/service-scenarios/${key}/publish`, { revision });
export const setServiceScenarioStatus = (
  key: string,
  status: Exclude<ScenarioStatus, 'published'>,
  revision: number,
) => post<ServiceScenarioSummary>(`/service-scenarios/${key}/status`, { status, revision });
export const rollbackServiceScenario = (key: string, version: number, revision: number) =>
  post<ServiceScenarioSummary>(`/service-scenarios/${key}/rollback`, { version, revision });
export const simulateServiceScenario = (key: string, body: SimulationRequestInput) =>
  post<SimulationTrace>(`/service-scenarios/${key}/simulate`, body);
export const retryExtensionEvent = (eventId: string) =>
  post<ExtensionEventTask>(`/extensions/events/${eventId}/retry`);
export const getModules = (signal?: AbortSignal) => api<PlatformModule[]>('/modules', { signal });
