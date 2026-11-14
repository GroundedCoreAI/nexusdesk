export type ApplicationStatus = 'draft' | 'review' | 'published' | 'offline';
export type ApplicationOrigin = 'user' | 'example';
export type ApplicationTabKey =
    | 'overview'
    | 'agent'
    | 'experience'
    | 'skills'
    | 'rules'
    | 'conversations'
    | 'release';

export type SkillType = 'knowledge' | 'query' | 'action' | 'handoff';
export type ConnectionExecutorKind = 'http' | 'internal' | 'human_queue';
export type ConnectionMethod = 'GET' | 'POST';
export type ConnectionAuthKind = 'none' | 'bearer' | 'api_key' | 'custom';
export type ReadinessStatus = 'pass' | 'warning' | 'blocked';
export type ReadinessSeverity = 'blocking' | 'warning' | 'info';

export interface ApplicationAgent {
    id: string;
    name?: string;
    version: number;
    published_version?: number | null;
}

export interface SkillSafety {
    requires_confirmation: boolean;
    max_amount: number | null;
    allowed_roles: string[];
    idempotency: 'none' | 'required' | 'optional';
    timeout_seconds: number;
    on_error: 'fail' | 'handoff';
}

export interface ApplicationSkill {
    id: string;
    key: string;
    name: string;
    description: string;
    type: SkillType;
    enabled: boolean;
    connection_id: string | null;
    connection_key: string | null;
    connection_name: string | null;
    revision: number;
    parameters: Record<string, unknown>;
    argument_mapping: Record<string, unknown>;
    result_mapping: Record<string, unknown>;
    result_schema: Record<string, unknown>;
    // Bases this skill searches. Empty means it inherits the Agent's list.
    knowledge_base_ids: string[];
    safety: SkillSafety;
    last_test?: {
        status: 'passed' | 'failed' | 'untested';
        ran_at?: string | null;
        message?: string | null;
    } | null;
}

export interface ApplicationConnection {
    id: string;
    key: string;
    name: string;
    executor_kind: ConnectionExecutorKind;
    endpoint: string | null;
    method: ConnectionMethod;
    public_headers: Record<string, string>;
    auth_kind: ConnectionAuthKind;
    credentials_configured: boolean;
    timeout_seconds: number;
    max_response_bytes: number;
    revision: number;
    config: Record<string, unknown>;
}

export interface ApplicationRules {
    fallback: 'handoff' | 'fallback' | 'fail';
    handoff_queue: string;
    handoff_message: string;
    require_confirmation: boolean;
    preview_write_enabled: boolean;
    validate_results: boolean;
}

export type ExperienceEntryKind = 'query' | 'action' | 'knowledge' | 'handoff';
export type ExperienceCategoryIcon = 'member' | 'order' | 'account' | 'support';
export type ExperienceCategoryTone = 'violet' | 'blue' | 'green' | 'amber';

export interface ExperienceEntry {
    key: string;
    label: string;
    kind: ExperienceEntryKind;
    description: string;
    binding: string;
}

export interface ExperienceCategory {
    key: string;
    label: string;
    icon: ExperienceCategoryIcon;
    tone: ExperienceCategoryTone;
    entries: ExperienceEntry[];
}

export interface ExperienceComponents {
    quick_menu: boolean;
    suggestions: boolean;
    order_card: boolean;
    form: boolean;
    confirmation: boolean;
    receipt: boolean;
    handoff: boolean;
}

export interface ServiceExperienceConfig {
    schema_version: 'v1';
    welcome_text: string;
    service_hours: string;
    suggestion_sets: string[][];
    categories: ExperienceCategory[];
    components: ExperienceComponents;
}

export interface ApplicationExperience {
    experience: ServiceExperienceConfig;
    revision: number;
    immutable: boolean;
    version?: number | null;
}

export interface ApplicationChannelBinding {
    id: string;
    name: string;
    provider: string;
    enabled: boolean;
    application_id: string;
    application_version: number;
    credentials_configured: boolean;
}

export interface ApplicationTrace {
    id: string;
    application_version: number;
    agent_version: number;
    skill_key: string | null;
    connection_key: string | null;
    outcome: string;
    reason_code: string | null;
    duration_ms: number | null;
    created_at: string;
}

export interface ApplicationSummary {
    id: string;
    key: string;
    name: string;
    description: string;
    status: ApplicationStatus;
    origin: ApplicationOrigin;
    immutable: boolean;
    template_key: string | null;
    template_version: string | null;
    agent: ApplicationAgent;
    skill_count: number;
    connection_count: number;
    channel_count: number;
    published_version: number | null;
    draft_revision: number;
    revision: number;
    has_unpublished_changes: boolean;
    archived: boolean;
    created_at: string | null;
    updated_at: string | null;
}

export interface ApplicationDetail extends ApplicationSummary {
    skills: ApplicationSkill[];
    connections: ApplicationConnection[];
    rules: ApplicationRules;
    channels: ApplicationChannelBinding[];
    credential_health: {
        configured: number;
        missing: number;
    };
}

export interface ApplicationPage {
    items: ApplicationSummary[];
    total: number;
    page: number;
    page_size: number;
}

export interface ApplicationOverview {
    applications: number;
    by_status: Record<ApplicationStatus, number>;
    examples: number;
    published: number;
    skills: number;
    connections: number;
    traces: number;
}

export interface SkillPage {
    items: ApplicationSkill[];
    total: number;
    page: number;
    page_size: number;
}

export interface ConnectionPage {
    items: ApplicationConnection[];
    total: number;
    page: number;
    page_size: number;
}

export interface ApplicationVersion {
    id: string;
    version: number;
    source_version: number | null;
    config_digest: string;
    created_by: string;
    created_at: string;
    current: boolean;
}

export interface ApplicationVersionPage {
    items: ApplicationVersion[];
    total: number;
    page: number;
    page_size: number;
}

export interface ReadinessCheck {
    key: string;
    title: string;
    detail: string;
    status: ReadinessStatus;
    severity: ReadinessSeverity;
}

export interface ApplicationReadiness {
    key: string;
    revision: number;
    status: ReadinessStatus;
    can_publish: boolean;
    checks: ReadinessCheck[];
    counts: Record<ReadinessStatus, number>;
}

export interface ApplicationTracePage {
    items: ApplicationTrace[];
    total: number;
    page: number;
    page_size: number;
}

export type ConversationAnswerStatus =
    | 'completed'
    | 'failed'
    | 'queued'
    | 'running'
    | 'cancelled'
    | 'bot'
    | 'waiting'
    | 'human'
    | 'closed'
    | 'unknown';

export type ServiceConversationKind = 'customer' | 'debug' | 'playground';

export interface ApplicationConversation {
    id: string;
    question: string;
    answer: string;
    status: ConversationAnswerStatus;
    mode: string;
    source: string;
    kind: ServiceConversationKind;
    channel_id: string;
    channel_name: string;
    account: string;
    user_name: string | null;
    conversation_title: string;
    message_count: number;
    turn_count?: number;
    last_turn_status?: string | null;
    run_id: string | null;
    application_version: number | null;
    agent_version: number | null;
    created_at: string | null;
    updated_at: string | null;
    feedback_type: string | null;
    feedback_status: string;
    qa_saved: boolean;
}

export interface ApplicationConversationMessage {
    id: string;
    seq: number;
    role: string;
    content: string;
    content_type: string;
    payload: unknown;
    runtime_message_id: string | null;
    /** Legacy runtime-message field retained for backward compatibility. */
    run_id: string | null;
    created_at: string | null;
}

export interface ApplicationConversationTurn {
    id: string;
    status: string;
    customer_message_id: string | null;
    assistant_message_id: string | null;
    runtime_conversation_id: string | null;
    runtime_run_id: string | null;
    application_version: number | null;
    agent_version: number | null;
    error_code: string | null;
    created_at: string | null;
    finished_at: string | null;
}

export interface ApplicationConversationRun {
    id: string;
    status: string;
    output: string | null;
    error_code: string | null;
    cancel_requested: boolean;
    created_at: string | null;
    started_at: string | null;
    finished_at: string | null;
}

export interface ApplicationConversationDetail extends ApplicationConversation {
    messages: ApplicationConversationMessage[];
    turns: ApplicationConversationTurn[];
    runs: ApplicationConversationRun[];
    messages_truncated?: boolean;
}

export interface ApplicationConversationPage {
    items: ApplicationConversation[];
    total: number;
    page: number;
    page_size: number;
    total_pages?: number;
}

export interface ApplicationPreviewResult {
    status: string;
    reply: string;
    application_version: number | null;
    draft: boolean;
    skills: Array<{
        key: string;
        status: string;
        duration_ms?: number | null;
    }>;
    trace?: Record<string, unknown>;
}

export interface ApplicationInput {
    key: string;
    name: string;
    description: string;
    agent_id: string;
    agent_version: number;
}

export interface SkillInput {
    key: string;
    name: string;
    description: string;
    type: SkillType;
    enabled: boolean;
    connection_id: string | null;
    parameters: Record<string, unknown>;
    argument_mapping: Record<string, unknown>;
    result_mapping: Record<string, unknown>;
    result_schema: Record<string, unknown>;
    knowledge_base_ids?: string[];
    safety: SkillSafety;
}

export interface ConnectionInput {
    key: string;
    name: string;
    executor_kind: ConnectionExecutorKind;
    endpoint: string | null;
    method: ConnectionMethod;
    public_headers: Record<string, string>;
    auth_kind: ConnectionAuthKind;
    timeout_seconds: number;
    max_response_bytes: number;
    config: Record<string, unknown>;
}

export type CredentialInput =
    | { type: 'bearer'; token: string }
    | { type: 'api_key'; header_name: string; token: string }
    | { type: 'custom'; headers: Record<string, string> }
    | { type: 'none' };

export const DEFAULT_PAGE_SIZE = 10;
