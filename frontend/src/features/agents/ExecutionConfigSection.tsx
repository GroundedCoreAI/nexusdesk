import { errorText, t } from '../../i18n/index';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, InputNumber, Tag } from 'antd';
import {
  DEFAULT_ENGINE,
  patchReactConfig,
  previewExecution,
  readExecution,
  toggleDisabledCapability,
  type AgentConfig,
  type ExecutionCapabilityName,
  type ExecutionConfigFlags,
  type ExecutionPreview,
} from '../../shared/api/client';
import { Alert, Field } from '../../shared/components/ui';
import { CapabilityPreview } from './CapabilityPreview';

/** Stable domain errors the execution endpoints answer with (03-technical-design.md §7.3). */
const EXECUTION_ERROR_CODES = ['execution_phase3_disabled', 'execution_engine_unavailable', 'execution_configuration_invalid', 'execution_policy_unavailable'];
/** Draft paths that belong to the execution contract; a 422 on these must stay pointable. */
const EXECUTION_PATHS = ['engine', 'react', 'disabled_capabilities', 'max_model_rounds', 'model_profile_id', 'model_profile_version'];

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
 * field path the server contract uses, so an alias conflict or an unregistered
 * triple can be pointed at instead of being silently resolved (FR-2, AC-2, M2).
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
     * Null while loading or after a failed read, which fails closed: the Phase
     * 3 specific editing entries stay hidden. They only drive UI visibility —
     * the server remains the authorization boundary (03 §8, R-25).
     */
    flags: ExecutionConfigFlags | null;
}
export function ExecutionConfigSection({ config, onChange, agentId, canEdit, busy, saveError, flags }: Props) {
    useTranslation();
    const [preview, setPreview] = useState<ExecutionPreview | null>(null);
    const [previewedConfig, setPreviewedConfig] = useState('');
    const [previewError, setPreviewError] = useState('');
    const [previewing, setPreviewing] = useState(false);
    const view = readExecution(config);
    const issues = executionIssues(config);
    // R-25 declarative gating, synthesized from the raw pair per the FR-9
    // matrix (03 §7.4): `execution_phase3_enabled` decides whether the Phase 3
    // editing entries exist at all (null fails closed); the pair
    // on+orchestrator-off is a deployment misconfiguration that keeps the
    // read-only view but must warn instead of pretending success.
    const phase3Entries = !!flags && flags.execution_phase3_enabled;
    const phase3Off = !!flags && !flags.execution_phase3_enabled;
    const misconfigured = !!flags && flags.execution_phase3_enabled && !flags.execution_orchestrator_enabled;
    const engineText = `${view.engine.engine_id} / ${view.engine.protocol_id} / ${view.engine.adapter_version}`;
    const previewPaths = locateExecutionErrors(previewError);
  const savePaths = locateExecutionErrors(saveError || '');
  const saveErrorIsExecution = EXECUTION_ERROR_CODES.some(code => (saveError || '').includes(code)) || savePaths.length > 0;
  const executionSaveError = saveErrorIsExecution ? (saveError || '') : '';
  // Each part is translated on its own: the shared mapping only recognises a
  // message that is exactly one stable code, so a joined block must never be
  // handed to it as a whole.
  const shown = [...issues, ...previewPaths, ...(executionSaveError && !previewPaths.length ? [executionSaveError] : [])].filter(Boolean).map(errorText).join('\n');
    // A preview belongs to the draft it was taken from, so it does not survive
    // a switch to another agent.
    useEffect(() => { setPreview(null); setPreviewError(''); setPreviewedConfig(''); }, [agentId]);
    async function runPreview() {
        setPreviewing(true);
        setPreviewError('');
        try {
            setPreview(await previewExecution(agentId, config));
            setPreviewedConfig(JSON.stringify(config));
        }
        catch (error) {
            setPreview(null);
            setPreviewedConfig('');
            setPreviewError(error instanceof Error ? error.message : t('预览能力失败，请重试。'));
        }
        finally {
            setPreviewing(false);
        }
    }
    return <section id="agent-execution">
    <div className="agent-section-heading"><h2>{t('执行与能力')}</h2>{phase3Entries && <Button onClick={runPreview} loading={previewing}>{t('预览能力')}</Button>}</div>
    <p className="agent-section-description">{t('运行 Engine 与能力由服务端注册表和策略决定，这里只能查看与收窄。')}</p>
    {phase3Off && <p role="status" className="agent-muted">{t('当前部署未启用 Phase 3 执行能力，能力预览与能力收窄入口已隐藏；React 配置与历史记录不受影响。')}</p>}
    {misconfigured && <p role="status" className="agent-muted">{t('部署配置错误：execution_phase3_enabled 已启用而 execution_orchestrator_enabled 未启用，能力预览会失败，请联系运维核对配置。')}</p>}
    <Alert error={shown || previewError}/>
    <div className="agent-setting-card">
      <h3 className="agent-memory-group">{t('执行配置')}</h3>
      <Field label={t('Engine 三元组')}>
        <div className="agent-execution-engine">
          <input readOnly value={engineText} aria-label={t('Engine 三元组')}/>
          <Tag color={view.engineKnown ? 'green' : 'red'}>{view.engineKnown ? t('已注册') : t('未注册')}</Tag>
        </div>
      </Field>
      <p className="agent-muted">{view.engineKnown ? t('缺省即 {{v0}}，旧 Agent 无需重新发布。', { v0: `${DEFAULT_ENGINE.engine_id}/${DEFAULT_ENGINE.protocol_id}/${DEFAULT_ENGINE.adapter_version}` }) : t('所选 Engine 未注册或已停用，无法预览或发布。')}</p>
    </div>
    <div className="agent-setting-card">
      <h3 className="agent-memory-group">{t('React 配置')}</h3>
      {view.react ? <Field label={t('最大模型轮次')}>
        <InputNumber aria-label={t('最大模型轮次')} min={1} max={30} precision={0} value={view.react.max_model_rounds} disabled={!canEdit || busy} onChange={value => onChange(patchReactConfig(config, { max_model_rounds: value || 1 }))}/>
      </Field> : <p className="agent-muted">{t('非 React Engine 不使用 React 轮次配置。')}</p>}
      <p className="agent-muted">{t('限制单次运行的模型调用轮数，范围 1–30。')}</p>
      <p className="agent-muted">{t('Chat 模型方案在「模型配置」区块中选择，与轮次同属 React Engine 的配置。')}</p>
      {phase3Entries && <p className="agent-muted">{t('禁用能力只会收窄服务端计算结果，不能授予任何能力。')}</p>}
    </div>
    {preview && phase3Entries && <CapabilityPreview preview={preview} disabledCapabilities={view.disabledCapabilities} onNarrow={(name, disabled) => onChange(toggleDisabledCapability(config, name, disabled))} canEdit={canEdit && !busy} stale={previewedConfig !== JSON.stringify(config)}/>}
  </section>;
}
