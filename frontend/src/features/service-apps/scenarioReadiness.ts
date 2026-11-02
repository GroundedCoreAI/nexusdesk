import type {
  ScenarioConfig,
  ScenarioUserDecision,
  ServiceApplicationReadiness,
  ServiceApplicationSummary,
  ServiceReadinessCheck,
  ServiceReadinessCheckSeverity,
  ServiceReadinessCheckStatus,
  ServiceReadinessState,
  ServiceScenarioReadiness,
  ServiceScenarioSummary,
} from '../../shared/api/client';
import { t } from '../../i18n/index';

export type ScenarioReadinessState = ServiceReadinessState;
export type ScenarioReadinessCheckStatus = ServiceReadinessCheckStatus;
export type ScenarioReadinessSeverity = ServiceReadinessCheckSeverity;
export type ScenarioReadinessCheck = ServiceReadinessCheck;

export interface ScenarioReadinessResult {
  status: ScenarioReadinessState;
  label: string;
  description: string;
  checks: ScenarioReadinessCheck[];
  counts: {
    pass: number;
    warning: number;
    blocked: number;
  };
  canPublish: boolean;
  canSimulate: boolean;
}

export interface ScenarioReadinessOptions {
  /**
   * Enabled provider identities loaded from the admin registry. The local
   * fallback treats an omitted set as "not checked", not as "nothing enabled",
   * so it can still render a business-only warning without false blocking.
   */
  availableProviderIdentities?: ReadonlySet<string>;
}

export function scenarioReadinessResultFromApi(
  readiness: ServiceScenarioReadiness,
): ScenarioReadinessResult {
  return {
    status: readiness.status,
    label: readinessLabel(readiness.status),
    description: readinessDescription(readiness.status),
    checks: readiness.checks,
    counts: { ...readiness.counts },
    canPublish: readiness.can_publish,
    canSimulate: readiness.can_simulate,
  };
}

interface HumanCapabilitySource {
  queue?: string | null;
  config?: Record<string, unknown>;
}

function readinessLabel(status: ScenarioReadinessState): string {
  if (status === 'ready') return t('可发布');
  if (status === 'simulate_only') return t('仅可模拟');
  return t('配置不完整');
}

function readinessDescription(status: ScenarioReadinessState): string {
  if (status === 'ready') return t('核心配置和客户触点已就绪，可以发布新版本。');
  if (status === 'simulate_only') return t('核心链路可以模拟体验，但仍有发布前需要处理的配置。');
  return t('存在阻断发布的配置缺失，请先完成必需项。');
}

const objectNameKeys: Record<string, string> = {
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
};

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function list<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function check(
  key: string,
  title: string,
  detail: string,
  status: ScenarioReadinessCheckStatus,
  severity: ScenarioReadinessSeverity,
): ScenarioReadinessCheck {
  return { key, title, detail, status, severity };
}

function passed(key: string, title: string, detail: string, severity: ScenarioReadinessSeverity = 'blocking') {
  return check(key, title, detail, 'pass', severity);
}

function blocked(key: string, title: string, detail: string) {
  return check(key, title, detail, 'blocked', 'blocking');
}

function warning(key: string, title: string, detail: string, severity: ScenarioReadinessSeverity = 'warning') {
  return check(key, title, detail, 'warning', severity);
}

function objectName(type?: string | null): string {
  const normalized = text(type).toLocaleLowerCase().replace(/-/g, '_');
  return t(objectNameKeys[normalized] || '业务对象');
}

function queueOf(source: HumanCapabilitySource): string {
  if (text(source.queue)) return text(source.queue);
  const config = source.config || {};
  for (const key of ['queue', 'handoff_queue', 'handoff_target', 'assignee_group']) {
    const value = text(config[key]);
    if (value) return value;
  }
  return '';
}

function requiresBusinessObject(config: ScenarioConfig | null, object: ScenarioConfig['object']): boolean {
  if (config?.template === 'query' || config?.template === 'action') return true;
  return !!object && (object.required || object.mode === 'required' || object.mode === 'multiple');
}

function industryPackMetadata(config: ScenarioConfig | null): Record<string, unknown> | null {
  if (!config?.config || !Object.prototype.hasOwnProperty.call(config.config, 'industry_pack')) {
    return null;
  }
  const value = config.config.industry_pack;
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function providerRequirements(config: ScenarioConfig | null): Set<string> {
  const requirements = new Set<string>();
  if (!config) return requirements;
  if (config.object && text(config.object.provider)) {
    requirements.add(`object:${text(config.object.provider)}`);
  }
  for (const handler of list(config.handlers)) {
    if (handler.enabled === false) continue;
    if (text(handler.tool)) requirements.add(`tool:${text(handler.tool)}`);
    const queue = queueOf(handler);
    if (queue && (handler.type === 'human' || !!queue)) {
      requirements.add(`human_queue:${queue}`);
    }
  }
  return requirements;
}

function applicationScenarioEnabled(
  application: ServiceApplicationSummary,
  scenario: ServiceScenarioSummary,
): { linked: boolean; enabled: boolean } {
  const references = list(application.config?.scenarios);
  const reference = references.find(item => item.key === scenario.key);
  return {
    linked: !!reference,
    enabled: !!reference && reference.enabled !== false,
  };
}

function evaluateApplicationLink(
  application: ServiceApplicationSummary | null | undefined,
  scenario: ServiceScenarioSummary,
): ScenarioReadinessCheck {
  if (!application) {
    return blocked(
      'application-link',
      t('应用关联与启用'),
      t('场景尚未关联服务应用，无法进入客户服务链路。'),
    );
  }

  const link = applicationScenarioEnabled(application, scenario);
  if (!link.linked) {
    return blocked(
      'application-link',
      t('应用关联与启用'),
      t('场景尚未加入「{{v0}}」，客户无法从该应用进入服务。', { v0: application.name }),
    );
  }
  if (!link.enabled) {
    return blocked(
      'application-link',
      t('应用关联与启用'),
      t('场景在应用内处于停用状态，客户不会看到该服务。'),
    );
  }

  return passed(
    'application-link',
    t('应用关联与启用'),
    t('已加入「{{v0}}」并在应用内启用。', { v0: application.name }),
  );
}

function evaluateBusinessObject(
  config: ScenarioConfig | null,
): ScenarioReadinessCheck {
  const object = config?.object || null;
  const required = requiresBusinessObject(config, object);

  if (!object) {
    if (required) {
      return blocked(
        'business-object',
        t('必填业务对象'),
        t('该场景需要业务对象，但尚未明确客户要选择或提供哪类业务对象。'),
      );
    }
    return passed(
      'business-object',
      t('必填业务对象'),
      t('咨询型场景无需业务对象，可直接通过知识或固定应答处理。'),
    );
  }

  if (!text(object.type)) {
    return blocked(
      'business-object',
      t('必填业务对象'),
      t('业务对象尚未选择，客户无法进入对应的查询或办理流程。'),
    );
  }

  if (!text(object.provider)) {
    return blocked(
      'business-object',
      t('必填业务对象'),
      t('已选择{{v0}}对象，但尚未明确业务数据来源。', { v0: objectName(object.type) }),
    );
  }

  return passed(
    'business-object',
    t('必填业务对象'),
    t('已配置{{v0}}对象，并明确业务数据来源。', { v0: objectName(object.type) }),
  );
}

function evaluateFacts(
  config: ScenarioConfig | null,
): ScenarioReadinessCheck {
  const facts = list(config?.facts);
  if (!facts.length) {
    if (config?.template === 'query' || config?.template === 'action') {
      return blocked(
        'business-facts',
        t('业务事实字段'),
        t('查询或办理场景尚未配置业务事实，客户无法看到判断所需的关键信息。'),
      );
    }
    return passed(
      'business-facts',
      t('业务事实字段'),
      t('咨询型场景无需展示业务事实。'),
      'info',
    );
  }

  const invalid = facts.filter(item => !text(item.key) || !text(item.label) || !text(item.source));
  if (invalid.length) {
    return blocked(
      'business-facts',
      t('业务事实字段'),
      t('有 {{v0}} 项业务事实缺少业务名称或数据来源，请补全后再发布。', { v0: invalid.length }),
    );
  }

  return passed(
    'business-facts',
    t('业务事实字段'),
    t('已配置 {{v0}} 项业务事实，客户可看到判断所需的信息。', { v0: facts.length }),
  );
}

function evaluateHandlers(config: ScenarioConfig | null): ScenarioReadinessCheck {
  const enabled = list(config?.handlers).filter(item => item.enabled !== false);
  if (!enabled.length) {
    return blocked(
      'handlers',
      t('处理能力'),
      t('场景尚未启用任何处理能力，客户进入后无法得到处理结果。'),
    );
  }
  return passed(
    'handlers',
    t('处理能力'),
    t('已启用 {{v0}} 项处理能力，可承接客户问题。', { v0: enabled.length }),
  );
}

function evaluateActionConfirmation(config: ScenarioConfig | null): ScenarioReadinessCheck {
  if (config?.template !== 'action') {
    return passed(
      'action-confirmation',
      t('办理确认'),
      t('当前场景不涉及业务办理，无需提交操作确认。'),
      'info',
    );
  }

  const decisions = list(config.decisions);
  const confirmation = decisions.find((item: ScenarioUserDecision) => item.kind === 'confirm_action');
  if (!confirmation) {
    return blocked(
      'action-confirmation',
      t('办理确认'),
      t('办理型场景尚未配置操作确认，客户可能在未确认影响的情况下提交业务。'),
    );
  }

  const safe = confirmation.required !== false && confirmation.confirm !== false && confirmation.allow_skip !== true;
  if (!safe) {
    return warning(
      'action-confirmation',
      t('办理确认'),
      t('操作确认尚未设置为必填且不可跳过，请确认客户能够明确知晓办理影响。'),
    );
  }

  return passed(
    'action-confirmation',
    t('办理确认'),
    t('办理前会要求客户确认影响和操作内容。'),
  );
}

function evaluateFallback(config: ScenarioConfig | null): ScenarioReadinessCheck {
  const handlers = list(config?.handlers);
  const enabledKeys = new Set(handlers.filter(item => item.enabled !== false).map(item => item.key));
  const fallback = [...new Set(list(config?.fallback_order).map(text).filter(Boolean))];

  if (!fallback.length) {
    return blocked(
      'fallback-order',
      t('异常兜底顺序'),
      t('兜底顺序为空，处理能力不可用时无法确定下一承接方式。'),
    );
  }

  const valid = fallback.filter(key => enabledKeys.has(key));
  const invalid = fallback.filter(key => !enabledKeys.has(key));
  if (!valid.length) {
    return blocked(
      'fallback-order',
      t('异常兜底顺序'),
      t('兜底顺序中的承接方式均不可用，请重新编排异常处理路径。'),
    );
  }
  if (invalid.length) {
    return warning(
      'fallback-order',
      t('异常兜底顺序'),
      t('兜底顺序中有 {{v0}} 项承接方式已失效，发布前请重新编排。', { v0: invalid.length }),
    );
  }

  return passed(
    'fallback-order',
    t('异常兜底顺序'),
    t('已配置 {{v0}} 级兜底顺序，异常时可继续升级处理。', { v0: valid.length }),
  );
}

function evaluateHumanHandoff(
  application: ServiceApplicationSummary | null | undefined,
  config: ScenarioConfig | null,
): ScenarioReadinessCheck {
  const handlers = list(config?.handlers).filter(item => item.enabled !== false);
  const humanHandlers = handlers.filter(item => item.type === 'human');
  const humanCapabilities = list(application?.config?.capabilities)
    .filter(item => item.enabled !== false && item.type === 'human');
  const explicitHandoff = list(config?.decisions).some(item => item.kind === 'handoff');
  const humanInFallback = humanHandlers.some(item => list(config?.fallback_order).includes(item.key));
  const sources: HumanCapabilitySource[] = [...humanHandlers, ...humanCapabilities];

  if (!sources.length) {
    if (explicitHandoff) {
      return blocked(
        'human-handoff',
        t('人工承接'),
        t('已设置转人工决策，但尚未配置可接管的人工队列或承接方式。'),
      );
    }
    return warning(
      'human-handoff',
      t('人工承接'),
      t('尚未配置人工承接，复杂问题暂时无法升级给人工坐席。'),
    );
  }

  const withQueue = sources.filter(item => !!queueOf(item));
  if (withQueue.length) {
    return passed(
      'human-handoff',
      t('人工承接'),
      t('已配置明确的人工承接方式，复杂问题可以转交人工处理。'),
    );
  }

  if (explicitHandoff || humanInFallback) {
    return blocked(
      'human-handoff',
      t('人工承接'),
      t('服务路径包含转人工，但尚未指定人工队列或承接方式。'),
    );
  }

  return warning(
    'human-handoff',
    t('人工承接'),
    t('已添加人工能力，但尚未指定人工队列或承接方式。'),
  );
}

function evaluateCustomerChannels(application: ServiceApplicationSummary | null | undefined): ScenarioReadinessCheck {
  if (!application) {
    return warning(
      'customer-channels',
      t('客户渠道'),
      t('尚未关联服务应用，无法确认客户从哪些渠道进入服务。'),
    );
  }

  const channels = list(application.config?.channels)
    .filter(item => item.status !== 'disabled');
  if (!channels.length) {
    return warning(
      'customer-channels',
      t('客户渠道'),
      t('尚未接入可用客户渠道，可以先用模拟体验，但暂不能对外发布。'),
    );
  }

  return passed(
    'customer-channels',
    t('客户渠道'),
    t('已接入 {{v0}} 个客户渠道。', { v0: channels.length }),
  );
}

function evaluatePublication(scenario: ServiceScenarioSummary): ScenarioReadinessCheck {
  const publishedVersion = scenario.published_version;
  if (scenario.status === 'offline') {
    return warning(
      'publication',
      t('发布状态'),
      t('场景当前已下线，重新发布后才会对客户生效。'),
      'info',
    );
  }

  if (scenario.has_unpublished_changes) {
    return warning(
      'publication',
      t('发布状态'),
      publishedVersion
        ? t('已发布 v{{v0}}，但当前配置存在未发布修改；客户仍在使用已发布版本。', { v0: publishedVersion })
        : t('当前配置尚未发布；完成检查后会生成首个客户可用版本。'),
      'info',
    );
  }

  if (publishedVersion) {
    return passed(
      'publication',
      t('发布状态'),
      t('当前配置已发布为 v{{v0}}，与客户使用版本一致。', { v0: publishedVersion }),
      'info',
    );
  }

  return passed(
    'publication',
    t('发布状态'),
    t('当前场景尚未发布；检查通过后可以发布首个客户可用版本。'),
    'info',
  );
}

function evaluateTemplateMaturity(
  application: ServiceApplicationSummary | null | undefined,
  config: ScenarioConfig | null,
): ScenarioReadinessCheck | null {
  const metadata = industryPackMetadata(config);
  if (metadata === null) return null;
  const maturity = text(metadata.maturity).toLocaleLowerCase();
  if (maturity === 'alpha') {
    return blocked(
      'template-maturity',
      t('模板成熟度'),
      t('该服务模板仍在灰度验证中，暂不能发布给客户。'),
    );
  }
  if (maturity === 'beta') {
    const canary = list(application?.config?.channels)
      .some(item => item.status === 'canary');
    if (!canary) {
      return blocked(
        'template-maturity',
        t('模板成熟度'),
        t('该服务模板处于公测阶段，请先配置灰度客户渠道再发布。'),
      );
    }
    return passed(
      'template-maturity',
      t('模板成熟度'),
      t('已配置灰度渠道，可在受控客户范围内验证该服务模板。'),
      'info',
    );
  }
  if (!maturity) {
    return warning(
      'template-maturity',
      t('模板成熟度'),
      t('该服务模板尚未标记成熟度，请确认发布范围后再继续。'),
    );
  }
  return passed(
    'template-maturity',
    t('模板成熟度'),
    t('该服务模板已达到正式发布标准。'),
    'info',
  );
}

function evaluateProviderCapability(
  config: ScenarioConfig | null,
  availableProviderIdentities?: ReadonlySet<string>,
): ScenarioReadinessCheck | null {
  if (industryPackMetadata(config) === null) return null;
  const required = providerRequirements(config);
  if (!required.size) {
    return passed(
      'provider-capability',
      t('执行能力接入'),
      t('该服务模板不依赖外部业务数据或执行能力。'),
      'info',
    );
  }
  if (!availableProviderIdentities) {
    return warning(
      'provider-capability',
      t('执行能力接入'),
      t('该服务模板依赖 {{v0}} 项业务数据能力，请确认已在行业能力中完成接入。', {
        v0: required.size,
      }),
    );
  }
  const missing = [...required].filter(identity => !availableProviderIdentities.has(identity));
  if (missing.length) {
    return blocked(
      'provider-capability',
      t('执行能力接入'),
      t('该场景需要接入 {{v0}} 项业务数据能力，尚未完成配置。', { v0: missing.length }),
    );
  }
  return passed(
    'provider-capability',
    t('执行能力接入'),
    t('已接入 {{v0}} 项业务数据能力。', { v0: required.size }),
    'info',
  );
}

export function evaluateScenarioReadiness(
  application: ServiceApplicationSummary | null | undefined,
  scenario: ServiceScenarioSummary,
  options: ScenarioReadinessOptions = {},
): ScenarioReadinessResult {
  const config = scenario.config || scenario.published_config || null;
  const checks: ScenarioReadinessCheck[] = [
    evaluateApplicationLink(application, scenario),
    evaluateBusinessObject(config),
    evaluateFacts(config),
    evaluateHandlers(config),
    evaluateFallback(config),
    evaluateActionConfirmation(config),
    evaluateHumanHandoff(application, config),
    evaluateCustomerChannels(application),
    evaluatePublication(scenario),
  ];
  const optionalChecks = [
    evaluateTemplateMaturity(application, config),
    evaluateProviderCapability(config, options.availableProviderIdentities),
  ];
  checks.push(...optionalChecks.filter((item): item is ScenarioReadinessCheck => item !== null));

  const hasBlocking = checks.some(item => item.status !== 'pass' && item.severity === 'blocking');
  const hasWarning = checks.some(item => item.status !== 'pass' && item.severity === 'warning');
  const status: ScenarioReadinessState = hasBlocking ? 'blocked' : hasWarning ? 'simulate_only' : 'ready';

  return {
    status,
    label: readinessLabel(status),
    description: readinessDescription(status),
    checks,
    counts: {
      pass: checks.filter(item => item.status === 'pass').length,
      warning: checks.filter(item => item.status === 'warning').length,
      blocked: checks.filter(item => item.status === 'blocked').length,
    },
    canPublish: status === 'ready',
    canSimulate: status !== 'blocked',
  };
}

export interface ApplicationReleaseReadiness {
  items: Array<{
    scenario: ServiceScenarioSummary;
    result: ScenarioReadinessResult;
  }>;
  readyCount: number;
  blockedCount: number;
  simulateOnlyCount: number;
  canPublish: boolean;
}

export function evaluateApplicationReleaseReadiness(
  application: ServiceApplicationSummary | null | undefined,
  scenarios: ServiceScenarioSummary[],
  options: ScenarioReadinessOptions = {},
): ApplicationReleaseReadiness {
  const items = scenarios.map(scenario => ({
    scenario,
    result: evaluateScenarioReadiness(application, scenario, options),
  }));
  const readyCount = items.filter(item => item.result.status === 'ready').length;
  const blockedCount = items.filter(item => item.result.status === 'blocked').length;
  const simulateOnlyCount = items.filter(item => item.result.status === 'simulate_only').length;

  return {
    items,
    readyCount,
    blockedCount,
    simulateOnlyCount,
    canPublish: items.length > 0 && readyCount === items.length && blockedCount === 0 && simulateOnlyCount === 0,
  };
}

export function applicationReleaseGateMessage(readiness: ApplicationReleaseReadiness): string {
  if (!readiness.items.length) return t('当前应用还没有可发布的场景。');
  if (readiness.blockedCount > 0 && readiness.simulateOnlyCount > 0) {
    return t('有 {{v0}} 个场景存在发布阻断项，另有 {{v1}} 个场景仍有发布前待处理项，完成检查后才能发布。', {
      v0: readiness.blockedCount,
      v1: readiness.simulateOnlyCount,
    });
  }
  if (readiness.blockedCount > 0) {
    return t('有 {{v0}} 个场景存在发布阻断项，完成检查后才能发布。', { v0: readiness.blockedCount });
  }
  if (readiness.simulateOnlyCount > 0) {
    return t('有 {{v0}} 个场景仍有发布前待处理项，完成检查后才能发布。', { v0: readiness.simulateOnlyCount });
  }
  return t('全部场景已通过完整性检查，可以发布新版本。');
}

/** Build the application release message from the server-side readiness result. */
export function applicationReadinessGateMessage(readiness: ServiceApplicationReadiness): string {
  const blockedCount = readiness.scenarios.filter(item => item.status === 'blocked').length;
  const simulateOnlyCount = readiness.scenarios.filter(item => item.status === 'simulate_only').length;
  if (!readiness.scenarios.length) return t('当前应用还没有可发布的场景。');
  if (blockedCount > 0 && simulateOnlyCount > 0) {
    return t('有 {{v0}} 个场景存在发布阻断项，另有 {{v1}} 个场景仍有发布前待处理项，完成检查后才能发布。', {
      v0: blockedCount,
      v1: simulateOnlyCount,
    });
  }
  if (blockedCount > 0) {
    return t('有 {{v0}} 个场景存在发布阻断项，完成检查后才能发布。', { v0: blockedCount });
  }
  if (simulateOnlyCount > 0) {
    return t('有 {{v0}} 个场景仍有发布前待处理项，完成检查后才能发布。', { v0: simulateOnlyCount });
  }
  if (readiness.can_publish) {
    return t('全部场景已通过完整性检查，可以发布新版本。');
  }
  return readinessDescription(readiness.status);
}
