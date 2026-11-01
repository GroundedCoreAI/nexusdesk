import type { Page } from '@playwright/test';

export const agent = {
    id: 'agent-1',
    name: '购物消费助手',
    description: '处理购物、订单、物流与售后问题',
    draft: {
        system_prompt: 'test',
        tool_names: ['knowledge_search'],
        knowledge_base_ids: [],
        max_model_rounds: 6,
        model_profile_id: 'profile-1',
        model_profile_version: 2,
    },
    draft_revision: 1,
    published_version: 5,
    archived: false,
    updated_at: '2026-10-31T02:00:00Z',
};

const recommendation = (key: string, label: string, message: string) => ({ key, label, message, when: {} });

function scenarioConfig(
    key: string,
    name: string,
    description: string,
    category: string,
    template: 'consult' | 'query' | 'action',
) {
    const objectRequired = template !== 'consult';
    const handlers = template === 'action'
        ? [
            { key: 'business-action', type: 'action', label: '提交业务申请', enabled: true, priority: 10, tool: 'create_after_sales', when: {} },
            { key: 'human-support', type: 'human', label: '人工客服', enabled: true, priority: 20, queue: 'order-support', when: {} },
        ]
        : template === 'query'
            ? [
                { key: 'agent-complex', type: 'agent', label: '复杂问题与异常解释', enabled: true, priority: 10, agent_id: agent.id, agent_version: 5, agent_name: agent.name, when: {} },
                { key: 'order-status-query', type: 'query', label: '查询订单状态', enabled: true, priority: 20, tool: 'order_status', when: {} },
                { key: 'human-order-queue', type: 'human', label: '订单专属人工队列', enabled: true, priority: 30, queue: 'order-support', when: {} },
            ]
            : [
                { key: 'direct-reply', type: 'direct', label: '固定应答', enabled: true, priority: 10, reply: `您好，这里是${name}。`, when: {} },
                { key: 'human-support', type: 'human', label: '人工客服', enabled: true, priority: 20, queue: 'order-support', when: {} },
            ];
    return {
        schema_version: 'v1',
        name,
        description,
        domain: '客户服务',
        category,
        template,
        channels: ['web', 'app'],
        entries: [
            { key: 'natural-language', type: 'natural_language', label: '自然语言', description: name, enabled: true, config: {} },
            { key: 'service-catalog', type: 'service_catalog', label: '服务目录', description: category, enabled: true, config: {} },
        ],
        facts: objectRequired
            ? [
                { key: 'order_status', label: '订单状态', source: 'status', format: 'text', order: 10, masked: false, audiences: ['customer'], refresh: 'on_open', config: {} },
                { key: 'logistics_status', label: '物流状态', source: 'logistics.status', format: 'text', order: 20, masked: false, audiences: ['customer'], refresh: 'on_open', config: {} },
            ]
            : [],
        object: objectRequired
            ? {
                type: 'order',
                provider: 'order_provider',
                required: true,
                mode: 'required',
                candidate_strategy: {
                    sort: 'recent_desc',
                    limit: 5,
                    filters: ['运输中', '已完成'],
                    empty_state: '没有找到可用的订单。',
                    unavailable_state: '订单服务暂时不可用。',
                },
                permission_policy: 'customer_scope',
                config: {},
            }
            : null,
        decisions: template === 'query'
            ? [
                { key: 'select_order', kind: 'select_object', label: '选择订单', required: true, options: [], allow_free_text: false, allow_skip: false, confirm: false, correctable: true, when: {} },
                { key: 'choose_intent', kind: 'select_intent', label: '选择问题', required: false, options: [], allow_free_text: true, allow_skip: true, confirm: false, correctable: true, when: {} },
            ]
            : template === 'action'
                ? [
                    { key: 'confirm-action', kind: 'confirm_action', label: '确认提交', required: true, options: [], allow_free_text: false, allow_skip: false, confirm: true, correctable: true, when: {} },
                ]
                : [],
        recommendations: [
            recommendation(`${key}-status`, '查询处理状态', '我想查询处理进度'),
            recommendation(`${key}-human`, '转人工', '转人工'),
        ],
        handlers,
        fallback_order: handlers.map(item => item.key),
        matching: {
            keywords: [name, key, category],
            intents: [],
            negative_keywords: [],
        },
        config: {},
    };
}

const scenarioDefinitions = [
    {
        key: 'invoice',
        name: '发票与报销',
        description: '查看可开发票订单、申请开票并查询开票进度',
        category: '发票服务',
        template: 'action' as const,
        status: 'published',
        published_version: 4,
    },
    {
        key: 'order-rules',
        name: '咨询订单规则',
        description: '查询退换货、配送和订单相关政策',
        category: '规则与知识',
        template: 'consult' as const,
        status: 'published',
        published_version: 2,
    },
    {
        key: 'complaints',
        name: '投诉与反馈',
        description: '提交服务投诉并跟踪处理进度',
        category: '投诉反馈',
        template: 'action' as const,
        status: 'review',
        published_version: null,
    },
    {
        key: 'query-orders',
        name: '查询我的订单',
        description: '找到并确认一笔订单，查看状态并继续咨询',
        category: '订单服务',
        template: 'query' as const,
        status: 'published',
        published_version: 3,
    },
    {
        key: 'track-logistics',
        name: '查询物流',
        description: '查询物流节点并解释运输异常',
        category: '订单服务',
        template: 'query' as const,
        status: 'published',
        published_version: 1,
    },
    {
        key: 'after-sales',
        name: '申请售后',
        description: '选择订单并发起退款、退货或换货申请',
        category: '售后服务',
        template: 'action' as const,
        status: 'draft',
        published_version: null,
    },
];

export const scenarios = scenarioDefinitions.map((item, index) => ({
    id: `scenario-${item.key}`,
    key: item.key,
    name: item.name,
    description: item.description,
    domain: '客户服务',
    category: item.category,
    template: item.template,
    status: item.status,
    revision: 1,
    published_version: item.published_version,
    config: scenarioConfig(item.key, item.name, item.description, item.category, item.template),
    published_config: item.published_version
        ? scenarioConfig(item.key, item.name, item.description, item.category, item.template)
        : null,
    has_unpublished_changes: false,
    metrics: { volume: 1800 - index * 120, auto_resolved: 1500, handoffs: 80, auto_resolve_rate: 83.3, handoff_rate: 4.4 },
    created_at: '2026-10-31T02:00:00Z',
    updated_at: '2026-10-31T02:00:00Z',
}));

export const scenarioByKey = new Map(scenarios.map(item => [item.key, item]));

const applicationConfig = {
    schema_version: 'v1',
    name: '购物消费服务应用',
    description: '订单、物流、售后与发票服务的统一业务应用',
    service_categories: [
        { name: '订单服务', order: 10 },
        { name: '售后服务', order: 20 },
        { name: '发票服务', order: 30 },
        { name: '规则与知识', order: 40 },
        { name: '投诉反馈', order: 50 },
    ],
    scenarios: scenarios.map(item => ({ key: item.key, version: item.published_version, enabled: true })),
    capabilities: [
        { key: 'direct', type: 'direct', label: 'Direct', enabled: true, priority: 10, when: {}, agent_id: null, agent_version: null, agent_name: null, queue: null, tool: null, config: { description: '固定回执与不需要外部资源的确定性回复。' } },
        { key: 'knowledge', type: 'knowledge', label: '知识检索', enabled: true, priority: 20, when: {}, agent_id: null, agent_version: null, agent_name: null, queue: null, tool: null, config: { description: '企业知识库、FAQ、规则与政策文档。' } },
        { key: 'business-query', type: 'query', label: '业务查询', enabled: true, priority: 30, when: {}, agent_id: null, agent_version: null, agent_name: null, queue: null, tool: 'order_status', config: { description: '订单、物流、发票等只读业务接口。' } },
        { key: 'business-action', type: 'action', label: '业务办理', enabled: true, priority: 40, when: {}, agent_id: null, agent_version: null, agent_name: null, queue: null, tool: 'create_after_sales', config: { description: '售后申请、投诉、工单等需要确认的业务动作。' } },
        { key: 'shopping-agent', type: 'agent', label: '购物消费助手', enabled: true, priority: 50, when: {}, agent_id: agent.id, agent_version: 5, agent_name: agent.name, queue: null, tool: null, config: { description: '复杂解释、多步推理和确定性能力失败后的升级处理。' } },
        { key: 'human-support', type: 'human', label: '人工客服', enabled: true, priority: 60, when: {}, agent_id: null, agent_version: null, agent_name: null, queue: 'order-support', tool: null, config: { description: '带完整业务上下文的最终人工兜底。' } },
        { key: 'service-tracking', type: 'tracking', label: '处理进度跟踪', enabled: true, priority: 70, when: {}, agent_id: null, agent_version: null, agent_name: null, queue: null, tool: null, config: { description: '售后、投诉与工单的处理进度查询。' } },
    ],
    default_execution_order: ['deterministic', 'action', 'agent', 'human'],
    channels: [
        { key: 'web', name: '官网帮助中心', type: 'web', status: 'active', config: {} },
        { key: 'wecom', name: '企业微信客服', type: 'wecom', status: 'active', config: {} },
        { key: 'open-api', name: '开放平台 API', type: 'api', status: 'active', config: {} },
        { key: 'h5', name: 'H5 服务页', type: 'h5', status: 'canary', config: {} },
    ],
};

export const consumerApp = {
    id: 'app-consumer',
    key: 'consumer-service',
    name: '购物消费服务应用',
    description: applicationConfig.description,
    status: 'published',
    revision: 8,
    published_version: 8,
    config: applicationConfig,
    scenario_count: scenarios.length,
    capability_count: applicationConfig.capabilities.length,
    channel_count: applicationConfig.channels.length,
    has_unpublished_changes: false,
    created_at: '2026-10-30T02:00:00Z',
    updated_at: '2026-10-31T02:00:00Z',
};

const createdApp = {
    id: 'app-account',
    key: 'account-service',
    name: '账号安全服务应用',
    description: '处理登录、密码与账号安全相关服务',
    status: 'draft',
    revision: 1,
    published_version: null,
    config: {
        ...applicationConfig,
        name: '账号安全服务应用',
        description: '处理登录、密码与账号安全相关服务',
        service_categories: [],
        scenarios: [],
        capabilities: [],
        channels: [],
    },
    scenario_count: 0,
    capability_count: 0,
    channel_count: 0,
    has_unpublished_changes: true,
    updated_at: '2026-11-01T02:00:00Z',
};

const appVersion = {
    id: 'app-version-8',
    version: 8,
    config: applicationConfig,
    source_version: null,
    created_by: 'admin',
    created_at: '2026-10-31T02:00:00Z',
    published: true,
};

const trace = {
    id: 'trace-e2e',
    scenario_key: 'query-orders',
    scenario_version: 3,
    simulation: true,
    entry: 'natural_language',
    message_length: 12,
    message_excerpt: '物流为什么没更新？',
    object_ref: { id: 'SIM-ORDER-20261031', type: 'order', status: '运输中' },
    facts: [],
    decisions: [],
    handler_type: 'agent',
    outcome: 'resolved',
    reason_code: 'completed',
    result_summary: '后端模拟已完成',
    trace: {},
    created_by: 'admin',
    created_at: '2026-10-31T02:00:00Z',
};

function simulatedTrace(body: any) {
    const scenario = scenarioByKey.get(body.scenario_key) || scenarioByKey.get('query-orders')!;
    const handler = body.message?.includes('人工')
        ? { key: 'human-order-queue', type: 'human', label: '订单专属人工队列', queue: 'order-support' }
        : scenario.config.handlers[0];
    return {
        schema_version: 'v1',
        scenario_key: scenario.key,
        scenario_name: scenario.name,
        scenario_version: scenario.published_version,
        scenario_status: scenario.status,
        resolved_by: 'target',
        steps: [
            { step: 'scene', status: 'done', scenario_name: scenario.name, reason: '目标场景已命中' },
            { step: 'object', status: body.object ? 'done' : 'not_required', object: body.object || null },
            { step: 'facts', status: 'done', count: 1 },
            { step: 'decision', status: 'done', available_keys: scenario.config.decisions.map((item: any) => item.key), selected_decision: body.selected_decision || null },
            { step: 'handler', status: 'done', handler_type: handler.type, handler_key: handler.key },
            { step: 'result', status: 'done', content: `已由${scenario.name}处理后端模拟请求。` },
        ],
        object_ref: body.object || null,
        facts: body.object
            ? [
                { key: 'order_status', label: '订单状态', source: 'status', value: body.object.status || null, format: 'text' },
                { key: 'logistics_status', label: '物流状态', source: 'logistics.status', value: body.object.facts?.logistics_status || null, format: 'text' },
            ]
            : [],
        decisions: scenario.config.decisions.map((item: any) => ({ ...item, selected: body.selected_decision === item.key })),
        recommendations: scenario.config.recommendations,
        handler,
        result: { status: handler.type === 'human' ? 'handoff' : 'resolved', content: `已由${scenario.name}处理后端模拟请求。` },
        fallback_path: scenario.config.fallback_order,
        explanation: [
            `消息命中服务场景「${scenario.name}」`,
            body.object ? `已绑定模拟对象 ${body.object.id}` : '该场景无需业务对象',
            `由 ${handler.label} 承接本次模拟`,
        ],
        simulated: true,
        trace_id: 'trace-e2e-20261101',
        application_key: 'consumer-service',
        application_revision: 8,
        application_source: 'draft',
        application_version: null,
    };
}

export async function mockConsoleApi(
    page: Page,
    options: {
        onCreate?: (body: unknown) => void;
        onScenarioCreate?: (body: unknown) => void;
        onUpdateApp?: (body: unknown) => void;
        onCatalogUpdate?: (body: unknown) => void;
        onSimulate?: (body: unknown) => void;
    } = {},
) {
    await page.route('**/api/v1/**', route => {
        const request = route.request();
        const path = new URL(request.url()).pathname.replace('/api/v1', '');
        const method = request.method();

        if (path === '/me') return route.fulfill({ json: { role: 'admin', tenant: '演示企业', actor: 'admin', permissions: [] } });
        if (path === '/extensions/ui') return route.fulfill({ json: [] });
        if (path === '/extensions/capabilities') return route.fulfill({ json: { capabilities: { items: [] } } });
        if (path === '/modules') return route.fulfill({ json: [] });
        if (path === '/observability/summary') return route.fulfill({ json: {} });

        if (path === '/service-apps' && method === 'POST') {
            options.onCreate?.(request.postDataJSON());
            return route.fulfill({ status: 201, json: createdApp });
        }
        if (path === '/service-apps') return route.fulfill({ json: { items: [consumerApp], total: 1 } });
        if (path === '/service-apps/overview') {
            return route.fulfill({
                json: {
                    applications: 1,
                    by_status: { draft: 0, review: 0, published: 1, offline: 0 },
                    scenarios: scenarios.length,
                    capabilities: applicationConfig.capabilities.length,
                    channels: applicationConfig.channels.length,
                    simulations: 1,
                },
            });
        }
        if (path === '/service-apps/consumer-service') {
            if (method === 'PUT') {
                const body = request.postDataJSON();
                options.onUpdateApp?.(body);
                return route.fulfill({ json: { ...consumerApp, config: body.config, revision: body.revision + 1, updated_at: '2026-11-01T04:00:00Z' } });
            }
            return route.fulfill({ json: consumerApp });
        }
        if (path === '/service-apps/consumer-service/service-catalog' && method === 'PUT') {
            const body = request.postDataJSON() as any;
            options.onCatalogUpdate?.(body);
            return route.fulfill({
                json: {
                    ...consumerApp,
                    config: { ...applicationConfig, service_categories: body.categories },
                    revision: body.revision + 1,
                    updated_at: '2026-11-01T05:00:00Z',
                },
            });
        }
        if (path === '/service-apps/account-service') return route.fulfill({ json: createdApp });
        if (path === '/service-apps/account-service/versions') return route.fulfill({ json: { items: [], published_version: null } });
        if (path === '/service-apps/account-service/traces') return route.fulfill({ json: { items: [] } });
        if (path === '/service-apps/consumer-service/versions') return route.fulfill({ json: { items: [appVersion], published_version: 8 } });
        if (path === '/service-apps/consumer-service/traces') return route.fulfill({ json: { items: [trace] } });
        if (path === '/service-apps/consumer-service/simulate' && method === 'POST') {
            const body = request.postDataJSON();
            options.onSimulate?.(body);
            return route.fulfill({ json: simulatedTrace(body) });
        }
        if (path === '/service-apps/consumer-service/publish') {
            const body = request.postDataJSON();
            return route.fulfill({ json: { ...consumerApp, status: 'published', revision: body.revision + 1, published_version: 9, has_unpublished_changes: false } });
        }
        if (path === '/service-apps/consumer-service/status') {
            const body = request.postDataJSON();
            return route.fulfill({ json: { ...consumerApp, status: body.status, revision: body.revision + 1 } });
        }
        if (path === '/service-apps/consumer-service/rollback') {
            const body = request.postDataJSON();
            return route.fulfill({ json: { ...consumerApp, published_version: body.version, revision: body.revision + 1 } });
        }

        if (path === '/service-scenarios' && method === 'POST') {
            const body = request.postDataJSON() as any;
            options.onScenarioCreate?.(body);
            return route.fulfill({ status: 201, json: { ...scenarios[0], id: `scenario-${body.key}`, key: body.key, name: body.config.name, config: body.config, revision: 1, status: 'draft', published_version: null, published_config: null } });
        }
        if (path === '/service-scenarios') return route.fulfill({ json: { items: scenarios, total: scenarios.length } });
        const scenarioVersionMatch = path.match(/^\/service-scenarios\/([^/]+)\/versions$/);
        if (scenarioVersionMatch) {
            const scenario = scenarioByKey.get(scenarioVersionMatch[1]);
            return route.fulfill({
                json: {
                    items: scenario?.published_version
                        ? [{ id: `scenario-version-${scenario.key}`, version: scenario.published_version, config: scenario.config, source_version: null, created_by: 'admin', created_at: '2026-10-31T02:00:00Z', published: true }]
                        : [],
                    published_version: scenario?.published_version || null,
                },
            });
        }
        const scenarioSimulateMatch = path.match(/^\/service-scenarios\/([^/]+)\/simulate$/);
        if (scenarioSimulateMatch) {
            return route.fulfill({ json: simulatedTrace({ ...request.postDataJSON(), scenario_key: scenarioSimulateMatch[1] }) });
        }
        const scenarioMatch = path.match(/^\/service-scenarios\/([^/]+)$/);
        if (scenarioMatch) {
            const scenario = scenarioByKey.get(scenarioMatch[1]);
            if (!scenario) return route.fulfill({ status: 404, json: { detail: 'service_scenario_not_found' } });
            if (method === 'PUT') {
                const body = request.postDataJSON();
                return route.fulfill({ json: { ...scenario, config: body.config, revision: body.revision + 1 } });
            }
            return route.fulfill({ json: scenario });
        }

        if (path === '/agents') return route.fulfill({ json: [agent] });
        if (path === '/agents/catalog') return route.fulfill({ json: { items: [agent], total: 1, page: 1, page_size: 12 } });
        if (path === '/agents/memory-config-caps') {
            return route.fulfill({ json: { summary_enabled: true, memory_inject_enabled: true, memory_extract_enabled: true, memory_inject_max_items: 20, memory_search_limit: 5, memory_blacklist_auto_handoff: false } });
        }
        if (path === '/agents/agent-1/service-scenarios') {
            return route.fulfill({
                json: {
                    items: ['query-orders', 'track-logistics', 'order-rules'].map(key => {
                        const scenario = scenarioByKey.get(key)!;
                        return {
                            key,
                            name: scenario.name,
                            domain: scenario.domain,
                            status: scenario.status,
                            version: scenario.published_version,
                            handler_key: 'agent-complex',
                            handler_label: '复杂问题与异常解释',
                            binding: '复杂问题与查询失败时启用',
                            agent_version: 5,
                            configured_version: 5,
                            metrics: scenario.metrics,
                            volume: scenario.metrics?.volume || 0,
                        };
                    }),
                },
            });
        }
        if (path === '/agents/agent-1') return route.fulfill({ json: agent });
        if (path === '/agents/agent-1/evaluation-reports') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 1, versions: [] } });
        if (path === '/agents/agent-1/versions') return route.fulfill({ json: [] });
        if (path.startsWith('/model-gateway/catalog/')) return route.fulfill({ json: { items: [], total: 0 } });
        if (path === '/tools' || path === '/knowledge-bases') return route.fulfill({ json: [] });
        return route.fulfill({ json: {} });
    });
}
