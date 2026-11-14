import { api, patch, post, put } from '../../shared/api/client';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationConversation,
    type ApplicationConversationDetail,
    type ApplicationConversationMessage,
    type ApplicationConversationPage,
    type ApplicationConversationRun,
    type ApplicationConversationTurn,
    type ApplicationDetail,
    type ApplicationExperience,
    type ApplicationInput,
    type ApplicationOverview,
    type ApplicationPage,
    type ApplicationPreviewResult,
    type ApplicationReadiness,
    type ApplicationRules,
    type ApplicationSkill,
    type ApplicationSummary,
    type ApplicationTracePage,
    type ApplicationVersion,
    type ApplicationVersionPage,
    type ConnectionInput,
    type ConnectionPage,
    type ConversationAnswerStatus,
    type CredentialInput,
    type ExperienceCategory,
    type ExperienceEntry,
    type ServiceExperienceConfig,
    type SkillInput,
    type SkillPage,
} from './contracts';

type Raw = Record<string, unknown>;
const record = (value: unknown): Raw =>
    value && typeof value === 'object' && !Array.isArray(value) ? value as Raw : {};
const array = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const text = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback;
const number = (value: unknown, fallback = 0) =>
    typeof value === 'number' && Number.isFinite(value) ? value : fallback;
const nullableNumber = (value: unknown) =>
    typeof value === 'number' && Number.isFinite(value) ? value : null;
const boolean = (value: unknown, fallback = false) =>
    typeof value === 'boolean' ? value : fallback;

function pageOf<T>(raw: unknown, normalize: (item: Raw) => T) {
    const value = record(raw);
    return {
        items: array<Raw>(value.items).map(normalize),
        total: number(value.total, array<Raw>(value.items).length),
        page: number(value.page, 1),
        page_size: number(value.page_size, 10),
    };
}

function normalizeAgent(raw: unknown, source: Raw): ApplicationSummary['agent'] {
    const direct = record(raw);
    const agent = Object.keys(direct).length ? direct : record(source.draft);
    const nested = record(agent.agent);
    return {
        id: text(agent.agent_id ?? nested.id ?? agent.id ?? source.agent_id),
        name: text(
            agent.agent_name
            ?? agent.name
            ?? nested.name
            ?? source.agent_name,
            undefined,
        ),
        version: number(agent.agent_version ?? nested.version ?? source.agent_version, 1),
        published_version: nullableNumber(agent.published_version),
    };
}

export function normalizeApplication(raw: unknown): ApplicationSummary {
    const value = record(raw);
    const draft = record(value.draft);
    const config = record(value.config);
    const agent = normalizeAgent(value.agent, { ...draft, agent_id: value.agent_id });
    const skills = array<Raw>(value.skills ?? draft.skills);
    const connections = array<Raw>(value.connections ?? draft.connections);
    const channels = array<Raw>(value.channels ?? draft.channels);
    return {
        id: text(value.id),
        key: text(value.key ?? value.application_key),
        name: text(value.name, text(value.key ?? value.application_key)),
        description: text(value.description, text(config.description ?? draft.description)),
        status: text(value.status, 'draft') as ApplicationSummary['status'],
        origin: text(value.origin, 'user') as ApplicationSummary['origin'],
        immutable: boolean(value.immutable, text(value.origin) === 'example'),
        template_key: text(value.template_key, undefined),
        template_version: text(value.template_version, undefined),
        agent,
        skill_count: number(value.skill_count, skills.length),
        connection_count: number(value.connection_count, connections.length),
        channel_count: number(value.channel_count, channels.length),
        published_version: nullableNumber(value.published_version),
        draft_revision: number(value.draft_revision ?? value.revision, 1),
        revision: number(value.revision ?? value.draft_revision, 1),
        has_unpublished_changes: boolean(value.has_unpublished_changes),
        archived: boolean(value.archived),
        created_at: text(value.created_at, undefined),
        updated_at: text(value.updated_at, undefined),
    };

}

function normalizeSkill(raw: unknown): ApplicationSkill {
    const value = record(raw);
    const config = record(value.config);
    const nestedSafety = record(config.safety ?? value.safety);
    const connection = record(value.connection);
    const test = record(value.last_test ?? value.recent_test);
    return {
        id: text(value.id ?? value.skill_key ?? value.key),
        key: text(value.skill_key ?? value.key ?? value.id),
        name: text(value.name, text(value.skill_key ?? value.key)),
        description: text(value.description),
        type: text(value.type ?? config.type, 'query') as ApplicationSkill['type'],
        enabled: boolean(value.enabled, true),
        connection_id: text(value.connection_id ?? connection.id, undefined),
        connection_key: text(value.connection_key ?? connection.key ?? config.connection_key, undefined),
        connection_name: text(value.connection_name ?? connection.name, undefined),
        revision: number(value.revision, 1),
        parameters: record(value.parameters ?? config.parameters),
        argument_mapping: record(value.argument_mapping ?? config.argument_mapping),
        result_mapping: record(value.result_mapping ?? config.result_mapping),
        result_schema: record(value.result_schema ?? config.result_schema),
        knowledge_base_ids: array<string>(value.knowledge_base_ids ?? config.knowledge_base_ids)
            .filter(item => typeof item === 'string'),
        safety: {
            requires_confirmation: boolean(nestedSafety.requires_confirmation),
            max_amount: nullableNumber(nestedSafety.max_amount),
            allowed_roles: array<string>(nestedSafety.allowed_roles).filter(item => typeof item === 'string'),
            idempotency: text(nestedSafety.idempotency, 'none') as ApplicationSkill['safety']['idempotency'],
            timeout_seconds: number(nestedSafety.timeout_seconds, 10),
            on_error: text(nestedSafety.on_error, 'fail') as ApplicationSkill['safety']['on_error'],
        },
        last_test: Object.keys(test).length ? {
            status: text(test.status, 'untested') as 'passed' | 'failed' | 'untested',
            ran_at: text(test.ran_at, undefined),
            message: text(test.message, undefined),
        } : null,
    };
}

function normalizeConnection(raw: unknown): ConnectionPage['items'][number] {
    const value = record(raw);
    const config = record(value.config);
    return {
        id: text(value.id ?? value.connection_key ?? value.key),
        key: text(value.connection_key ?? value.key ?? value.id),
        name: text(value.name, text(value.connection_key ?? value.key)),
        executor_kind: text(value.executor_kind, 'http') as ConnectionPage['items'][number]['executor_kind'],
        endpoint: text(value.endpoint, undefined),
        method: text(value.method, 'GET') as ConnectionPage['items'][number]['method'],
        public_headers: record(value.public_headers) as Record<string, string>,
        auth_kind: text(value.auth_kind, 'none') as ConnectionPage['items'][number]['auth_kind'],
        credentials_configured: boolean(
            value.credentials_configured,
            boolean(config.credentials_configured),
        ),
        timeout_seconds: number(value.timeout_seconds, 10),
        max_response_bytes: number(value.max_response_bytes, 16000),
        revision: number(value.revision, 1),
        config,
    };
}

function normalizeChannel(raw: unknown): ApplicationDetail['channels'][number] {
    const value = record(raw);
    return {
        id: text(value.id),
        name: text(value.name),
        provider: text(value.provider, 'generic_webhook'),
        enabled: boolean(value.enabled, true),
        application_id: text(value.application_id),
        application_version: number(value.application_version, 1),
        credentials_configured: boolean(value.credentials_configured),
    };
}

function normalizeFallback(value: unknown): ApplicationRules['fallback'] {
    const fallback = text(value, 'handoff').trim().toLowerCase();
    if (fallback === 'reply') return 'fallback';
    if (fallback === 'handoff' || fallback === 'fallback' || fallback === 'fail') {
        return fallback;
    }
    return 'handoff';
}

function normalizeRules(raw: unknown): ApplicationRules {
    const value = record(raw);
    return {
        fallback: normalizeFallback(value.fallback),
        handoff_queue: text(value.handoff_queue),
        handoff_message: text(value.handoff_message),
        require_confirmation: boolean(value.require_confirmation, true),
        preview_write_enabled: boolean(value.preview_write_enabled),
        validate_results: boolean(value.validate_results, true),
    };
}

function normalizeExperienceEntry(raw: unknown): ExperienceEntry {
    const value = record(raw);
    return {
        key: text(value.key),
        label: text(value.label),
        kind: text(value.kind, 'knowledge') as ExperienceEntry['kind'],
        description: text(value.description),
        binding: text(value.binding),
    };
}

function normalizeExperienceCategory(raw: unknown): ExperienceCategory {
    const value = record(raw);
    return {
        key: text(value.key),
        label: text(value.label),
        icon: text(value.icon, 'support') as ExperienceCategory['icon'],
        tone: text(value.tone, 'blue') as ExperienceCategory['tone'],
        entries: array<Raw>(value.entries).map(normalizeExperienceEntry),
    };
}

function normalizeExperience(raw: unknown): ServiceExperienceConfig {
    const value = record(raw);
    const components = record(value.components);
    return {
        schema_version: 'v1',
        welcome_text: text(value.welcome_text, '您好，请问有什么可以帮您？'),
        service_hours: text(value.service_hours, '09:00-21:00'),
        suggestion_sets: array<Raw>(value.suggestion_sets)
            .map(set => array<unknown>(set).filter(
                (item): item is string => typeof item === 'string',
            )),
        categories: array<Raw>(value.categories).map(normalizeExperienceCategory),
        components: {
            quick_menu: boolean(components.quick_menu, true),
            suggestions: boolean(components.suggestions, true),
            order_card: boolean(components.order_card, true),
            form: boolean(components.form, true),
            confirmation: boolean(components.confirmation, true),
            receipt: boolean(components.receipt, true),
            handoff: boolean(components.handoff, true),
        },
    };
}

function normalizeVersion(raw: unknown, current: number | null): ApplicationVersion {
    const value = record(raw);
    return {
        id: text(value.id),
        version: number(value.version, 1),
        source_version: nullableNumber(value.source_version),
        config_digest: text(value.config_digest),
        created_by: text(value.created_by),
        created_at: text(value.created_at),
        current: boolean(value.current, number(value.version) === current),
    };
}

function normalizeReadiness(raw: unknown): ApplicationReadiness {
    const value = record(raw);
    const checks = array<Raw>(value.checks).map(check => ({
        key: text(check.key),
        title: text(check.title),
        detail: text(check.detail),
        status: text(check.status, 'warning') as ApplicationReadiness['status'],
        severity: text(check.severity, 'warning') as ApplicationReadiness['checks'][number]['severity'],
    }));
    return {
        key: text(value.key),
        revision: number(value.revision, 1),
        status: text(value.status, 'warning') as ApplicationReadiness['status'],
        can_publish: boolean(value.can_publish),
        checks,
        counts: {
            pass: number(record(value.counts).pass),
            warning: number(record(value.counts).warning),
            blocked: number(record(value.counts).blocked),
        },
    };
}

function normalizeConversation(raw: unknown): ApplicationConversation {
    const value = record(raw);
    const kind = text(value.kind);
    return {
        id: text(value.id),
        question: text(value.question),
        answer: text(value.answer),
        status: text(value.status, 'unknown') as ConversationAnswerStatus,
        mode: text(value.mode, 'bot'),
        source: text(value.source, 'unknown'),
        kind: kind as ApplicationConversation['kind'],
        channel_id: text(value.channel_id),
        channel_name: text(value.channel_name),
        account: text(value.account),
        user_name: text(value.user_name) || null,
        conversation_title: text(value.conversation_title),
        message_count: number(value.message_count),
        turn_count: value.turn_count === undefined ? undefined : number(value.turn_count),
        last_turn_status: value.last_turn_status === undefined
            ? undefined
            : text(value.last_turn_status) || null,
        run_id: text(value.run_id) || null,
        application_version: nullableNumber(value.application_version),
        agent_version: nullableNumber(value.agent_version),
        created_at: text(value.created_at) || null,
        updated_at: text(value.updated_at) || null,
        feedback_type: text(value.feedback_type) || null,
        feedback_status: text(value.feedback_status, 'none'),
        qa_saved: boolean(value.qa_saved),
    };
}

function normalizeConversationMessage(raw: unknown): ApplicationConversationMessage {
    const value = record(raw);
    return {
        id: text(value.id),
        seq: number(value.seq),
        role: text(value.role, 'system'),
        content: text(value.content),
        content_type: text(value.content_type, 'text'),
        payload: value.payload,
        runtime_message_id: text(value.runtime_message_id) || null,
        run_id: text(value.run_id) || null,
        created_at: text(value.created_at) || null,
    };
}

function normalizeConversationTurn(raw: unknown): ApplicationConversationTurn {
    const value = record(raw);
    return {
        id: text(value.id),
        status: text(value.status, 'unknown'),
        customer_message_id: text(value.customer_message_id) || null,
        assistant_message_id: text(value.assistant_message_id) || null,
        runtime_conversation_id: text(value.runtime_conversation_id) || null,
        runtime_run_id: text(value.runtime_run_id) || null,
        application_version: nullableNumber(value.application_version),
        agent_version: nullableNumber(value.agent_version),
        error_code: text(value.error_code) || null,
        created_at: text(value.created_at) || null,
        finished_at: text(value.finished_at) || null,
    };
}

function normalizeConversationRun(raw: unknown): ApplicationConversationRun {
    const value = record(raw);
    return {
        id: text(value.id),
        status: text(value.status, 'unknown'),
        output: text(value.output) || null,
        error_code: text(value.error_code) || null,
        cancel_requested: boolean(value.cancel_requested),
        created_at: text(value.created_at) || null,
        started_at: text(value.started_at) || null,
        finished_at: text(value.finished_at) || null,
    };
}

function normalizeConversationDetail(raw: unknown): ApplicationConversationDetail {
    const value = record(raw);
    return {
        ...normalizeConversation(value),
        messages: array<Raw>(value.messages).map(normalizeConversationMessage),
        turns: array<Raw>(value.turns).map(normalizeConversationTurn),
        runs: array<Raw>(value.runs).map(normalizeConversationRun),
        messages_truncated: boolean(value.messages_truncated),
    };
}

function queryString(params: Record<string, string | number | boolean | undefined>) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== '') search.set(key, String(value));
    }
    const suffix = search.toString();
    return suffix ? `?${suffix}` : '';
}

export async function listApplications(params: {
    page: number;
    pageSize: number;
    origin?: 'user' | 'example';
    status?: 'draft' | 'review' | 'published' | 'offline';
    query?: string;
    archived?: boolean;
}) {
    const raw = await api<Raw>(
        `/service-apps${queryString({
            page: params.page,
            page_size: params.pageSize,
            origin: params.origin,
            status: params.status,
            q: params.query,
            archived: params.archived,
        })}`,
    );
    return pageOf(raw, normalizeApplication) as ApplicationPage;
}

export async function getApplicationOverview(
    origin?: 'user' | 'example',
): Promise<ApplicationOverview> {
    const raw = record(await api<Raw>(
        `/service-apps/overview${queryString({ origin })}`,
    ));
    const statuses = record(raw.by_status);
    return {
        applications: number(raw.applications),
        by_status: {
            draft: number(statuses.draft),
            review: number(statuses.review),
            published: number(statuses.published),
            offline: number(statuses.offline),
        },
        examples: number(raw.examples),
        published: number(raw.published),
        skills: number(raw.skills),
        connections: number(raw.connections),
        traces: number(raw.traces),
    };
}

export async function getApplication(key: string): Promise<ApplicationDetail> {
    const raw = record(await api<Raw>(`/service-apps/${encodeURIComponent(key)}`));
    const summary = normalizeApplication(raw);
    const connections = array<Raw>(raw.connections ?? record(raw.draft).connections)
        .map(normalizeConnection);
    return {
        ...summary,
        skills: array<Raw>(raw.skills ?? record(raw.draft).skills).map(normalizeSkill),
        connections,
        rules: normalizeRules(raw.rules ?? record(raw.draft).rules),
        channels: array<Raw>(raw.channels ?? record(raw.draft).channels)
            .map(normalizeChannel),
        credential_health: {
            configured: connections.filter(item => item.credentials_configured).length,
            missing: connections.filter(item => item.auth_kind !== 'none' && !item.credentials_configured).length,
        },
    };
}

export async function createApplication(input: ApplicationInput) {
    return normalizeApplication(await post<Raw>('/service-apps', input));
}

export async function updateApplication(
    key: string,
    input: Partial<ApplicationInput> & {
        revision: number;
        rules?: Partial<ApplicationRules>;
    },
) {
    return normalizeApplication(await put<Raw>(
        `/service-apps/${encodeURIComponent(key)}`,
        input,
    ));
}

export async function copyApplication(key: string, input: { key: string; name: string }) {
    return normalizeApplication(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/copy`,
        input,
    ));
}

export async function listSkills(key: string, page: number, pageSize: number, query = '') {
    const raw = await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/skills${queryString({
            page,
            page_size: pageSize,
            q: query,
        })}`,
    );
    return pageOf(raw, normalizeSkill) as SkillPage;
}

export async function createSkill(key: string, input: SkillInput) {
    return normalizeSkill(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/skills`,
        input,
    ));
}

export async function updateSkill(
    key: string,
    skillKey: string,
    input: SkillInput,
    revision: number,
) {
    return normalizeSkill(await put<Raw>(
        `/service-apps/${encodeURIComponent(key)}/skills/${encodeURIComponent(skillKey)}`,
        { ...input, revision },
    ));
}

export async function toggleSkill(
    key: string,
    skillKey: string,
    enabled: boolean,
    revision: number,
) {
    return normalizeSkill(await patch<Raw>(
        `/service-apps/${encodeURIComponent(key)}/skills/${encodeURIComponent(skillKey)}`,
        { enabled, revision },
    ));
}

export async function deleteSkill(key: string, skillKey: string, revision: number) {
    return api<{ deleted: boolean }>(
        `/service-apps/${encodeURIComponent(key)}/skills/${encodeURIComponent(skillKey)}?revision=${revision}`,
        { method: 'DELETE' },
    );
}

export async function testSkill(key: string, skillKey: string) {
    return api<{ status: string; message?: string; duration_ms?: number }>(
        `/service-apps/${encodeURIComponent(key)}/skills/${encodeURIComponent(skillKey)}/test`,
        { method: 'POST' },
    );
}

export async function listConnections(key: string, page = 1, pageSize = DEFAULT_PAGE_SIZE) {
    const raw = await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/connections${queryString({
            page,
            page_size: pageSize,
        })}`,
    );
    return pageOf(raw, normalizeConnection) as ConnectionPage;
}

export async function createConnection(key: string, input: ConnectionInput) {
    const raw = await post<Raw>(`/service-apps/${encodeURIComponent(key)}/connections`, input);
    return {
        connection: normalizeConnection(raw),
        id: text(record(raw).id),
    };
}

export async function updateConnection(
    key: string,
    connectionKey: string,
    input: ConnectionInput,
    revision: number,
) {
    return normalizeConnection(await put<Raw>(
        `/service-apps/${encodeURIComponent(key)}/connections/${encodeURIComponent(connectionKey)}`,
        { ...input, revision },
    ));
}

export async function saveCredentials(
    key: string,
    connectionKey: string,
    credentials: CredentialInput,
) {
    return api<{ credentials_configured: boolean }>(
        `/service-apps/${encodeURIComponent(key)}/connections/${encodeURIComponent(connectionKey)}/credentials`,
        {
            method: 'PUT',
            body: JSON.stringify({ credentials }),
        },
    );
}

export async function testConnection(key: string, connectionKey: string) {
    return api<{
        status: string;
        message?: string;
        duration_ms?: number;
        credentials_configured?: boolean;
    }>(
        `/service-apps/${encodeURIComponent(key)}/connections/${encodeURIComponent(connectionKey)}/test`,
        { method: 'POST' },
    );
}

export async function deleteConnection(key: string, connectionKey: string, revision: number) {
    return api<{ deleted: boolean }>(
        `/service-apps/${encodeURIComponent(key)}/connections/${encodeURIComponent(connectionKey)}?revision=${revision}`,
        { method: 'DELETE' },
    );
}

export async function getApplicationReadiness(key: string) {
    return normalizeReadiness(await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/readiness`,
    ));
}

export async function getApplicationExperience(
    key: string,
    version?: number | null,
): Promise<ApplicationExperience> {
    const raw = record(await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/experience${queryString({
            version: version ?? undefined,
        })}`,
    ));
    return {
        experience: normalizeExperience(raw.experience),
        revision: number(raw.revision, 1),
        immutable: boolean(raw.immutable),
        version: nullableNumber(raw.version),
    };
}

export async function updateApplicationExperience(
    key: string,
    experience: ServiceExperienceConfig,
    revision: number,
): Promise<ApplicationExperience> {
    const raw = record(await put<Raw>(
        `/service-apps/${encodeURIComponent(key)}/experience`,
        { experience, revision },
    ));
    return {
        experience: normalizeExperience(raw.experience),
        revision: number(raw.revision, revision + 1),
        immutable: boolean(raw.immutable),
    };
}

export async function publishApplication(key: string, revision: number) {
    return normalizeApplication(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/publish`,
        { revision },
    ));
}

export async function setApplicationStatus(
    key: string,
    status: 'draft' | 'review' | 'offline',
    revision: number,
) {
    return normalizeApplication(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/status`,
        { status, revision },
    ));
}

export async function archiveApplication(key: string, revision: number) {
    return normalizeApplication(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/archive`,
        { revision },
    ));
}

export async function restoreApplication(key: string, revision?: number) {
    return normalizeApplication(await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/restore`,
        {
            method: 'POST',
            ...(revision === undefined ? {} : { body: JSON.stringify({ revision }) }),
        },
    ));
}

export async function purgeApplication(key: string) {
    return api<{ key: string; deleted: boolean }>(
        `/service-apps/${encodeURIComponent(key)}`,
        { method: 'DELETE' },
    );
}

export async function rollbackApplication(key: string, version: number, revision: number) {
    return normalizeApplication(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/rollback`,
        { version, revision },
    ));
}

export async function listVersions(key: string, page: number, pageSize: number) {
    const raw = await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/versions${queryString({
            page,
            page_size: pageSize,
        })}`,
    );
    const value = record(raw);
    return {
        items: array<Raw>(value.items).map(item => normalizeVersion(item, nullableNumber(value.published_version))),
        total: number(value.total, array<Raw>(value.items).length),
        page: number(value.page, page),
        page_size: number(value.page_size, pageSize),
    } as ApplicationVersionPage;
}

export async function listTraces(key: string, page = 1, pageSize = 5) {
    const raw = await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/traces${queryString({
            page,
            page_size: pageSize,
        })}`,
    );
    const value = record(raw);
    return {
        items: array<Raw>(value.items).map(item => ({
            id: text(item.id),
            application_version: number(item.application_version),
            agent_version: number(item.agent_version),
            skill_key: text(item.skill_key, undefined),
            connection_key: text(item.connection_key, undefined),
            outcome: text(item.outcome),
            reason_code: text(item.reason_code, undefined),
            duration_ms: nullableNumber(item.duration_ms),
            created_at: text(item.created_at),
        })),
        total: number(value.total, array<Raw>(value.items).length),
        page: number(value.page, page),
        page_size: number(value.page_size, pageSize),
    } as ApplicationTracePage;
}

export async function listApplicationConversations(
    key: string,
    params: {
        page: number;
        pageSize: number;
        query?: string;
        channelId?: string;
        status?: ConversationAnswerStatus | 'all';
    },
): Promise<ApplicationConversationPage> {
    const raw = await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/conversations${queryString({
            page: params.page,
            page_size: params.pageSize,
            q: params.query,
            channel_id: params.channelId,
            status: params.status,
        })}`,
    );
    const value = record(raw);
    const page = pageOf(raw, normalizeConversation);
    return {
        ...page,
        total_pages: value.total_pages === undefined
            ? Math.max(1, Math.ceil(page.total / Math.max(1, page.page_size)))
            : number(value.total_pages),
    } as ApplicationConversationPage;
}

export async function getApplicationConversation(
    key: string,
    conversationId: string,
): Promise<ApplicationConversationDetail> {
    return normalizeConversationDetail(await api<Raw>(
        `/service-apps/${encodeURIComponent(key)}/conversations/${encodeURIComponent(conversationId)}`,
    ));
}

export async function previewApplication(
    key: string,
    input: {
        message: string;
        skill_key?: string | null;
        version?: number | null;
        allow_write?: boolean;
    },
) {
    const raw = record(await post<Raw>(
        `/service-apps/${encodeURIComponent(key)}/preview`,
        input,
    ));
    return {
        status: text(raw.status, 'completed'),
        reply: text(raw.reply ?? raw.message ?? raw.content),
        application_version: nullableNumber(raw.application_version),
        draft: boolean(raw.draft, input.version == null),
        skills: array<Raw>(raw.skills).map(item => ({
            key: text(item.key),
            status: text(item.status),
            duration_ms: nullableNumber(item.duration_ms),
        })),
        trace: record(raw.trace),
    } as ApplicationPreviewResult;
}

export async function listApplicationChannels(applicationId: string) {
    const raw = await api<Raw[] | Raw>(
        `/channels${queryString({ application_id: applicationId, page_size: 100 })}`,
    );
    const items = Array.isArray(raw) ? raw : array<Raw>(record(raw).items);
    return items.map(normalizeChannel);
}

export async function switchChannelVersion(channelId: string, applicationVersion: number) {
    return api<Raw>(
        `/channels/${encodeURIComponent(channelId)}/application-version`,
        {
            method: 'PUT',
            body: JSON.stringify({ application_version: applicationVersion }),
        },
    );
}
