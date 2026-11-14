import { useEffect, useState } from 'react';
import { Button, Empty, Spin } from 'antd';
import { t } from '../../i18n';
import {
  getMonitorChecklist,
  getMonitorNotifications,
  type MonitorCheck,
  type MonitorChecklist,
  type MonitorNotification,
} from '../../shared/api/client';
import { NotificationRow } from './NotificationRow';
import './notification-panel.css';

const PREVIEW_LIMIT = 5;

const STATUS_LABEL: Record<string, string> = {
  pass: '正常',
  warn: '需要关注',
  fail: '故障',
  not_configured: '未接入',
  unknown: '未知',
  stale: '已过期',
};

const OVERALL_LABEL: Record<string, string> = {
  healthy: '系统状态正常',
  degraded: '系统状态降级',
  down: '系统状态异常',
  unknown: '状态未知',
};

interface Props {
  onNavigate?: (path: string) => void;
  onClose?: () => void;
  /** Opens the paged history modal; the popover itself never paginates. */
  onOpenAll?: () => void;
}

function Dot({ status }: { status: string }) {
  return (
    <span
      className={`monitor-dot is-${status}`}
      title={t(STATUS_LABEL[status] || status)}
      aria-hidden
    />
  );
}

function CheckRow({ item }: { item: MonitorCheck }) {
  const attention = item.status !== 'pass' && item.status !== 'not_configured';
  // Capacity checks report their measured value; a bare "usage is high" without
  // the number gives an operator nothing to act on.
  const value = item.evidence?.percent;
  return (
    <li className={`monitor-check${attention ? ' is-attention' : ''}`}>
      <Dot status={item.status} />
      <div className="monitor-check-body">
        <div className="monitor-check-title">
          <span>{t(item.title)}</span>
          {attention && <span className={`monitor-severity is-${item.severity}`}>{item.severity}</span>}
          {item.status === 'not_configured' && <span className="monitor-check-note">{t('未接入')}</span>}
          {item.stale && <span className="monitor-stale">{t('已过期')}</span>}
        </div>
        {attention && (
          <p className="monitor-check-summary">
            {t(item.summary)}
            {typeof value === 'number' && <span className="monitor-check-value">{value}%</span>}
          </p>
        )}
      </div>
    </li>
  );
}

function Group({ group }: { group: MonitorChecklist['groups'][number] }) {
  const failing = group.items.filter(item => item.status === 'fail' || item.status === 'warn');
  // Unconfigured optional components are not faults, but hiding them entirely
  // makes an operator think the component is absent from the checklist.
  const unconfigured = group.items.filter(item => item.status === 'not_configured');
  // Collapsed by default: only rows that need attention are listed, so the
  // panel reads as "what is wrong", never as a wall of green.
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? group.items : [...failing, ...unconfigured];
  return (
    <section className="monitor-group">
      <button
        type="button"
        className="monitor-group-heading"
        onClick={() => setExpanded(value => !value)}
        aria-expanded={expanded}
      >
        <Dot status={failing.length ? (failing.some(i => i.status === 'fail') ? 'fail' : 'warn') : 'pass'} />
        <span>{t(group.title)}</span>
        {unconfigured.length > 0 && (
          <span className="monitor-group-muted">{t('未接入')} {unconfigured.length}</span>
        )}
        <span className="monitor-group-count">
          {`${failing.length || unconfigured.length}/${group.items.length}`}
        </span>
      </button>
      <ul className="monitor-check-list">
        {shown.map(item => <CheckRow key={item.check_id} item={item} />)}
      </ul>
    </section>
  );
}

export function NotificationPanel({ onNavigate, onClose, onOpenAll }: Props) {
  const [checklist, setChecklist] = useState<MonitorChecklist | null>(null);
  const [notices, setNotices] = useState<MonitorNotification[]>([]);
  const [unreadTotal, setUnreadTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const [nextChecklist, nextNotices] = await Promise.all([
          getMonitorChecklist(controller.signal),
          getMonitorNotifications({ unread: true, limit: PREVIEW_LIMIT }, controller.signal),
        ]);
        setChecklist(nextChecklist);
        setNotices(nextNotices.items);
        setUnreadTotal(nextNotices.total);
      } catch (cause) {
        if (!controller.signal.aborted) setError(String(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, []);

  const overall = checklist?.overall_status || 'unknown';
  const counts = checklist?.counts;
  const stale = (checklist?.scan_age_seconds ?? 0) > 180;
  // A group whose checks are all healthy says nothing an operator needs to act
  // on: it stays out of the panel entirely instead of showing "all healthy".
  const groups = (checklist?.groups ?? []).filter(group =>
    group.items.some(item => item.status === 'warn' || item.status === 'fail' || item.status === 'not_configured'),
  );

  return (
    <div className="notification-panel" role="region" aria-label={t('消息通知')}>
      <div className="notification-panel-heading">
        <span>{t('消息通知')}</span>
        {checklist && <span className={`monitor-overall is-${overall}`}>{t(OVERALL_LABEL[overall])}</span>}
      </div>
      {loading ? (
        <div className="notification-panel-loading"><Spin size="small" /></div>
      ) : (
        <div className="notification-panel-body">
          {error && <p className="notification-panel-error" role="alert">{error}</p>}
          {stale && <p className="notification-panel-warn">{t('检查数据可能已过期')}</p>}
          <section className="notification-section">
            <div className="notification-section-heading">
              <span>{t('当前系统状态')}</span>
              {counts && (
                <span className="monitor-counts">
                  {(['P0', 'P1', 'P2'] as const).map(level => (
                    counts[level] > 0 ? <span key={level} className={`monitor-severity is-${level}`}>{level} {counts[level]}</span> : null
                  ))}
                </span>
              )}
            </div>
            {checklist && groups.length === 0 ? (
              <p className="notification-panel-ok">{t('全部检查项正常')}</p>
            ) : groups.length ? (
              groups.map(group => <Group key={group.id} group={group} />)
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('暂无检查数据')} />
            )}
          </section>
          <section className="notification-section">
            <div className="notification-section-heading">
              <span>{t('未读消息')}</span>
              {unreadTotal > 0 && <span className="monitor-group-count">{unreadTotal}</span>}
            </div>
            {notices.length
              ? <ul className="monitor-notice-list">{notices.map(item => <NotificationRow key={item.id} item={item} />)}</ul>
              : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span className="notification-empty-text">{t('暂无新消息')}</span>} />}
          </section>
        </div>
      )}
      {/* Outside the scroll container: the entry point to history must never be
          hidden behind a long list of checks. */}
      <div className="notification-panel-footer">
        <Button type="link" size="small" onClick={onOpenAll}>{t('查看全部消息')}</Button>
      </div>
    </div>
  );
}
