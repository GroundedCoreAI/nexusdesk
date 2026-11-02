import {
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';
import type { ServiceApplicationSummary, ServiceScenarioSummary } from '../../shared/api/client';
import {
  evaluateScenarioReadiness,
  type ScenarioReadinessCheck,
  type ScenarioReadinessCheckStatus,
  type ScenarioReadinessResult,
  type ScenarioReadinessState,
} from './scenarioReadiness';
import { t } from '../../i18n/index';

export interface ScenarioReadinessPanelProps {
  application: ServiceApplicationSummary | null | undefined;
  scenario: ServiceScenarioSummary;
  readiness?: ScenarioReadinessResult | null;
  className?: string;
}

const stateIcons: Record<ScenarioReadinessState, ReactNode> = {
  ready: <CheckCircleFilled/>,
  simulate_only: <ExclamationCircleFilled/>,
  blocked: <CloseCircleFilled/>,
};

const checkIcons: Record<ScenarioReadinessCheckStatus, ReactNode> = {
  pass: <CheckCircleFilled/>,
  warning: <ExclamationCircleFilled/>,
  blocked: <CloseCircleFilled/>,
};

function checkStatusLabel(status: ScenarioReadinessCheckStatus): string {
  if (status === 'pass') return t('通过');
  if (status === 'warning') return t('警告');
  return t('阻断');
}

function severityLabel(check: ScenarioReadinessCheck): string {
  if (check.status === 'pass') return t('检查通过');
  if (check.severity === 'blocking') return t('阻断发布');
  if (check.severity === 'info') return t('发布提示');
  return t('发布前处理');
}

export function ScenarioReadinessPanel({
  application,
  scenario,
  readiness: serverReadiness,
  className = '',
}: ScenarioReadinessPanelProps) {
  const readiness = serverReadiness ?? evaluateScenarioReadiness(application, scenario);

  return <section className={`sa-readiness ${className}`.trim()} aria-label={t('场景发布完整性检查')}>
    <header className="sa-readiness-head">
      <div className={`sa-readiness-mark ${readiness.status}`}>
        {readiness.status === 'ready' ? <SafetyCertificateOutlined/> : stateIcons[readiness.status]}
      </div>
      <div className="sa-readiness-heading">
        <span className="sa-eyebrow">PUBLISH READINESS</span>
        <h3>{t('场景发布完整性检查')}</h3>
        <p>{t('从业务对象、处理路径、人工承接和客户触点评估发布条件。')}</p>
      </div>
      <span className={`sa-readiness-state ${readiness.status}`}>
        {stateIcons[readiness.status]}
        {readiness.label}
      </span>
    </header>

    <div className="sa-readiness-overview">
      <div className={`sa-readiness-verdict ${readiness.status}`}>
        <span>{readiness.label}</span>
        <p>{readiness.description}</p>
      </div>
      <div className="sa-readiness-counts" aria-label={t('检查结果统计')}>
        <span className="pass"><strong>{readiness.counts.pass}</strong><small>{t('通过')}</small></span>
        <span className="warning"><strong>{readiness.counts.warning}</strong><small>{t('警告')}</small></span>
        <span className="blocked"><strong>{readiness.counts.blocked}</strong><small>{t('阻断')}</small></span>
      </div>
    </div>

    <ul className="sa-readiness-checks">
      {readiness.checks.map(item => <li className={`sa-readiness-check ${item.status}`} key={item.key}>
        <span className="sa-readiness-check-icon">{checkIcons[item.status]}</span>
        <div className="sa-readiness-check-copy">
          <div className="sa-readiness-check-title">
            <strong>{item.title}</strong>
            <span>{checkStatusLabel(item.status)}</span>
          </div>
          <p>{item.detail}</p>
        </div>
        <span className={`sa-readiness-severity ${item.status} ${item.severity}`}>
          {severityLabel(item)}
        </span>
      </li>)}
    </ul>

    <footer className="sa-readiness-foot">
      <InfoCircleFilled/>
      <span>{t('检查只使用业务配置和客户可见结果，不展示内部数据来源或执行标识。')}</span>
    </footer>
  </section>;
}
