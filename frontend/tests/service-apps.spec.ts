import { expect, test, type Page } from '@playwright/test';

const agent = {
    id: 'agent-1',
    name: '购物消费助手',
    description: '处理购物、订单、物流与售后问题',
    draft: {
        system_prompt: 'test',
        tool_names: ['knowledge_search'],
        knowledge_base_ids: [],
        max_model_rounds: 6,
        model_profile_id: 'profile-1',
        model_profile_version: 1,
    },
    draft_revision: 3,
    published_version: 2,
    archived: false,
    updated_at: '2026-11-01T02:00:00Z',
};

const application = {
    id: 'app-1',
    key: 'consumer-service',
    name: '购物消费服务应用',
    description: '处理订单、物流和售后问题',
    status: 'published',
    origin: 'user',
    immutable: false,
    template_key: null,
    template_version: null,
    agent: {
        id: agent.id,
        name: agent.name,
        version: 2,
        published_version: 2,
    },
    skill_count: 1,
    connection_count: 1,
    channel_count: 1,
    published_version: 2,
    draft_revision: 3,
    revision: 3,
    has_unpublished_changes: false,
    archived: false,
    created_at: '2026-11-01T01:00:00Z',
    updated_at: '2026-11-01T02:00:00Z',
};

const exampleApplication = {
    ...application,
    id: 'app-example',
    key: 'example-order-service',
    name: '标准订单服务',
    origin: 'example',
    immutable: true,
    template_key: 'order-service',
    template_version: '1',
};

const archivedApplication = {
    ...application,
    id: 'app-archived',
    key: 'archived-service',
    name: '已归档服务应用',
    description: '用于验证恢复与彻底删除',
    status: 'offline',
    archived: true,
    published_version: null,
};

const overview = {
    applications: 1,
    by_status: {
        draft: 0,
        review: 0,
        published: 1,
        offline: 0,
    },
    examples: 1,
    published: 1,
    skills: 1,
    connections: 1,
    traces: 1,
};

const skill = {
    id: 'skill-1',
    key: 'order_lookup',
    name: '订单查询',
    description: '按订单号查询状态',
    type: 'query',
    enabled: true,
    connection_id: 'connection-1',
    connection_key: 'order-api',
    connection_name: '订单服务',
    revision: 1,
    parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
            order_id: { type: 'string' },
        },
    },
    argument_mapping: {},
    result_mapping: {},
    result_schema: {},
    safety: {
        requires_confirmation: false,
        max_amount: null,
        allowed_roles: [],
        idempotency: 'none',
        timeout_seconds: 10,
        on_error: 'fail',
    },
    last_test: {
        status: 'passed',
        ran_at: '2026-11-01T02:00:00Z',
        message: null,
    },
};

const connection = {
    id: 'connection-1',
    key: 'order-api',
    name: '订单服务',
    executor_kind: 'http',
    endpoint: 'https://orders.example.test',
    method: 'POST',
    public_headers: {},
    auth_kind: 'bearer',
    credentials_configured: true,
    timeout_seconds: 10,
    max_response_bytes: 16000,
    revision: 1,
    config: {},
};

const channel = {
    id: 'channel-1',
    name: '官网帮助中心',
    provider: 'generic_webhook',
    enabled: true,
    application_id: application.id,
    application_version: 2,
    credentials_configured: true,
};

const detail = {
    ...application,
    skills: [skill],
    connections: [connection],
    rules: {
        fallback: 'handoff',
        handoff_queue: 'customer-service',
        handoff_message: '正在为您转接人工客服。',
        require_confirmation: true,
        preview_write_enabled: false,
        validate_results: true,
    },
    channels: [channel],
    credential_health: {
        configured: 1,
        missing: 0,
    },
};

const experience = {
    experience: {
        schema_version: 'v1',
        welcome_text: '您好，我是购物消费服务助手，请问有什么可以帮您？',
        service_hours: '09:00-21:00',
        suggestion_sets: [
            ['查询订单', '申请退款', '转接人工'],
            ['物流进度', '修改地址', '发票问题'],
        ],
        categories: [
            {
                key: 'orders',
                label: '订单服务',
                icon: 'order',
                tone: 'blue',
                entries: [
                    {
                        key: 'order_lookup',
                        label: '查询订单',
                        kind: 'query',
                        description: '按订单号查询订单与物流状态',
                        binding: 'order_lookup',
                    },
                ],
            },
        ],
        components: {
            quick_menu: true,
            suggestions: true,
            order_card: true,
            form: true,
            confirmation: true,
            receipt: true,
            handoff: true,
        },
    },
    revision: application.draft_revision,
    immutable: application.immutable,
};

const conversations = Array.from({ length: 12 }, (_, index) => ({
    id: `conversation-${index + 1}`,
    question: index === 0 ? '请帮我查询订单' : `测试客户问题 ${index + 1}`,
    answer: index === 0 ? '已为您查询到订单，当前正在配送中。' : `测试应用回答 ${index + 1}`,
    status: index === 0 ? 'completed' : 'failed',
    kind: 'customer',
    mode: 'bot',
    source: 'generic_webhook',
    channel_id: channel.id,
    channel_name: channel.name,
    account: `customer-${index + 1}`,
    user_name: index === 0 ? '张小明' : null,
    conversation_title: index === 0 ? '订单配送进度咨询' : `客户会话 ${index + 1}`,
    message_count: index === 0 ? 4 : 2,
    turn_count: index === 0 ? 2 : 1,
    last_turn_status: index === 0 ? 'completed' : 'failed',
    run_id: `run-${index + 1}`,
    application_version: 2,
    agent_version: 2,
    created_at: '2026-11-01T01:50:00Z',
    updated_at: '2026-11-01T02:00:00Z',
    feedback_type: null,
    feedback_status: 'none',
    qa_saved: false,
}));

const nonCustomerConversations = [
    {
        ...conversations[0],
        id: 'debug-conversation',
        kind: 'debug',
        question: '客户界面调试会话不应出现',
        conversation_title: '调试会话',
        channel_id: '',
        channel_name: '',
    },
    {
        ...conversations[1],
        id: 'playground-conversation',
        kind: 'playground',
        question: 'Playground 会话不应出现',
        conversation_title: 'Playground 会话',
        channel_id: '',
        channel_name: '',
    },
];

async function mockConsole(
    page: Page,
    requests: string[] = [],
    options: {
        rules?: unknown;
        readiness?: unknown;
        role?: string;
        conversationList?: {
            delayMs?: number;
            error?: string;
            injectNonCustomer?: boolean;
        };
    } = {},
) {
    let publishedVersion = application.published_version;
    let draftRevision = application.draft_revision;
    let applicationStatus = application.status;
    let applicationRevision = application.draft_revision;
    let applicationArchived = false;
    let purged = false;
    await page.route('**/api/v1/**', async route => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname.replace('/api/v1', '');
        requests.push(`${request.method()} ${path}${url.search}`);

        if (path === '/me') {
            return route.fulfill({
                json: {
                    role: options.role || 'admin',
                    tenant: '演示企业',
                    actor: 'admin',
                    permissions: [],
                },
            });
        }
        if (path === '/extensions/ui') return route.fulfill({ json: [] });
        if (path === '/extensions/capabilities') {
            return route.fulfill({ json: { capabilities: { items: [] } } });
        }
        if (path === '/modules' || path === '/tools' || path === '/knowledge-bases') {
            return route.fulfill({ json: [] });
        }
        if (path === '/observability/summary') return route.fulfill({ json: {} });
        if (path === '/deployment') {
            return route.fulfill({ json: { quickstart: false } });
        }
        if (path === '/agents') return route.fulfill({ json: [agent] });
        if (path === '/agents/catalog') {
            return route.fulfill({
                json: { items: [agent], total: 1, page: 1, page_size: 12 },
            });
        }
        if (path === '/agents/agent-1') return route.fulfill({ json: agent });
        if (path === '/agents/agent-1/evaluation-reports') {
            return route.fulfill({
                json: { items: [], total: 0, page: 1, page_size: 1 },
            });
        }
        if (path === '/agents/agent-1/versions') return route.fulfill({ json: [] });
        if (path === '/agents/agent-1/diff') {
            return route.fulfill({ json: { changes: [] } });
        }
        if (path === '/service-apps/overview' && request.method() === 'GET') {
            return route.fulfill({
                json: url.searchParams.get('origin') === 'example'
                    ? { ...overview, applications: 1, examples: 1 }
                    : overview,
            });
        }
        if (path === '/service-apps' && request.method() === 'GET') {
            const origin = url.searchParams.get('origin');
            const archivedQuery = url.searchParams.get('archived') === 'true';
            const items = archivedQuery
                ? (purged ? [] : [archivedApplication])
                : origin === 'user'
                    ? (applicationArchived ? [] : [{
                        ...application,
                        status: applicationStatus,
                        revision: applicationRevision,
                        draft_revision: applicationRevision,
                    }])
                    : origin === 'example'
                        ? [exampleApplication]
                        : [application, exampleApplication];
            return route.fulfill({
                json: {
                    items,
                    total: items.length,
                    page: 1,
                    page_size: 10,
                    total_pages: 1,
                },
            });
        }
        if (path === '/service-apps/consumer-service/archive' && request.method() === 'POST') {
            expect(request.postDataJSON()).toEqual({ revision: applicationRevision });
            applicationArchived = true;
            return route.fulfill({
                json: { ...application, archived: true, status: 'offline' },
            });
        }
        if (path === '/service-apps/archived-service/restore' && request.method() === 'POST') {
            return route.fulfill({
                json: { ...archivedApplication, archived: false },
            });
        }
        if (path === '/service-apps/archived-service' && request.method() === 'DELETE') {
            purged = true;
            return route.fulfill({ json: { key: 'archived-service', deleted: true } });
        }
        if (path === '/service-apps/consumer-service/status' && request.method() === 'POST') {
            expect(request.postDataJSON()).toEqual({
                status: 'offline',
                revision: applicationRevision,
            });
            applicationStatus = 'offline';
            applicationRevision += 1;
            return route.fulfill({
                json: {
                    ...application,
                    status: applicationStatus,
                    draft_revision: applicationRevision,
                    revision: applicationRevision,
                },
            });
        }
        if (path === '/service-apps/consumer-service' && request.method() === 'GET') {
            return route.fulfill({
                json: options.rules === undefined
                    ? detail
                    : { ...detail, rules: options.rules },
            });
        }
        if (path === '/service-apps/example-order-service' && request.method() === 'GET') {
            return route.fulfill({
                json: { ...detail, ...exampleApplication },
            });
        }
        if (path === '/service-apps/consumer-service/experience') {
            const version = url.searchParams.get('version');
            return route.fulfill({
                json: version
                    ? {
                        ...experience,
                        version: Number(version),
                        immutable: true,
                        experience: {
                            ...experience.experience,
                            welcome_text: '发布版本欢迎语',
                        },
                    }
                    : experience,
            });
        }
        if (
            path === '/service-apps/consumer-service/conversations'
            && request.method() === 'GET'
        ) {
            if (options.conversationList?.delayMs) {
                await new Promise(resolve => setTimeout(resolve, options.conversationList?.delayMs));
            }
            if (options.conversationList?.error) {
                return route.fulfill({
                    status: 500,
                    json: { detail: options.conversationList.error },
                });
            }
            const page = Number(url.searchParams.get('page') || 1);
            const pageSize = Number(url.searchParams.get('page_size') || 10);
            const query = (url.searchParams.get('q') || '').toLowerCase();
            const status = url.searchParams.get('status') || 'all';
            const channelId = url.searchParams.get('channel_id');
            const filtered = [...conversations, ...nonCustomerConversations].filter(item =>
                item.kind === 'customer'
                && (!query
                    || item.question.toLowerCase().includes(query)
                    || item.answer.toLowerCase().includes(query)
                    || item.channel_name.toLowerCase().includes(query)
                    || item.account.toLowerCase().includes(query))
                && (status === 'all' || item.status === status)
                && (!channelId || item.channel_id === channelId),
            );
            return route.fulfill({
                json: {
                    items: [
                        ...filtered.slice((page - 1) * pageSize, page * pageSize),
                        ...(options.conversationList?.injectNonCustomer
                            ? nonCustomerConversations
                            : []),
                    ],
                    total: filtered.length,
                    page,
                    page_size: pageSize,
                    total_pages: Math.ceil(filtered.length / pageSize),
                },
            });
        }
        if (
            path.startsWith('/service-apps/consumer-service/conversations/')
            && request.method() === 'GET'
        ) {
            const conversationId = path.split('/').at(-1);
            const selected = conversations.find(item => item.id === conversationId)
                || conversations[0];
            return route.fulfill({
                json: {
                    ...selected,
                    messages: [
                        {
                            id: 'message-1',
                            seq: 1,
                            role: 'customer',
                            content: selected.question,
                            content_type: 'text',
                            payload: {},
                            runtime_message_id: 'runtime-message-1',
                            created_at: '2026-11-01T01:50:00Z',
                        },
                        {
                            id: 'message-2',
                            seq: 2,
                            role: 'assistant',
                            content: selected.answer,
                            content_type: 'text',
                            payload: {},
                            runtime_message_id: 'runtime-message-2',
                            created_at: '2026-11-01T02:00:00Z',
                        },
                    ],
                    turns: [{
                        id: 'turn-1',
                        status: selected.status,
                        customer_message_id: 'message-1',
                        assistant_message_id: 'message-2',
                        runtime_conversation_id: 'runtime-conversation-1',
                        runtime_run_id: selected.run_id,
                        application_version: 2,
                        agent_version: 2,
                        error_code: null,
                        created_at: '2026-11-01T01:50:00Z',
                        finished_at: '2026-11-01T02:00:00Z',
                    }],
                    runs: [{
                        id: selected.run_id,
                        status: selected.status,
                        output: 'Runtime 内部诊断输出，不属于客户对话内容。',
                        error_code: null,
                        cancel_requested: false,
                        created_at: '2026-11-01T01:50:00Z',
                        started_at: '2026-11-01T01:50:01Z',
                        finished_at: '2026-11-01T02:00:00Z',
                    }],
                    messages_truncated: false,
                },
            });
        }
        if (path === '/service-apps/consumer-service/preview' && request.method() === 'POST') {
            const body = request.postDataJSON() as {
                message: string;
                skill_key: string | null;
                version: number | null;
                allow_write: boolean;
            };
            expect(body).toEqual({
                message: '查询订单',
                skill_key: null,
                version: null,
                allow_write: false,
            });
            return route.fulfill({
                json: {
                    status: 'completed',
                    reply: '已为您查询到订单，当前正在配送中。',
                    application_version: null,
                    draft: true,
                    skills: [{
                        key: 'order_lookup',
                        status: 'completed',
                        duration_ms: 42,
                    }],
                    trace: {
                        route: 'order_lookup',
                        steps: ['receive', 'skill', 'reply'],
                    },
                },
            });
        }
        if (path === '/service-apps/consumer-service' && request.method() === 'PUT') {
            const body = request.postDataJSON() as { name?: string; rules?: unknown };
            return route.fulfill({
                json: {
                    ...application,
                    ...(body.name ? { name: body.name } : {}),
                    rules: body.rules,
                },
            });
        }
        if (path === '/service-apps/consumer-service/skills') {
            return route.fulfill({
                json: { items: [skill], total: 1, page: 1, page_size: 10 },
            });
        }
        if (path === '/service-apps/consumer-service/connections') {
            const page = Number(url.searchParams.get('page') || 1);
            const pageSize = Number(url.searchParams.get('page_size') || 10);
            const connections = Array.from({ length: 12 }, (_, index) => ({
                ...connection,
                id: `connection-${index + 1}`,
                key: `order-api-${index + 1}`,
                name: `订单服务 ${index + 1}`,
            }));
            return route.fulfill({
                json: {
                    items: connections.slice((page - 1) * pageSize, page * pageSize),
                    total: connections.length,
                    page,
                    page_size: pageSize,
                },
            });
        }
        if (path === '/service-apps/consumer-service/traces') {
            return route.fulfill({
                json: {
                    items: [
                        {
                            id: 'trace-1',
                            application_version: 2,
                            agent_version: 2,
                            skill_key: 'order_lookup',
                            connection_key: 'order-api',
                            outcome: 'completed',
                            reason_code: null,
                            duration_ms: 42,
                            created_at: '2026-11-01T02:00:00Z',
                        },
                    ],
                    total: 1,
                    page: 1,
                    page_size: 5,
                },
            });
        }
        if (path === '/service-apps/consumer-service/readiness') {
            return route.fulfill({
                json: options.readiness || {
                    key: application.key,
                    revision: application.draft_revision,
                    status: 'pass',
                    can_publish: true,
                    checks: [
                        {
                            key: 'agent',
                            title: '智能体版本',
                            detail: '已绑定发布版本 v2',
                            status: 'pass',
                            severity: 'blocking',
                        },
                    ],
                    counts: { pass: 1, warning: 0, blocked: 0 },
                },
            });
        }
        if (path === '/service-apps/consumer-service/versions') {
            return route.fulfill({
                json: {
                    items: [
                        {
                            id: 'version-1',
                            version: 1,
                            source_version: null,
                            config_digest: 'sha256:123456',
                            created_by: 'admin',
                            created_at: '2026-10-30T02:00:00Z',
                            current: false,
                        },
                        {
                            id: 'version-2',
                            version: 2,
                            source_version: null,
                            config_digest: 'sha256:abcdef',
                            created_by: 'admin',
                            created_at: '2026-11-01T02:00:00Z',
                            current: true,
                        },
                    ],
                    total: 2,
                    page: 1,
                    page_size: 100,
                    published_version: publishedVersion,
                },
            });
        }
        if (path === '/service-apps/consumer-service/publish' && request.method() === 'POST') {
            expect(request.postDataJSON()).toEqual({ revision: application.draft_revision });
            publishedVersion = 3;
            draftRevision = 4;
            return route.fulfill({
                json: {
                    ...application,
                    status: 'published',
                    published_version: 3,
                    draft_revision: 4,
                    revision: 4,
                    has_unpublished_changes: false,
                },
            });
        }
        if (path === '/service-apps/consumer-service/rollback' && request.method() === 'POST') {
            const body = request.postDataJSON() as { version: number; revision: number };
            expect(body.version).toBe(1);
            expect(body.revision).toBe(draftRevision);
            publishedVersion = 4;
            draftRevision = 5;
            return route.fulfill({
                json: {
                    ...application,
                    status: 'published',
                    published_version: 4,
                    draft_revision: 5,
                    revision: 5,
                    has_unpublished_changes: false,
                },
            });
        }
        if (path === '/service-apps/example-order-service/copy' && request.method() === 'POST') {
            expect(request.postDataJSON()).toEqual({
                key: 'order-service-copy',
                name: '标准订单服务 副本',
            });
            const copied = {
                ...application,
                id: 'app-copy',
                key: 'order-service-copy',
                name: '标准订单服务 副本',
                origin: 'user',
                immutable: false,
                template_key: 'order-service',
                template_version: '1',
            };
            return route.fulfill({ status: 201, json: copied });
        }
        if (path === '/service-apps/order-service-copy' && request.method() === 'GET') {
            return route.fulfill({
                json: {
                    ...detail,
                    id: 'app-copy',
                    key: 'order-service-copy',
                    name: '标准订单服务 副本',
                    origin: 'user',
                    immutable: false,
                },
            });
        }
        if (path === '/channels') {
            return route.fulfill({ json: { items: [channel], total: 1 } });
        }
        if (path.startsWith('/model-gateway/catalog/')) {
            return route.fulfill({
                json: { items: [], total: 0, page: 1, page_size: 10 },
            });
        }
        return route.fulfill({ json: { items: [], total: 0 } });
    });
}

test('publishing warns that unsaved changes are excluded from the release', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps/consumer-service/rules');

    await page.getByRole('combobox', { name: '兜底策略' }).click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option')
        .filter({ hasText: '直接失败' })
        .click();

    await page.getByRole('button', { name: /发布$/ }).click();
    const popover = page.locator('.ant-popover:visible');
    await expect(popover.getByText('当前页面有未保存修改', { exact: true })).toBeVisible();
    await expect(popover.getByText(
        '发布仅包含已保存草稿；未保存修改不会进入新版本。',
        { exact: true },
    )).toBeVisible();
    expect(requests.some(item =>
        item.startsWith('POST /service-apps/consumer-service/publish'),
    )).toBe(false);
});

test('publish button exposes the first blocking readiness reason', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests, {
        readiness: {
            key: application.key,
            revision: application.draft_revision,
            status: 'blocked',
            can_publish: false,
            checks: [{
                key: 'agent:agent_release_available',
                title: 'agent_release_available',
                detail: 'Bound Agent/version is unavailable: agent_not_found',
                status: 'blocked',
                severity: 'blocking',
            }],
            counts: { pass: 0, warning: 0, blocked: 1 },
        },
    });
    await page.goto('/#/service-apps/consumer-service');

    const publishButton = page.getByRole('button', { name: /发布$/ });
    await expect(publishButton).toBeDisabled();
    await page.locator('.sa-release-header-actions > span').hover();
    await expect(page.locator('.ant-tooltip:visible')).toContainText(
        '发布检查未通过：Bound Agent/version is unavailable: agent_not_found',
    );
});

test('immutable examples expose a specific publish reason', async ({ page }) => {
    await mockConsole(page, []);
    await page.goto('/#/service-apps/example-order-service');

    const examplePublish = page.getByRole('button', { name: /发布$/ });
    await expect(examplePublish).toBeDisabled();
    await page.locator('.sa-release-header-actions > span').hover();
    await expect(page.locator('.ant-tooltip:visible')).toContainText(
        '标准案例需复制为我的应用后才能发布。',
    );
});

test('non-admin users expose a specific publish reason', async ({ page }) => {
    await mockConsole(page, [], { role: 'viewer' });
    await page.goto('/#/service-apps/consumer-service');

    const viewerPublish = page.getByRole('button', { name: /发布$/ });
    await expect(viewerPublish).toBeDisabled();
    await page.locator('.sa-release-header-actions > span').hover();
    await expect(page.locator('.ant-tooltip:visible')).toContainText(
        '当前角色没有发布权限。',
    );
});

test('my applications catalog uses the v2 contract and default page size', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);

    await page.goto('/#/service-apps');
    await expect(page.locator('.console-heading')).toHaveCount(0);
    await expect(page.locator('.sa-catalog-hero h2')).toHaveText('我的应用');
    await expect(page.getByRole('button', { name: /标准案例/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /新建服务应用/ })).toBeVisible();
    await expect(page.locator('.sa-app-card')).toHaveCount(1);
    await expect(page.getByText('购物消费服务应用', { exact: true })).toBeVisible();
    await expect(page.getByText('标准订单服务', { exact: true })).toHaveCount(0);
    await expect(page.getByText('生产运行中', { exact: true })).toBeVisible();
    await expect(page.getByText('业务编排', { exact: true })).toHaveCount(0);
    await expect(page.getByText('执行能力', { exact: true })).toHaveCount(0);
    await expect(page.getByText('接入能力', { exact: true })).toHaveCount(0);

    expect(requests).toContain(
        'GET /service-apps?page=1&page_size=10&origin=user&archived=false',
    );
    expect(requests).toContain('GET /service-apps/overview?origin=user');
    await expect(page.locator('.sa-pagination-bar')).toHaveCSS('justify-content', 'flex-end');
    await expect(page.locator('.sa-pagination-bar .ant-pagination'))
        .toContainText(/10\s*条\/页/);
});

test('standard examples live on their own route and do not mix into my applications', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);

    await page.goto('/#/service-apps/standards');

    await expect(page.locator('.sa-catalog-hero h2')).toHaveText('标准案例');
    await expect(page.getByText('标准订单服务', { exact: true })).toBeVisible();
    await expect(page.getByText('购物消费服务应用', { exact: true })).toHaveCount(0);
    await expect(page.locator('.sa-standard-card')).toHaveCount(1);
    expect(requests).toContain(
        'GET /service-apps?page=1&page_size=10&origin=example&archived=false',
    );

    await page.getByRole('button', { name: /返回服务应用/ }).click();
    await expect(page).toHaveURL(/#\/service-apps$/);
});

test('service application detail exposes only the seven v2 tabs', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps/consumer-service');

    await expect(page.locator('.console-heading')).toHaveCount(0);
    await expect(page.locator('.sa-detail-title-line h2')).toHaveText('购物消费服务应用');
    await page.getByRole('button', { name: '编辑 购物消费服务应用' }).click();
    const nameInput = page.getByRole('textbox', { name: '应用名称' });
    await expect(nameInput).toHaveValue('购物消费服务应用');
    await nameInput.fill('购物消费服务应用（已更新）');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await expect(page.locator('.sa-detail-title-line h2'))
        .toHaveText('购物消费服务应用（已更新）');
    expect(requests).toContain('PUT /service-apps/consumer-service');
    await expect(page.getByText('已完成', { exact: true })).toBeVisible();
    await expect(page.getByText('completed', { exact: true })).toHaveCount(0);
    const cardAlignment = await page.locator('.sa-overview-card dl').first().evaluate(dl => {
        const label = dl.querySelector('dt')!.getBoundingClientRect();
        const value = dl.querySelector('dd')!.getBoundingClientRect();
        return { labelTop: label.top, valueTop: value.top, labelLeft: label.left, valueLeft: value.left };
    });
    expect(Math.abs(cardAlignment.labelTop - cardAlignment.valueTop)).toBeLessThan(1.5);
    expect(cardAlignment.valueLeft).toBeGreaterThan(cardAlignment.labelLeft);
    await expect(page.locator('.sa-detail-tabs .ant-tabs-nav-list .anticon')).toHaveCount(0);
    const publishButton = page.getByRole('button', { name: /发布$/ });
    await expect(publishButton).toBeVisible();
    const tabs = page.getByRole('tab');
    await expect(tabs).toHaveCount(7);
    await expect(tabs.nth(0)).toContainText('概览');
    await expect(tabs.nth(1)).toContainText('智能体');
    await expect(tabs.nth(2)).toContainText('客户交互');
    await expect(tabs.nth(3)).toContainText('技能');
    await expect(tabs.nth(4)).toContainText('业务规则');
    await expect(tabs.nth(5)).toContainText('对话记录');
    await expect(tabs.nth(6)).toContainText('客户渠道与发布');
    await expect(page.getByRole('tab', { name: '客户界面调试' })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: '预览与调试' })).toHaveCount(0);

    await tabs.nth(1).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/agent$/);
    await expect(publishButton).toBeVisible();
    await expect(page.getByText('应用绑定版本', { exact: true })).toBeVisible();
    await tabs.nth(2).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/experience$/);
    await expect(publishButton).toBeVisible();
    await expect(page.getByText('订单服务', { exact: true }).first()).toBeVisible();
    await expect(page.locator('.sa-component-list .ant-tag')).toHaveCount(0);
    await tabs.nth(3).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/skills$/);
    await expect(publishButton).toBeVisible();
    await expect(page.getByText('order_lookup', { exact: true })).toBeVisible();
    expect(requests.some(item => item.includes('/skills?page=1&page_size=10'))).toBeTruthy();
    await expect(page.locator('.sa-skills-panel .ant-table-pagination')).toHaveCount(0);
    await page.getByRole('button', { name: '测试技能 订单查询' }).hover();
    await expect(page.locator('.ant-tooltip:visible')).toContainText('测试技能');
    await tabs.nth(4).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/rules$/);
    await expect(publishButton).toBeVisible();
    await tabs.nth(5).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/conversations$/);
    await expect(page.locator('.sa-conversation-records-table')).toBeVisible();
    await tabs.nth(6).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/release$/);
    await expect(publishButton).toBeVisible();
    await page.locator('.sa-detail-meta-current').click();
    await expect(page.locator('.sa-version-history')).toBeVisible();
    await expect(page.getByRole('heading', { name: '版本历史', exact: true })).toBeVisible();
    await expect(page.getByText('渠道数量', { exact: true })).toBeVisible();
    await expect(page.locator('.sa-versions-panel')).toHaveCount(0);
});

test('customer interaction uses real preview replies and keeps diagnostics in the operations drawer', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps/consumer-service/experience');

    const canvas = page.locator('.sa-cp-canvas');
    await expect(canvas).toBeVisible();
    await expect(canvas.getByText('猜你想问', { exact: true })).toBeVisible();
    await expect(canvas).not.toContainText('order_lookup');

    await page.getByText('发布版本 · v2', { exact: true }).click();
    await expect(canvas.getByText('发布版本欢迎语', { exact: true })).toBeVisible();
    expect(requests).toContain(
        'GET /service-apps/consumer-service/experience?version=2',
    );
    await page.getByText('草稿预览 · r3', { exact: true }).click();
    await expect(canvas.getByText(
        '您好，我是购物消费服务助手，请问有什么可以帮您？',
        { exact: true },
    )).toBeVisible();

    await page.getByRole('textbox', { name: '客户消息' }).fill('查询订单');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    await expect(canvas.getByText('已为您查询到订单，当前正在配送中。', { exact: true }))
        .toBeVisible();
    expect(requests).toContain('POST /service-apps/consumer-service/preview');
    await expect(page.getByRole('button', { name: /运行记录/ })).toContainText('1');
    await expect(canvas).not.toContainText('"route": "order_lookup"');

    await page.getByRole('button', { name: /运行记录/ }).click();
    const history = page.getByRole('dialog', { name: '运行记录' });
    await expect(history.getByRole('row', { name: /查询订单/ })).toBeVisible();
    await history.getByRole('button', { name: /查看诊断/ }).click();

    const diagnostic = page.getByRole('dialog', { name: '诊断详情' });
    await expect(diagnostic.getByText('order_lookup · completed', { exact: true })).toBeVisible();
    await expect(diagnostic.getByText(/"route": "order_lookup"/)).toBeVisible();
});

test('customer conversation records use business conversations with pagination and full detail', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests, {
        conversationList: { injectNonCustomer: true },
    });
    await page.goto('/#/service-apps/consumer-service/conversations');

    const records = page.locator('.sa-conversation-records-table');
    await expect(records.locator('.ant-table-row')).toHaveCount(10);
    await expect(records.getByText('请帮我查询订单', { exact: true })).toBeVisible();
    await expect(records.getByText('订单配送进度咨询', { exact: true })).toBeVisible();
    await expect(records.getByText('客户界面调试会话不应出现', { exact: true })).toHaveCount(0);
    await expect(records.getByText('Playground 会话不应出现', { exact: true })).toHaveCount(0);
    await expect(records.getByText('暂无反馈', { exact: true }).first()).toBeVisible();
    await expect(records.getByRole('button', { name: '保存 QA' }).first()).toBeDisabled();
    expect(requests).toContain(
        'GET /service-apps/consumer-service/conversations?page=1&page_size=10&status=all',
    );

    await records.locator('.ant-pagination-item-2').click();
    await expect.poll(() => requests.includes(
        'GET /service-apps/consumer-service/conversations?page=2&page_size=10&status=all',
    )).toBe(true);
    await expect(records.locator('.ant-table-row')).toHaveCount(2);

    await records.locator('.ant-pagination-item-1').click();
    await records.getByRole('button', { name: '查看完整对话' }).first().click();
    const detail = page.getByRole('dialog', { name: '完整对话' });
    await expect(detail.getByText('订单配送进度咨询', { exact: true })).toBeVisible();
    await expect(detail.getByText('请帮我查询订单', { exact: true })).toBeVisible();
    const customerThread = detail.locator('.sa-conversation-thread');
    await expect(customerThread.getByText(
        '已为您查询到订单，当前正在配送中。',
        { exact: true },
    )).toBeVisible();
    await expect(customerThread).not.toContainText(
        'Runtime 内部诊断输出，不属于客户对话内容。',
    );
    await expect(detail.getByText('张小明', { exact: true })).toBeVisible();
    await expect(detail.getByText('客户', { exact: true })).toBeVisible();
    await expect(detail.getByText('应用回复', { exact: true })).toBeVisible();
    await expect(detail.getByText('Agent 运行诊断', { exact: true })).toBeVisible();
    await expect(detail.getByText('turn-1', { exact: true })).toBeVisible();
    await expect(
        detail.locator('.sa-conversation-diagnostic-table').nth(1)
            .getByText('run-1', { exact: true }),
    ).toBeVisible();

    await page.keyboard.press('Escape');
    await page.getByPlaceholder('搜索问题、回答、渠道或账号').fill('测试客户问题 11');
    await page.getByPlaceholder('搜索问题、回答、渠道或账号').press('Enter');
    await expect(records.getByText('测试客户问题 11', { exact: true })).toBeVisible();
    await expect(records.locator('.ant-table-row')).toHaveCount(1);

    await page.getByPlaceholder('搜索问题、回答、渠道或账号').fill('不存在的客户问题');
    await page.getByPlaceholder('搜索问题、回答、渠道或账号').press('Enter');
    await expect(records.locator('.ant-table-row')).toHaveCount(0);
    await expect(records.getByText('暂无真实客户对话记录', { exact: true })).toBeVisible();
});

test('customer conversation records expose loading and error states without stale rows', async ({ page }) => {
    await mockConsole(page, [], {
        conversationList: {
            delayMs: 300,
            error: 'conversation ledger unavailable',
        },
    });
    await page.goto('/#/service-apps/consumer-service/conversations');

    const records = page.locator('.sa-conversation-records-table');
    await expect(records.locator('.ant-spin-spinning')).toBeVisible();
    await expect(page.locator('.ant-alert-error')).toContainText(
        '500 · conversation ledger unavailable',
    );
    await expect(page.locator('.ant-alert-error .ant-btn')).toContainText(/重\s*试/);
    await expect(records.locator('.ant-table-row')).toHaveCount(0);
});

test('service application connections use server-side pagination metadata', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps/consumer-service/skills');

    const connectionsPanel = page.locator('.sa-connections');
    await expect(connectionsPanel.locator('.ant-table-row')).toHaveCount(10);
    await expect(connectionsPanel.locator('.ant-table-pagination')).toHaveCSS(
        'justify-content',
        'flex-end',
    );
    await expect(connectionsPanel.locator('.ant-pagination')).toContainText(/10\s*条\/页/);
    expect(requests).toContain(
        'GET /service-apps/consumer-service/connections?page=1&page_size=10',
    );

    await connectionsPanel.locator('.ant-pagination-item-2').click();
    await expect.poll(() => requests.includes(
        'GET /service-apps/consumer-service/connections?page=2&page_size=10',
    )).toBe(true);
    await expect(connectionsPanel.locator('.ant-table-row')).toHaveCount(2);
    await expect(page.getByText('订单服务 11', { exact: true })).toBeVisible();
});

test('application rules parser tolerates missing and additional v2 fields', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests, {
        rules: {
            fallback: 'reply',
            handoff_queue: 'after-sales',
            legacy_handoff_mode: 'queue',
            unexpected_preview: { enabled: true },
        },
    });
    await page.goto('/#/service-apps/consumer-service/rules');

    await expect(page.getByRole('heading', { name: '应用级规则', exact: true })).toBeVisible();
    await expect(page.getByText('兜底回复', { exact: true })).toBeVisible();
    await expect(page.getByLabel('人工队列', { exact: true })).toHaveValue('after-sales');
    await expect(page.getByLabel('转人工说明', { exact: true })).toHaveValue('');
    await expect(page.getByText('默认禁用', { exact: true })).toBeVisible();
    await expect(page.getByText('结果校验', { exact: true })).toBeVisible();
    await expect(page.locator('.sa-rules-skills .ant-table-pagination')).toHaveCount(0);

    const saveRequest = page.waitForRequest(request =>
        request.method() === 'PUT'
        && new URL(request.url()).pathname === '/api/v1/service-apps/consumer-service',
    );
    await page.getByRole('button', { name: /保存草稿/ }).click();
    const body = (await saveRequest).postDataJSON() as {
        rules: { fallback: string; validate_results: boolean };
    };
    expect(body.rules.fallback).toBe('fallback');
    expect(body.rules.validate_results).toBe(true);
    expect(JSON.stringify(body)).not.toContain('"reply"');
});

test('service application release publishes and appends a rollback version', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps/consumer-service/release');

    await expect(page.locator('.sa-detail-meta')).toBeVisible();
    await expect(page.locator('.sa-release-header-actions')).toBeVisible();
    await expect(page.getByRole('button', { name: /发布$/ })).toBeVisible();
    const agentMeta = page.locator('.sa-detail-meta > div').first();
    await expect(agentMeta).toContainText('购物消费助手-v1');
    await expect(agentMeta).not.toContainText('agent-1');
    await expect(page.getByText('绑定版本', { exact: true })).toHaveCount(0);
    await expect(page.locator('.sa-detail-meta > div').first()).toHaveCSS('min-height', '36px');
    await expect(page.locator('.sa-detail-meta > div').first()).toHaveCSS(
        'flex-direction',
        'row',
    );
    await expect(page.getByRole('button', { name: /发布$/ })).toHaveCSS('height', '36px');
    await expect(page.getByRole('heading', { name: '客户渠道与发布', exact: true })).toBeVisible();
    await page.locator('.sa-detail-meta-current').click();
    await expect(page.locator('.sa-version-history')).toBeVisible();
    await expect(page.getByRole('heading', { name: '版本历史', exact: true })).toBeVisible();
    await expect(page.locator('.sa-channels-panel')).toBeVisible();
    await expect(page.locator('.sa-readiness-card')).toBeVisible();
    await expect(page.getByRole('row', { name: /官网帮助中心/ })).toBeVisible();
    await expect(page.locator('.sa-version-history .ant-table-row')).toHaveCount(2);
    await expect(page.locator('.sa-channels-panel .ant-table-pagination')).toHaveCount(0);
    await expect(page.locator('.sa-version-history .ant-table-pagination')).toHaveCount(0);

    await page.getByRole('button', { name: /发布$/ }).click();
    await page.locator('.ant-popover:visible').getByRole('button', { name: /确认发布/ }).click();
    await expect.poll(() => requests.some(item =>
        item === 'POST /service-apps/consumer-service/publish'
        || item.startsWith('POST /service-apps/consumer-service/publish'),
    )).toBe(true);
    await expect(page.getByText('发布已保存草稿', { exact: true })).toBeVisible();

    await page.locator('.sa-detail-meta-current').click();
    await expect(page.locator('.sa-version-history')).toBeVisible();
    const versionOneRow = page.locator('.sa-version-history').getByRole('row', { name: /v1/ });
    await versionOneRow.getByRole('button', { name: /回滚$/ }).click();
    await page.locator('.ant-popconfirm-buttons:visible')
        .getByRole('button', { name: /回\s*滚/ })
        .click();
    await expect.poll(() => requests.some(item =>
        item.startsWith('POST /service-apps/consumer-service/rollback'),
    )).toBe(true);
    await expect(page.getByText('已回滚', { exact: true })).toBeVisible();
});

test('an immutable example application can be copied into an editable user application', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps/standards');

    await page.getByRole('button', { name: /复制为我的应用$/ }).click();
    const dialog = page.getByRole('dialog', { name: '复制为我的应用', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('应用标识', { exact: true })).toHaveValue('order-service-copy');
    await expect(dialog.getByLabel('应用名称', { exact: true })).toHaveValue('标准订单服务 副本');
    await dialog.getByRole('button', { name: /复\s*制/ }).click();

    await expect.poll(() => requests.some(item =>
        item.startsWith('POST /service-apps/example-order-service/copy'),
    )).toBe(true);
    await expect(page).toHaveURL(/#\/service-apps\/order-service-copy$/);
    await expect(page.locator('.sa-detail-title-line h2')).toHaveText('标准订单服务 副本');
    await expect(page.getByText('我的应用', { exact: true })).toBeVisible();
});

test('published applications must be taken offline before archiving, and archived rows can be restored', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);
    await page.goto('/#/service-apps');

    await page.getByRole('button', { name: /购物消费服务应用 更多操作/ }).click();
    await page.getByRole('menuitem', { name: '归档应用' }).click();
    const archiveDialog = page.getByRole('dialog', { name: '归档应用', exact: true });
    await expect(archiveDialog.getByText('需要先下线生产版本', { exact: true })).toBeVisible();
    await expect(archiveDialog.getByRole('button', { name: '前往下线处理', exact: true })).toBeVisible();
    expect(requests.some(item =>
        item.startsWith('POST /service-apps/consumer-service/archive'),
    )).toBe(false);
    await archiveDialog.getByRole('button', { name: /前往下线处理/ }).click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service\/release$/);
    await page.getByRole('button', { name: /下线应用/ }).click();
    await page.locator('.ant-popover:visible').getByRole('button', { name: /确认下线/ }).click();
    await expect.poll(() => requests.some(item =>
        item.startsWith('POST /service-apps/consumer-service/status'),
    )).toBe(true);

    await page.goto('/#/service-apps');
    await page.getByRole('button', { name: /购物消费服务应用 更多操作/ }).click();
    await page.getByRole('menuitem', { name: '归档应用' }).click();
    const confirmArchiveDialog = page.getByRole('dialog', { name: '归档应用', exact: true });
    await confirmArchiveDialog.getByRole('button', { name: /确认归档/ }).click();
    await expect.poll(() => requests.some(item =>
        item.startsWith('POST /service-apps/consumer-service/archive'),
    )).toBe(true);
    await expect(page.getByText('应用已归档，可在“已归档”中恢复', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: /已归档/ }).click();
    const archivedDialog = page.getByRole('dialog', { name: '已归档应用', exact: true });
    await expect(archivedDialog.locator('.sa-archived-table')).toBeVisible();
    await expect(archivedDialog.getByText('已归档服务应用', { exact: true })).toBeVisible();
    await expect(archivedDialog.locator('.ant-table-pagination')).toHaveCount(0);
    await archivedDialog.getByRole('button', { name: /恢\s*复/ }).click();
    await expect.poll(() => requests.some(item =>
        item.startsWith('POST /service-apps/archived-service/restore'),
    )).toBe(true);
    await expect(page.getByText('应用已恢复', { exact: true })).toBeVisible();
});

test('agent usage view reads service application references from the application list', async ({ page }) => {
    const requests: string[] = [];
    await mockConsole(page, requests);

    await page.goto('/#/agents/agent-1/usage');
    await expect(page.getByRole('button', { name: '服务应用', exact: true })).toBeVisible();
    await expect(page.getByText('被服务应用引用', { exact: true })).toBeVisible();
    await expect(page.getByText('购物消费服务应用', { exact: true })).toBeVisible();
    await expect(page.getByText('标准订单服务', { exact: true })).toBeVisible();

    expect(requests.some(item => item.includes('/service-apps?page=1&page_size=100'))).toBeTruthy();

    await page.getByRole('button', { name: '打开应用', exact: true }).first().click();
    await expect(page).toHaveURL(/#\/service-apps\/consumer-service$/);
});
