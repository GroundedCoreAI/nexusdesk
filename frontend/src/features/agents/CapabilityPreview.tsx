import { t } from '../../i18n/index';
import { useTranslation } from 'react-i18next';
import { Checkbox, Tag, Tooltip } from 'antd';
import {
  EXECUTION_CAPABILITY_NAMES,
  type ExecutionCapabilityName,
  type ExecutionPreview,
  type ExecutionReasonCode,
} from '../../shared/api/client';

/**
 * Read-only view of the server-computed Effective capabilities plus the
 * narrowing checkbox that is the only thing an administrator may change.
 *
 * The panel deliberately renders nothing but `name / effective / reason_code`
 * (03-technical-design.md §7.2, R-21): Declared, Available, policy decisions
 * and run snapshots stay server-side, and a preview is never an authorization.
 */
const CAPABILITY_LABELS: Record<ExecutionCapabilityName, () => string> = {
  streaming: () => t('流式输出'),
  persistent_session: () => t('持久会话'),
  session_resume: () => t('会话恢复'),
  cancellation: () => t('运行取消'),
  human_approval: () => t('人工审批'),
  interactive_input: () => t('交互式输入'),
  tool_calling: () => t('工具调用'),
  file_operations: () => t('文件操作'),
  terminal_execution: () => t('终端执行'),
  native_events: () => t('原生事件'),
  workspace_required: () => t('需要工作区'),
};
const REASON_LABELS: Record<ExecutionReasonCode, () => string> = {
  allowed: () => t('服务端允许'),
  not_declared: () => t('Engine 未声明此能力'),
  probe_unavailable: () => t('部署探测不可用'),
  probe_timeout: () => t('部署探测超时'),
  probe_stale: () => t('部署探测结果已过期'),
  workspace_unavailable: () => t('工作区不可用'),
  platform_denied: () => t('平台策略拒绝'),
  tenant_denied: () => t('租户策略拒绝'),
  agent_disabled: () => t('Agent 已禁用'),
  execution_denied: () => t('执行上下文拒绝'),
  policy_unavailable: () => t('策略源不可用'),
};
export const capabilityLabel = (name: ExecutionCapabilityName) => CAPABILITY_LABELS[name]();
const reasonLabel = (code: ExecutionReasonCode) => (REASON_LABELS[code] ? REASON_LABELS[code]() : code);

interface Props {
    preview: ExecutionPreview;
    /** Names the draft already disables; the only writable part of the result. */
    disabledCapabilities: ExecutionCapabilityName[];
    onNarrow: (name: ExecutionCapabilityName, disabled: boolean) => void;
    /** Editing follows the draft's write permission; the view itself never changes. */
    canEdit: boolean;
    /** True when the draft changed after the preview was taken. */
    stale: boolean;
}
export function CapabilityPreview({ preview, disabledCapabilities, onNarrow, canEdit, stale }: Props) {
    // Labels come from module-level `t()` calls, so the component has to
    // re-render when the interface language changes.
    useTranslation();
    // The server response order is the contract's CAPABILITY_ORDER; the local
    // constant is only a guard against a short or reordered payload.
    const items = preview.capabilities;
    const ordered = EXECUTION_CAPABILITY_NAMES.every((name, index) => items[index]?.name === name) ? items : EXECUTION_CAPABILITY_NAMES.map(name => items.find(item => item.name === name)).filter(item => !!item);
    return <div className="agent-capability-preview">
    <div className="agent-capability-head"><h3 className="agent-memory-group">{t('能力（Effective）')}</h3><span className="agent-muted">{t('共 {{v0}} 项，由服务端逐项计算', { v0: ordered.length })}</span></div>
    {stale && <p role="status" className="agent-muted">{t('预览结果基于此前的配置，请重新预览。')}</p>}
    <p className="agent-muted">{t('预览结果由服务端计算，不会创建运行，也不会授予执行权限。')}</p>
    {ordered.map(item => <div className="agent-capability-row" key={item.name}>
      <span className="agent-capability-name"><span>{capabilityLabel(item.name)}</span><span className="agent-capability-code">{item.name}</span></span>
      <Tag color={item.effective ? 'green' : 'default'}>{item.effective ? t('生效') : t('不可用')}</Tag>
      <span className="agent-capability-reason"><span>{reasonLabel(item.reason_code)}</span><code>{item.reason_code}</code></span>
      {item.effective || disabledCapabilities.includes(item.name) ? <Checkbox aria-label={t('收窄 {{v0}}', { v0: capabilityLabel(item.name) })} checked={disabledCapabilities.includes(item.name)} disabled={!item.effective || !canEdit} onChange={e => onNarrow(item.name, e.target.checked)}/> : <Tooltip title={t('已不可用的能力无法在此启用。')}><span><Checkbox aria-label={t('收窄 {{v0}}', { v0: capabilityLabel(item.name) })} checked={false} disabled/></span></Tooltip>}
    </div>)}
    <h3 className="agent-memory-group agent-capability-schema-title">{t('配置字段')}</h3>
    {preview.config_schema.fields.map(field => <div className="agent-schema-row" key={field.name}>
      <span className="agent-capability-code">{field.name}</span><span>{field.type}</span><Tag>{field.required ? t('必填') : t('可选')}</Tag>
    </div>)}
    <p className="agent-muted">{t('Engine {{v0}} · 配置 schema {{v1}}', { v0: `${preview.engine.engine_id}/${preview.engine.protocol_id}/${preview.engine.adapter_version}`, v1: preview.config_schema.schema_version })}</p>
  </div>;
}
