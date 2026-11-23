export interface PlatformModule { id: string; name: string; description: string; status: string }

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
/** Typed Stage A Codex settings. `credential_ref` is a UUID reference, never a key. */
export interface CodexExecutionConfig {
  protocol: 'cli_exec' | 'app_server';
  version: string;
  executable: string;
  timeout_seconds: number;
  approval_mode: 'never';
  sandbox_mode: 'read-only';
  credential_ref: string | null;
  path_env: string;
  /** Optional ModelGateway chat profile binding (issue #167). Both-or-neither. */
  model_profile_id?: string | null;
  model_profile_version?: number | null;
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
  codex?: CodexExecutionConfig | null;
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
  /**
   * Editor-only memory of the React Chat binding the user held before switching
   * to a CLI engine. The backend must clear React aliases on a CLI-engine draft
   * (fail-closed, `extra="forbid"`), so an echo from the server cannot carry the
   * binding back. This field is *never* sent to the server — `normalizeExecutionForEngine`
   * strips it — and only ever recalls a value the user actually bound; no model
   * profile is invented or injected here.
   */
  reactBindingMemory?: ReactExecutionConfig | null;
}
/**
 * Engine triples the UI can publish. The Codex CLI descriptor is registered by
 * the server only when the Stage A gate is enabled; publishing an unregistered
 * triple is still rejected there, so this list grants nothing by itself.
 */
export const SUPPORTED_ENGINES: EngineIdentity[] = [
  { engine_id: 'react', protocol_id: 'native', adapter_version: 'v1' },
  { engine_id: 'codex', protocol_id: 'cli_exec', adapter_version: 'v1' },
];
export const DEFAULT_ENGINE: EngineIdentity = SUPPORTED_ENGINES[0];
const DEFAULT_REACT: ReactExecutionConfig = { model_profile_id: null, model_profile_version: null, max_model_rounds: 6 };
// `version` is a placeholder here: there is no version UI, and the real value
// is injected from the deployment allowlist at the save/preview boundary by
// `normalizeExecutionForEngine`. An empty allowlist leaves it empty (fail-closed).
export const DEFAULT_CODEX: CodexExecutionConfig = {
  protocol: 'cli_exec', version: '', executable: 'codex', timeout_seconds: 600,
  approval_mode: 'never', sandbox_mode: 'read-only', credential_ref: null,
  path_env: '/usr/local/bin:/usr/bin:/bin',
  model_profile_id: null, model_profile_version: null,
};
const REACT_ALIASES: Array<keyof ReactExecutionConfig> = ['model_profile_id', 'model_profile_version', 'max_model_rounds'];
/** Semantic view of the execution part of a draft; never mutates the draft. */
export interface ExecutionView {
  engine: EngineIdentity;
  engineKnown: boolean;
  react: ReactExecutionConfig | null;
  codex: CodexExecutionConfig | null;
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
    // Legacy root aliases are a React-engine concept. On a CLI engine both the
    // aliases and a leftover React block are neutralised at the wire boundary,
    // so a disagreement between them is not a conflict the user must resolve —
    // reporting it made switching engines look broken (P7 defect set).
    if (engine.engine_id === 'react' && legacyValue !== undefined && modernValue !== undefined && JSON.stringify(legacyValue) !== JSON.stringify(modernValue)) {
      conflicts.push(field);
    }
    const value = modernValue !== undefined ? modernValue : legacyValue;
    if (value !== undefined) merged[field] = value;
  }
  return {
    engine,
    engineKnown: SUPPORTED_ENGINES.some(item => item.engine_id === engine.engine_id && item.protocol_id === engine.protocol_id && item.adapter_version === engine.adapter_version),
    react: engine.engine_id === 'react' ? merged as unknown as ReactExecutionConfig : null,
    codex: engine.engine_id === 'codex' ? (config.codex ?? { ...DEFAULT_CODEX }) : null,
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
  // Keep the CLI-save snapshot in step with the user's explicit choice: a
  // freshly chosen binding is remembered, and clearing the picker must clear
  // the memory too so an old profile is never resurrected on a later switch.
  const remembered = currentReactBinding(next);
  if (remembered)
    next.reactBindingMemory = remembered;
  else if ('model_profile_id' in patch)
    delete next.reactBindingMemory;
  return next;
}
/** Update the typed Codex block only; it has no legacy root aliases to keep in step. */
export function patchCodexConfig(config: AgentConfig, patch: Partial<CodexExecutionConfig>): AgentConfig {
  const codex = { ...(config.codex ?? DEFAULT_CODEX), ...patch };
  return { ...config, codex };
}
/**
 * The React settings the editor is currently holding, read from whichever
 * location has them (typed block first, then the legacy root aliases). Returns
 * null unless a Chat profile is actually bound, so an empty/default React
 * block is never mistaken for a remembered binding.
 */
export function currentReactBinding(config: AgentConfig): ReactExecutionConfig | null {
  const root = config as unknown as Record<string, unknown>;
  const react = config.react as unknown as Record<string, unknown> | null | undefined;
  const pick = (field: keyof ReactExecutionConfig): unknown =>
    react && react[field] !== undefined ? react[field] : root[field];
  const modelProfileId = pick('model_profile_id') as string | null | undefined;
  const modelProfileVersion = pick('model_profile_version') as number | null | undefined;
  if (modelProfileId == null || modelProfileVersion == null)
    return null;
  return {
    model_profile_id: modelProfileId,
    model_profile_version: modelProfileVersion,
    max_model_rounds: (pick('max_model_rounds') as number | undefined) ?? DEFAULT_REACT.max_model_rounds,
  };
}

/**
 * Switch the active engine without destroying the other engine's settings.
 *
 * The editor keeps both typed blocks while the user switches back and forth, so
 * a Codex version or a bound model profile is not lost on a round trip (a
 * switch used to reset the Codex version to an empty string, which then failed
 * the strict version field). Which block is actually *submitted* is decided by
 * `normalizeExecutionForEngine` at the save/preview boundary: `ExecutionConfig`
 * accepts exactly one engine block, and a CLI engine must not carry non-default
 * legacy React aliases. Keeping normalisation at the boundary — not inside the
 * switch — is what makes the switch lossless without ever sending an invalid
 * draft.
 *
 * A CLI-engine save is the one case the boundary cannot be lossless by itself:
 * the backend clears the React block and the three root aliases on that engine,
 * so the echoed draft carries no binding to switch back to. At the moment of
 * switching *away* from React we therefore snapshot the user's current binding
 * into `reactBindingMemory` (editor state only), and reseed from it when
 * switching back if the draft no longer holds a binding. Nothing is fabricated:
 * the memory is always a value the user had actually bound before the switch.
 */
export function patchEngine(config: AgentConfig, engine: EngineIdentity): AgentConfig {
  const next: AgentConfig = { ...config, engine };
  const bound = currentReactBinding(config);
  if (engine.engine_id === 'codex') {
    if (!next.codex) next.codex = { ...DEFAULT_CODEX };
    // Last moment the bound profile is still in editor state on a draft that
    // will be saved with a CLI engine (and therefore stripped by the server).
    if (bound) next.reactBindingMemory = bound;
  } else {
    const root = next as unknown as Record<string, unknown>;
    const hasReactBinding = !!config.react && config.react.model_profile_id != null && config.react.model_profile_version != null;
    if (!hasReactBinding) {
      // Prefer the live root aliases, then the snapshot taken on the way out.
      // A pre-Phase-3 draft keeps everything in the root aliases; a published
      // Codex draft has those aliases cleared, so its remembered binding is
      // the only lossless source. Either way a bound value is *restored*, never
      // invented, and max_model_rounds keeps the user's last choice.
      const memory = config.reactBindingMemory;
      next.react = {
        model_profile_id: (root.model_profile_id as string | null | undefined) ?? memory?.model_profile_id ?? null,
        model_profile_version: (root.model_profile_version as number | null | undefined) ?? memory?.model_profile_version ?? null,
        max_model_rounds: (root.max_model_rounds as number | undefined)
          ?? memory?.max_model_rounds
          ?? config.react?.max_model_rounds
          ?? DEFAULT_REACT.max_model_rounds,
      };
      // The Chat 模型方案 picker is bound to the legacy root alias, and the
      // CLI-save boundary cleared those aliases. Mirror the restored value back
      // so the picker (and readExecution) see the same canonical value with no
      // alias conflict.
      if (root.model_profile_id == null && next.react.model_profile_id != null) {
        root.model_profile_id = next.react.model_profile_id;
        root.model_profile_version = next.react.model_profile_version;
        root.max_model_rounds = next.react.max_model_rounds;
      }
    }
  }
  return next;
}

/**
 * Canonicalise the execution part of a draft for the engine that is active in
 * it. Called immediately before a save or preview request, never on the editor's
 * own state: the UI may hold both blocks, the wire payload may not.
 *
 * - CLI engine: drop the React block and neutralise the three legacy root
 *   aliases (the normalizer rejects non-default React aliases on a CLI engine).
 *   The Codex version is a required, gate-checked field with no UI control, so
 *   it is injected from the deployment allowlist here (first allowed version =
 *   the deployment default). An empty allowlist injects nothing and stays
 *   fail-closed: no version is ever fabricated.
 * - React engine: drop the Codex block and keep root aliases in step with the
 *   typed React block, so no "取值不一致" conflict can be published. A legacy
 *   draft with no typed block keeps its root aliases exactly as they are — they
 *   are its only source of React settings.
 *
 * `allowedCodexVersions` comes from `GET /agents/execution-config-flags`
 * (`flags.allowed_codex_versions`), which loads asynchronously. Callers pass the
 * latest loaded value so the saved version is always the deployment's current
 * allowlist, not a hardcoded constant or a stale snapshot.
 */
export function normalizeExecutionForEngine(config: AgentConfig, allowedCodexVersions?: readonly string[]): AgentConfig {
  const engineId = config.engine?.engine_id ?? DEFAULT_ENGINE.engine_id;
  const next: AgentConfig = { ...config };
  // `reactBindingMemory` is editor state, not a draft field. The backend rejects
  // unknown keys (extra="forbid"), so it must never reach the wire; the user's
  // binding itself is still restored into the typed block below when React is
  // active, which is what actually gets published.
  delete next.reactBindingMemory;
  const root = next as unknown as Record<string, unknown>;
  if (engineId === 'codex') {
    next.react = undefined;
    root.model_profile_id = null;
    root.model_profile_version = null;
    root.max_model_rounds = DEFAULT_REACT.max_model_rounds;
    if (!next.codex) next.codex = { ...DEFAULT_CODEX };
    // The deployment allowlist is the single source of truth for the version.
    // Replace whatever the draft carried (empty on a new draft, stale on an old
    // one) with the first allowed version. Copy the block rather than mutating
    // it: `next` is only a shallow clone of `config`.
    if (allowedCodexVersions?.length)
      next.codex = { ...next.codex, version: allowedCodexVersions[0] };
    // Issue #166: `credential_ref` is now a validated selection from the
    // credentials library, not a free-text UUID. Preserve it exactly (the server
    // canonicalizes it against the record at publish time) and preserve the
    // ModelGateway profile binding from issue #167. Issue #168: PATH is
    // deployment-owned, so any client value is replaced by the default and the
    // runtime reads AGENT_CODEX_PATH_ENV instead of the published snapshot.
    next.codex = { ...next.codex, path_env: DEFAULT_CODEX.path_env };
  } else {
    next.codex = undefined;
    if (config.react) {
      // Mirror the typed block into the legacy aliases, so the wire can never
      // carry the conflicting pair the backend normalizer rejects.
      const react = config.react;
      next.react = react;
      root.model_profile_id = react.model_profile_id;
      root.model_profile_version = react.model_profile_version;
      root.max_model_rounds = react.max_model_rounds;
    } else {
      // A legacy draft has no typed block: its root aliases ARE the config and
      // must survive untouched (an absent `react` key lets the server rebuild it
      // from them). A `null` block is dropped for the same reason.
      next.react = undefined;
    }
  }
  return next;
}

/** Engines whose publish validation binds a platform Chat model profile. */
export const MODEL_PROFILE_ENGINES: readonly string[] = ['react'];
/** Mirrors the backend D-1 gate: only these engines need a model profile to publish. */
export function engineUsesPlatformModel(config: AgentConfig): boolean {
  return MODEL_PROFILE_ENGINES.includes(config.engine?.engine_id ?? DEFAULT_ENGINE.engine_id);
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
 * The draft is normalised for its active engine first, so a preview can never
 * reject an editor-only round trip between two engine blocks (P7 defect set).
 */
export function previewExecution(agentId: string | null, config: AgentConfig, allowedCodexVersions?: readonly string[]) {
  return post<ExecutionPreview>('/agents/execution-preview', {
    agent_id: agentId,
    config: normalizeExecutionForEngine(config, allowedCodexVersions),
  });
}

/** Non-secret administrative metadata for one execution credential (T-07). */
export interface ExecutionCredentialSummary {
  credential_ref: string;
  tenant_id: string;
  name: string;
  credential_type: string;
  key_version: string;
  version: number;
  status: string;
  allowed_engines: string[];
  allowed_workspaces: string[];
  created_at: string;
  updated_at: string;
  rotated_at: string | null;
  revoked_at: string | null;
}
/**
 * Admin-only read of credential metadata. The endpoint returns
 * `public_metadata()` only: identifiers, name, type, scope and lifecycle — never
 * the secret value, the encrypted blob or the deployment env var that injects
 * it. Used solely to resolve a `credential_ref` into something a human can read.
 */
export function listExecutionCredentials() {
  return api<{ items: ExecutionCredentialSummary[] }>('/execution-credentials');
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
 * One informational Codex version row exposed by the flags endpoint (issue #162).
 * `verified` records whether npm officially confirmed the version; it never
 * grants execution permission — the allowlist is the authoritative gate.
 */
export interface CodexVersionCatalogueEntry {
  version: string;
  source: string;
  verified: boolean;
}
/**
 * Deployment-side Phase 3 switches exposed by GET /agents/execution-config-flags
 * (03-technical-design.md §7.4, R-25) plus the non-sensitive Codex version
 * metadata added in issue #162. The two booleans decide which Phase 3 editing
 * entries to show. `allowed_codex_versions` is the authoritative runtime
 * allowlist (absent/empty = deny-all) and `codex_version_catalogue` is a
 * TTL-cached informational snapshot. Neither grants execution permission:
 * the server remains the authorization boundary. The metadata fields are
 * optional so an older backend response still renders safely (fail-closed).
 */
export interface ExecutionConfigFlags {
  execution_phase3_enabled: boolean;
  execution_orchestrator_enabled: boolean;
  allowed_codex_versions?: string[];
  codex_version_catalogue?: CodexVersionCatalogueEntry[];
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
  application_version: number | null;
  agent_version: number | null;
  skill_key: string | null;
  connection_key: string | null;
  simulation: boolean;
  entry: string | null;
  handler_type: string | null;
  outcome: string | null;
  reason_code: string | null;
  duration_ms: number | null;
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
  application_id: string;
  application_key?: string | null;
  application_name?: string | null;
  application_version: number;
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

// Notification centre: the checklist is a backend-owned snapshot (the browser
// never probes dependencies itself), notifications are state transitions.
export type MonitorStatus = 'pass' | 'warn' | 'fail' | 'not_configured' | 'unknown' | 'stale';
export type MonitorSeverity = 'P0' | 'P1' | 'P2' | 'P3';
export interface MonitorCheck {
  check_id: string;
  type: 'required' | 'conditional' | 'optional';
  status: MonitorStatus;
  severity: MonitorSeverity;
  title: string;
  summary: string;
  evidence: Record<string, string | number | boolean | null>;
  checked_at: string | null;
  first_seen_at: string | null;
  changed_at: string | null;
  stale: boolean;
  action: { label: string; route: string } | null;
}
export interface MonitorCheckGroup { id: string; title: string; status: string; items: MonitorCheck[] }
export interface MonitorChecklist {
  overall_status: 'healthy' | 'degraded' | 'down' | 'unknown';
  generated_at: string;
  scan_age_seconds: number | null;
  counts: Record<MonitorSeverity, number>;
  groups: MonitorCheckGroup[];
}
export interface MonitorNotification {
  id: string;
  check_id: string;
  kind: 'opened' | 'recovered' | 'reminder' | 'unstable';
  severity: MonitorSeverity;
  status: 'active' | 'acknowledged' | 'resolved' | 'suppressed';
  title: string;
  impact: string;
  evidence: Record<string, string | number | boolean | null>;
  source: string;
  action_label: string | null;
  action_route: string | null;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  created_at: string;
  /** Read state is independent of status: reading a live alert never silences it. */
  read_at: string | null;
}
/** Paged feed: the modal needs a total to size its pagination, the bell does not. */
export interface MonitorNotificationPage { items: MonitorNotification[]; total: number }
export interface MonitorNotificationQuery {
  status?: 'active' | 'acknowledged' | 'resolved' | 'suppressed';
  severity?: MonitorSeverity;
  unread?: boolean;
  limit?: number;
  offset?: number;
}
export const getMonitorChecklist = (signal?: AbortSignal) =>
  api<MonitorChecklist>('/notifications/checklist', { signal });
export const getNotificationUnreadCount = (signal?: AbortSignal) =>
  api<{ count: number }>('/notifications/unread-count', { signal });
export const getMonitorNotifications = (query: MonitorNotificationQuery = {}, signal?: AbortSignal) => {
  const params = new URLSearchParams();
  if (query.status) params.set('status', query.status);
  if (query.severity) params.set('severity', query.severity);
  if (query.unread) params.set('unread', 'true');
  params.set('limit', String(query.limit ?? 20));
  params.set('offset', String(query.offset ?? 0));
  return api<MonitorNotificationPage>(`/notifications?${params.toString()}`, { signal });
};
export const markNotificationRead = (id: string) =>
  post<{ id: string; read_at: string }>(`/notifications/${id}/read`);
export const markAllNotificationsRead = () => post<{ updated: number }>('/notifications/read-all');
export const acknowledgeNotification = (id: string) => post<{ id: string; status: string }>(`/notifications/${id}/acknowledge`);

// Phase 6-2 · Execution governance observability (03-technical-design.md §2).
// Every model below is read-only and Secret-free by contract: identifiers,
// bounded reason codes and counts only — never an event payload, a raw parser
// sample, a key or an encrypted/plaintext credential. Request failures are
// surfaced by useResource as a stable error/empty state (fail-closed); nothing
// in this layer fabricates a healthy value or falls back to a Reader view.

/** Common server-side page envelope shared by the governance list endpoints. */
export interface GovernancePage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Tenant/scope attached to a governance row. Some source tables have no
 * `tenant_id` and are joined to `runtime_runs`; an orphaned join yields null,
 * which the UI renders as 部署级. The object form covers a joined
 * business/workspace scope; the string form covers a flattened scope.
 */
export type GovernanceScope = string | null | Record<string, unknown>;

/** SIG-1 · GET /observability/execution/fencing-denials. */
export interface FencingDenialRow {
  run_id: string;
  operation: string;
  reason: string;
  stale_owner: string | null;
  stale_lease_epoch: number | null;
  current_owner: string | null;
  current_lease_epoch: number | null;
  created_at: string;
  tenant_id: string | null;
  scope: GovernanceScope;
  /** Additive backend marker: true iff the run_id had no joined tenant. */
  deployment_level?: boolean;
}

/** SIG-3 · GET /observability/execution/cleanup-failures. */
export interface CleanupFailureRow {
  run_id: string;
  category: 'failed' | 'unconfirmed_cancel' | string;
  cleanup_status: string;
  cleanup_updated_at: string | null;
  cancel_requested_at: string | null;
  cancel_confirmed_at: string | null;
  tenant_id: string | null;
  scope: GovernanceScope;
}

/** SIG-4 · one bounded `last_error` row of GET /observability/execution/outbox. */
export interface OutboxLastError {
  run_id: string;
  seq: number;
  attempts: number;
  available_at: string;
  /** Bounded, redacted delivery error — never an event payload. */
  last_error: string | null;
}
/** SIG-4 · aggregate metrics + paged failure detail. */
export interface OutboxView {
  pending_count: number;
  oldest_available_at: string | null;
  stall_seconds: number | null;
  last_errors: OutboxLastError[];
  published_24h: number;
  total: number;
  page: number;
  page_size: number;
}

/** SIG-5 · GET /observability/execution/replay-gaps. */
export interface ReplayGapRow {
  id: string;
  run_id: string;
  requested_cursor_seq: number;
  retention_floor_seq: number;
  reason_code: string;
  created_at: string;
  tenant_id: string | null;
  scope: GovernanceScope;
}

/** SIG-6 · GET /observability/execution/usage-conflicts. */
export interface UsageConflictRow {
  run_id: string;
  tenant_id: string | null;
  source: string;
  source_event_id: string;
  supersedes_id: string | null;
  /** Usage/cost are display-only aggregates; never a secret or raw sample. */
  usage: unknown;
  cost: unknown;
  is_estimate: boolean | null;
  kind: 'chain' | 'duplicate' | string;
}

/** SIG-7 · GET /observability/execution/parser-diagnostics (counts only, D-class excluded). */
export interface ParserDiagnosticRow {
  bucket_start: string;
  category: string;
  reason_code: string | null;
  count: number;
  tenant_id: string | null;
  run_id: string | null;
}

/** SIG-8 · GET /observability/execution/credential-audit (public audit fields only). */
export interface CredentialAuditRow {
  id: string | number;
  credential_ref: string;
  action: string;
  outcome: string | null;
  reason_code: string | null;
  actor: string | null;
  created_at: string;
  tenant_id: string | null;
}

/** Optional filters shared by the governance list endpoints. */
export interface GovernanceQuery {
  from?: string;
  to?: string;
  run_id?: string;
  reason?: string;
  operation?: string;
  action?: string;
  category?: string;
  kind?: string;
  bucket?: string;
  tenant_id?: string;
  business_scope?: string;
  workspace?: string;
  page?: number;
  page_size?: number;
}

export type GovernanceEndpoint =
  | 'fencing-denials'
  | 'cleanup-failures'
  | 'outbox'
  | 'replay-gaps'
  | 'usage-conflicts'
  | 'parser-diagnostics'
  | 'credential-audit';

const GOVERNANCE_BASE = '/observability/execution';

/**
 * Build a governance endpoint path from typed filters. Used both by the typed
 * loaders below and by `useResource` in the governance panel, so the wire shape
 * has a single source of truth. Empty/undefined filters are omitted.
 */
export function governancePath(endpoint: GovernanceEndpoint, query: GovernanceQuery = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return `${GOVERNANCE_BASE}/${endpoint}${search ? `?${search}` : ''}`;
}

/** SIG-1 · typed loader; the UI calls the same path through `useResource`. */
export const getFencingDenials = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<GovernancePage<FencingDenialRow>>(governancePath('fencing-denials', query), { signal });
/** SIG-3 */
export const getCleanupFailures = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<GovernancePage<CleanupFailureRow>>(governancePath('cleanup-failures', query), { signal });
/** SIG-4 */
export const getOutbox = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<OutboxView>(governancePath('outbox', query), { signal });
/** SIG-5 */
export const getReplayGaps = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<GovernancePage<ReplayGapRow>>(governancePath('replay-gaps', query), { signal });
/** SIG-6 */
export const getUsageConflicts = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<GovernancePage<UsageConflictRow>>(governancePath('usage-conflicts', query), { signal });
/** SIG-7 · counts/redacted reason codes only. */
export const getParserDiagnostics = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<GovernancePage<ParserDiagnosticRow>>(governancePath('parser-diagnostics', query), { signal });
/** SIG-8 · `action` defaults to `revoked`, the audit's focus action. */
export const getCredentialAudit = (query: GovernanceQuery = {}, signal?: AbortSignal) =>
  api<GovernancePage<CredentialAuditRow>>(governancePath('credential-audit', { action: 'revoked', ...query }), { signal });
