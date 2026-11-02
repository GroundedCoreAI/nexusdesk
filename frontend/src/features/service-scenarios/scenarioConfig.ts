import type {
  ApplicationServiceCategory,
  ScenarioConfig,
  ScenarioHandlerType,
  ScenarioObjectMode,
  ScenarioStatus,
  ScenarioTemplate,
  ServiceApplicationConfig,
  ServiceApplicationSummary,
  ServiceScenarioSummary,
} from '../../shared/api/client';

export interface EffectiveServiceCategory extends ApplicationServiceCategory {
  scenarioCount: number;
}

export interface NewScenarioInput {
  name: string;
  description?: string;
  template?: ScenarioTemplate;
  domain?: string;
  category?: string;
  objectType?: string;
  reply?: string;
}

export function newScenarioConfig(input: NewScenarioInput): ScenarioConfig {
  const template = input.template || 'consult';
  const objectType = input.objectType?.trim() || 'order';
  const objectRequired = template !== 'consult';
  const handlerType: ScenarioHandlerType = template === 'query'
    ? 'query'
    : template === 'action'
      ? 'action'
      : 'direct';
  const handlerKey = template === 'query' ? 'business-query' : template === 'action' ? 'business-action' : 'direct-reply';
  const handlerLabel = template === 'query' ? '业务查询' : template === 'action' ? '业务办理' : '固定应答';
  const reply = input.reply?.trim() || `您好，这里是${input.name.trim()}。请告诉我您需要处理的问题。`;

  return {
    schema_version: 'v1',
    name: input.name.trim(),
    description: input.description?.trim() || '',
    domain: input.domain?.trim() || '客户服务',
    category: input.category?.trim() || '通用服务',
    template,
    channels: ['web'],
    entries: [
      {
        key: 'natural-language',
        type: 'natural_language',
        label: '自然语言',
        description: input.name.trim(),
        enabled: true,
        config: {},
      },
      {
        key: 'service-catalog',
        type: 'service_catalog',
        label: '服务目录',
        description: '从服务目录进入',
        enabled: true,
        config: {},
      },
    ],
    facts: [],
    object: objectRequired
      ? {
          type: objectType,
          provider: 'demo_provider',
          required: true,
          mode: 'required',
          candidate_strategy: {
            sort: 'recent_desc',
            limit: 5,
            filters: [],
            empty_state: '没有找到可用的业务对象。',
            unavailable_state: '业务对象暂时不可用，请稍后重试或转人工。',
          },
          permission_policy: 'customer_scope',
          config: {},
        }
      : null,
    decisions: template === 'action'
      ? [{
          key: 'confirm-action',
          kind: 'confirm_action',
          label: '确认提交',
          required: true,
          options: [],
          allow_free_text: false,
          allow_skip: false,
          confirm: true,
          correctable: true,
          when: {},
        }]
      : [],
    recommendations: [],
    handlers: [{
      key: handlerKey,
      type: handlerType,
      label: handlerLabel,
      priority: 10,
      enabled: true,
      when: { requires_object: objectRequired },
      agent_id: null,
      agent_version: null,
      agent_name: null,
      queue: null,
      tool: template === 'query' ? 'business_query' : template === 'action' ? 'business_action' : null,
      reply: handlerType === 'direct' ? reply : null,
      config: {},
    }],
    fallback_order: [handlerKey],
    matching: {
      keywords: [input.name.trim()],
      intents: [],
      negative_keywords: [],
    },
    config: {},
  };
}

export function scenarioStatusLabel(status?: ScenarioStatus): string {
  return {
    draft: '草稿',
    review: '待发布',
    published: '已发布',
    offline: '已下线',
  }[status || 'draft'];
}

export function scenarioTone(status?: ScenarioStatus) {
  return status === 'published' ? 'published' : status === 'review' ? 'review' : 'draft';
}

export function handlerTypeLabel(type: ScenarioHandlerType): string {
  return {
    direct: 'Direct',
    knowledge: '知识检索',
    query: '业务查询',
    action: '业务办理',
    agent: 'Agent',
    human: '人工',
    tracking: '进度跟踪',
  }[type];
}

export function objectModeLabel(mode: ScenarioObjectMode): string {
  return {
    none: '无需对象',
    implicit: '隐式对象',
    optional: '可选对象',
    required: '必需对象',
    multiple: '多对象',
  }[mode];
}

export function objectTypeLabel(type?: string | null): string {
  const normalized = (type || '').trim().toLocaleLowerCase().replace(/-/g, '_');
  if (!normalized) return '业务对象';
  return {
    order: '订单',
    invoice: '发票',
    logistics: '物流',
    refund: '退款',
    after_sales: '售后单',
    aftersales: '售后单',
    member: '会员',
    account: '账户',
    ticket: '工单',
    complaint: '投诉',
    address: '收货地址',
    transaction: '交易',
    payment: '支付记录',
    service_record: '服务记录',
  }[normalized] || type || '业务对象';
}

export function scenarioTemplateLabel(template?: ScenarioTemplate): string {
  return {
    consult: '咨询',
    query: '查询',
    action: '办理',
  }[template || 'consult'];
}

export function businessToolLabel(tool?: string | null): string {
  if (!tool) return '';
  return {
    order_status: '读取订单状态',
    logistics_status: '读取物流进度',
    invoice_status: '读取发票状态',
    create_after_sales: '提交售后申请',
    propose_ticket: '创建服务工单',
  }[tool] || tool.replace(/_/g, ' ');
}

export function handlerProductHint(handler: { type: ScenarioHandlerType; tool?: string | null; queue?: string | null }): string {
  if (handler.type === 'query') return businessToolLabel(handler.tool) || '读取业务系统数据';
  if (handler.type === 'action') return businessToolLabel(handler.tool) || '提交业务办理';
  if (handler.type === 'agent') return '复杂问题由 Agent 继续理解与推进';
  if (handler.type === 'human') return handler.queue ? '携带完整上下文转人工' : '转人工继续处理';
  if (handler.type === 'tracking') return '查询后续处理进度';
  if (handler.type === 'knowledge') return '检索企业知识后回答';
  return '按固定服务话术即时回复';
}

export function serviceResultLabel(status?: string | null): string {
  switch ((status || '').toLocaleLowerCase()) {
    case 'needs_input':
    case 'clarify':
    case 'awaiting_confirmation':
      return '等待补充或确认';
    case 'succeeded':
    case 'success':
    case 'completed':
    case 'resolved':
      return '处理完成';
    case 'failed':
    case 'error':
    case 'rejected':
    case 'denied':
      return '处理失败';
    case 'handoff':
    case 'handed_off':
      return '已转人工';
    case 'processing':
    case 'pending':
    case 'deferred':
    case 'tracking':
      return '处理中';
    default:
      return '结果待确认';
  }
}

export function resolveScenarioConfig(scenario?: ServiceScenarioSummary | null): ScenarioConfig | null {
  return scenario?.config || scenario?.published_config || null;
}

export function enabledApplicationScenarios(
  application: ServiceApplicationSummary | null | undefined,
  scenarios: ServiceScenarioSummary[],
) {
  if (!application) return [];
  const byKey = new Map(scenarios.map(item => [item.key, item]));
  return application.config.scenarios
    .filter(reference => reference.enabled !== false)
    .map(reference => {
      const scenario = byKey.get(reference.key);
      return scenario ? { reference, scenario } : null;
    })
    .filter((item): item is { reference: ServiceApplicationConfig['scenarios'][number]; scenario: ServiceScenarioSummary } => !!item);
}

export function applicationScenarioItems(
  application: ServiceApplicationSummary | null | undefined,
  scenarios: ServiceScenarioSummary[],
) {
  if (!application) return [];
  const byKey = new Map(scenarios.map(item => [item.key, item]));
  return application.config.scenarios
    .map(reference => byKey.get(reference.key))
    .filter((item): item is ServiceScenarioSummary => !!item);
}

export function effectiveServiceCategories(
  application: ServiceApplicationSummary | null | undefined,
  scenarios: ServiceScenarioSummary[],
): EffectiveServiceCategory[] {
  const scopedScenarios = application
    ? applicationScenarioItems(application, scenarios)
    : scenarios;
  const counts = new Map<string, number>();
  for (const scenario of scopedScenarios) {
    const name = scenario.config.category || scenario.config.domain || '其他服务';
    counts.set(name, (counts.get(name) || 0) + 1);
  }

  const configured = [...(application?.config.service_categories || [])]
    .sort((left, right) => left.order - right.order || left.name.localeCompare(right.name));
  const result: EffectiveServiceCategory[] = [];
  const seen = new Set<string>();
  for (const category of configured) {
    if (seen.has(category.name)) continue;
    seen.add(category.name);
    result.push({ ...category, scenarioCount: counts.get(category.name) || 0 });
  }

  // Legacy applications did not persist a catalog. Preserve their existing
  // scenario categories instead of hiding scenes behind an empty selector.
  for (const scenario of scopedScenarios) {
    const name = scenario.config.category || scenario.config.domain || '其他服务';
    if (seen.has(name)) continue;
    seen.add(name);
    result.push({
      name,
      order: (result.length + 1) * 10,
      scenarioCount: counts.get(name) || 0,
    });
  }
  return result;
}

export function groupScenariosByCategory<T extends { category: string }>(
  scenes: T[],
  categories: EffectiveServiceCategory[],
) {
  const groups = new Map<string, T[]>();
  for (const scene of scenes) {
    const items = groups.get(scene.category) || [];
    items.push(scene);
    groups.set(scene.category, items);
  }
  const ordered = categories
    .map(category => [category.name, groups.get(category.name) || []] as const)
    .filter(([, items]) => items.length > 0);
  const known = new Set(categories.map(category => category.name));
  for (const [name, items] of groups) {
    if (!known.has(name)) ordered.push([name, items]);
  }
  return ordered;
}

export function withApplicationScenario(
  config: ServiceApplicationConfig,
  key: string,
  update: Partial<ServiceApplicationConfig['scenarios'][number]> = {},
): ServiceApplicationConfig {
  const exists = config.scenarios.some(item => item.key === key);
  return {
    ...config,
    scenarios: exists
      ? config.scenarios.map(item => item.key === key ? { ...item, ...update } : item)
      : [...config.scenarios, { key, version: null, enabled: true, ...update }],
  };
}

export function withoutApplicationScenario(config: ServiceApplicationConfig, key: string): ServiceApplicationConfig {
  return { ...config, scenarios: config.scenarios.filter(item => item.key !== key) };
}

export function defaultExecutionStages(config: ServiceApplicationConfig) {
  return config.default_execution_order.length
    ? config.default_execution_order
    : ['deterministic', 'action', 'agent', 'human'];
}

export function formatTraceValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}
