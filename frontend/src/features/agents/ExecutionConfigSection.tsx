import { errorText, t } from '../../i18n/index';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { InputNumber, Select } from 'antd';
import {
  SUPPORTED_ENGINES,
  listExecutionCredentials,
  patchCodexConfig,
  patchEngine,
  patchReactConfig,
  readExecution,
  type AgentConfig,
  type ExecutionConfigFlags,
  type ExecutionCredentialSummary,
} from '../../shared/api/client';
import { Alert, Field } from '../../shared/components/ui';
import { useCatalogOptions } from '../models/useCatalogOptions';
import type { ModelResource } from '../models/ModelsPage';

/** Stable domain errors the execution endpoints answer with (03-technical-design.md §7.3). */
const EXECUTION_ERROR_CODES = [
  'execution_phase3_disabled', 'execution_engine_unavailable', 'execution_configuration_invalid',
  'execution_policy_unavailable', 'execution_credential_unavailable',
  'codex_credential_invalid', 'codex_model_profile_invalid',
];
/** Draft paths that belong to the execution contract; a 422 on these must stay pointable. */
const EXECUTION_PATHS = ['engine', 'react', 'codex', 'disabled_capabilities', 'max_model_rounds', 'model_profile_id', 'model_profile_version'];

/**
 * Recover the field paths from a strict-schema rejection. The shared error
 * mapping flattens a `422` detail list into generic copy, which would hide
 * *which* field the server rejected, so the execution section re-reads the
 * structured detail and names the contract path (FR-2, AC-2, M2).
 */
export function locateExecutionErrors(message: string): string[] {
  const raw = /^422 · ([\s\S]*)$/.exec(message || '')?.[1];
  if (!raw)
    return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  }
  catch {
    return [];
  }
  if (!Array.isArray(parsed))
    return [];
  return parsed.flatMap(item => {
    const location = (item as { loc?: unknown }).loc;
    if (!Array.isArray(location))
      return [];
    const path = location.filter(segment => typeof segment === 'string' && segment !== 'body' && segment !== 'config').join('.');
    if (!EXECUTION_PATHS.some(root => path === root || path.startsWith(`${root}.`)))
      return [];
    return [t('字段 {{v0}}：{{v1}}', { v0: path, v1: String((item as { msg?: unknown }).msg ?? '') })];
  });
}

/**
 * Blockers for the execution part of the current draft, each prefixed with the
 * field path the server contract uses. Operator-facing: a draft can only be
 * previewed or published when the engine is registered and the two legacy
 * React aliases agree (FR-2, AC-2, M2).
 */
export function executionIssues(config: AgentConfig): string[] {
  const view = readExecution(config);
  const issues: string[] = [];
  for (const field of view.conflicts) {
    issues.push(`${field} · react.${field} — ${t('{{v0}} 与 {{v1}} 取值不一致，请保留其中一处后再保存。', { v0: field, v1: `react.${field}` })}`);
  }
  if (!view.engineKnown) {
    issues.push(`engine.engine_id — ${t('所选 Engine 未注册或已停用，无法预览或发布。')}`);
  }
  return issues;
}

/** Friendly, business-facing name for a registered engine. The triple stays a wire identity only. */
function engineLabel(engineId: string): string {
  if (engineId === 'react')
    return t('对话模型（平台内置）');
  if (engineId === 'codex')
    return t('代码任务（命令行）');
  return engineId;
}

/**
 * The credential library can legitimately hold several versions of the same
 * named credential; the duplication is operational metadata, not a set of
 * different choices. Collapse by the fields a customer could distinguish so
 * the platform can bind one automatically without a confusing picker.
 */
function distinctCredentials(items: ExecutionCredentialSummary[] | null): ExecutionCredentialSummary[] {
  const seen = new Set<string>();
  return (items ?? []).filter(item => {
    if (item.status !== 'active' || !(item.allowed_engines ?? []).includes('codex'))
      return false;
    const key = `${item.name}|${item.credential_type}`;
    if (seen.has(key))
      return false;
    seen.add(key);
    return true;
  });
}

interface Props {
    config: AgentConfig;
    onChange: (config: AgentConfig) => void;
    /** Null previews an unsaved draft; the endpoint accepts both (FR-5). */
    agentId: string | null;
    /** Write permission gates editing only; preview rides on the read permission. */
    canEdit: boolean;
    busy: boolean;
    saveError?: string;
    /**
     * Deployment switches from `GET /agents/execution-config-flags` (03 §7.4).
     * Null while loading or after a failed read, which fails closed.
     */
    flags: ExecutionConfigFlags | null;
    /** Published ModelGateway chat profiles, already loaded by AgentsPage (issue #167). */
    profiles: ModelResource[] | null;
}
export function ExecutionConfigSection({ config, onChange, agentId, canEdit, busy, saveError, flags, profiles }: Props) {
    useTranslation();
    const view = readExecution(config);
    const issues = executionIssues(config);
    // R-25 declarative gating, synthesized from the raw pair per the FR-9
    // matrix (03 §7.4). The server remains the authorization boundary.
    const phase3Entries = !!flags && flags.execution_phase3_enabled;
    const phase3Off = !!flags && !flags.execution_phase3_enabled;
    const misconfigured = !!flags && flags.execution_phase3_enabled && !flags.execution_orchestrator_enabled;
    const engineOptions = SUPPORTED_ENGINES.map(item => ({ value: item.engine_id, label: engineLabel(item.engine_id) }));
    const codexReadOnly = !canEdit || busy || !phase3Entries;

    // Q2/Q3/Q5: neither the credential UUID nor the child PATH is a customer
    // field. The credential library is read only so a valid reference can be
    // bound automatically; its plaintext secret never reaches the browser.
    const [credentialItems, setCredentialItems] = useState<ExecutionCredentialSummary[] | null>(null);
    const codexActive = !!view.codex;
    useEffect(() => {
        let active = true;
        if (!codexActive || !canEdit) {
            setCredentialItems(null);
            return () => { active = false; };
        }
        void listExecutionCredentials()
            .then(response => { if (active) { setCredentialItems(response.items ?? []); } })
            .catch(() => { if (active) { setCredentialItems(null); } });
        return () => { active = false; };
    }, [codexActive, canEdit]);

    const credentialChoices = useMemo(() => distinctCredentials(credentialItems), [credentialItems]);
    const currentRef = view.codex?.credential_ref ?? null;
    // Bind the first platform-managed credential on entering the Codex lane so
    // publish validation (issue #165 L1) succeeds without asking the customer
    // to understand credential UUIDs. A chosen, still-valid reference is kept.
    // This is a hidden legacy-lane fallback for the published config, never a
    // customer-facing identity display: the gateway lane resolves the actual
    // runtime credential from the selected profile's connection at run time.
    useEffect(() => {
        if (!view.codex || !canEdit || busy || !credentialChoices.length)
            return;
        const currentValid = credentialChoices.some(item => item.credential_ref === currentRef);
        if (currentRef && currentValid)
            return;
        const first = credentialChoices[0];
        if (first && first.credential_ref !== currentRef)
            onChange(patchCodexConfig(config, { credential_ref: first.credential_ref }));
    }, [view.codex, canEdit, busy, credentialChoices, currentRef, config, onChange]);

    // A published chat profile is not automatically a runnable Codex profile:
    // the Gateway lane requires the primary connection to carry both a valid
    // execution credential reference and a bare HTTPS upstream address. The
    // backend enforces this at publish; filter the same chain here so the form
    // never offers a profile that can only end in codex_credential_invalid.
    const gatewayModels = useCatalogOptions('models', codexActive);
    const gatewayConnections = useCatalogOptions('connections', codexActive);
    const profileChoices = useMemo(() => {
        const modelById = new Map((gatewayModels.data ?? []).map(item => [item.id, item]));
        const connectionById = new Map((gatewayConnections.data ?? []).map(item => [item.id, item]));
        return (profiles ?? []).filter(item => {
            if (!item.enabled || !item.published_version || item.spec?.operation !== 'chat')
                return false;
            const model = modelById.get(String(item.spec?.model_id ?? ''));
            if (!model || model.spec?.tool_calling !== true)
                return false;
            const connection = connectionById.get(String(model.spec?.connection_id ?? ''));
            if (!connection)
                return false;
            const spec = connection.spec as Record<string, unknown>;
            const credentialRef = spec?.execution_credential_ref;
            const base = typeof spec?.codex_base_url === 'string' && spec.codex_base_url
                ? spec.codex_base_url : spec?.base_url;
            if (typeof credentialRef !== 'string' || !credentialRef.trim()
                || typeof base !== 'string' || !base.startsWith('https://'))
                return false;
            return true;
        });
    }, [profiles, gatewayModels.data, gatewayConnections.data]);
    const savePaths = locateExecutionErrors(saveError || '');
    const saveErrorIsExecution = EXECUTION_ERROR_CODES.some(code => (saveError || '').includes(code)) || savePaths.length > 0;
    const executionSaveError = saveErrorIsExecution ? (saveError || '') : '';
    const shown = [...issues, ...savePaths, ...(executionSaveError && !savePaths.length ? [executionSaveError] : [])]
        .filter(Boolean).map(errorText).join('\n');
    // A draft switch must not keep an error from a different agent.
    useEffect(() => { setCredentialItems(null); }, [agentId]);

    return <section id="agent-execution">
    <div className="agent-section-heading"><h2>{t('执行与能力')}</h2></div>
    <p className="agent-section-description">{t('选择 Agent 的运行方式；密钥、路径等细节由平台统一处理。')}</p>
    {phase3Off && <p role="status" className="agent-muted">{t('当前部署未启用代码执行能力，运行方式不可切换；平台对话模型不受影响。')}</p>}
    {misconfigured && <p role="status" className="agent-muted">{t('执行服务暂不可用，请联系运维核对部署配置。')}</p>}
    <Alert error={shown}/>
    <div className="agent-execution-card">
      {phase3Entries && <Field label={t('运行方式')}>
        <Select
          aria-label={t('运行方式')}
          value={view.engine.engine_id}
          options={engineOptions}
          disabled={!canEdit || busy}
          onChange={value => {
            const chosen = SUPPORTED_ENGINES.find(item => item.engine_id === value);
            if (chosen) onChange(patchEngine(config, chosen));
          }}
        />
      </Field>}
      {view.react && <>
        <Field label={t('最大模型轮次')}>
          <InputNumber aria-label={t('最大模型轮次')} min={1} max={30} precision={0} value={view.react.max_model_rounds} disabled={!canEdit || busy} onChange={value => onChange(patchReactConfig(config, { max_model_rounds: value || 1 }))}/>
        </Field>
        <p className="agent-execution-hint">{t('一次回答中最多调用模型的次数，范围 1–30。')}</p>
        <p className="agent-execution-hint">{t('模型方案在「模型配置」中选择。')}</p>
      </>}
      {view.codex && <>
        <Field label={t('Codex 模型方案（模型网关）')}>
          <Select
            aria-label={t('Codex 模型方案（模型网关）')}
            value={view.codex.model_profile_id ?? ''}
            disabled={codexReadOnly}
            options={[
              { value: '', label: t('未绑定（使用部署默认）') },
              ...profileChoices.map(item => ({
                value: item.id,
                label: `${item.name} · v${item.published_version}`,
              })),
              ...(view.codex.model_profile_id && !profileChoices.some(item => item.id === view.codex?.model_profile_id)
                ? [{ value: view.codex.model_profile_id, label: `${view.codex.model_profile_id}${t('（未加载或不可用）')}` }]
                : []),
            ]}
            onChange={value => {
              const chosen = profileChoices.find(item => item.id === value);
              onChange(patchCodexConfig(config, {
                model_profile_id: chosen?.id ?? null,
                model_profile_version: chosen?.published_version ?? null,
              }));
            }}
          />
        </Field>
        <p className="agent-execution-hint">{t('代码任务的模型与运行身份由平台统一配置，无需手动填写密钥或路径。')}</p>
        {profiles && gatewayModels.data && gatewayConnections.data && !profileChoices.length && <p role="status" className="agent-execution-hint">{t('暂无可用于代码任务的模型方案：模型网关连接尚未配置运行凭据或工具调用能力，请联系管理员。')}</p>}
      </>}
    </div>
  </section>;
}
