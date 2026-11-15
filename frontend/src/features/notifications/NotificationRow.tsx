import { Button } from 'antd';
import { t, locale } from '../../i18n';
import type { MonitorNotification } from '../../shared/api/client';
import './notification-row.css';

const KIND_LABEL: Record<string, string> = {
  opened: '异常',
  recovered: '已恢复',
  reminder: '仍未恢复',
  unstable: '状态不稳定',
};

const STATUS_LABEL: Record<string, string> = {
  active: '待处理',
  acknowledged: '已确认',
  resolved: '已恢复',
  suppressed: '已静音',
};

/** Server-supplied routes are still validated: never navigate to an arbitrary path. */
export const ROUTE_ALLOWLIST =
  /^\/(overview|conversations|service-apps|tickets|handoff|memory|agents|models|knowledge|tools|open-platform|access|evaluation|observability|members|roles|security|extensions)(\/|$)/;

function stamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(locale(), {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

interface Props {
  item: MonitorNotification;
  /** Rows in the modal can be dismissed; the popover preview stays read-only. */
  onRead?: (id: string) => void;
  onNavigate?: (path: string) => void;
  onClose?: () => void;
}

export function NotificationRow({ item, onRead, onNavigate, onClose }: Props) {
  const route = item.action_route && ROUTE_ALLOWLIST.test(item.action_route) ? item.action_route : null;
  const unread = !item.read_at;
  return (
    <li className={`notice-row${unread ? ' is-unread' : ''}`}>
      <span className={`monitor-severity is-${item.severity}`}>{item.severity}</span>
      <div className="notice-row-body">
        <div className="notice-row-head">
          <span className="notice-row-title">{t(item.title)}</span>
          {item.status !== 'active' && (
            <span className={`notice-status is-${item.status}`}>{t(STATUS_LABEL[item.status] || item.status)}</span>
          )}
          <time className="notice-row-time" dateTime={item.created_at} title={new Date(item.created_at).toLocaleString()}>
            {stamp(item.created_at)}
          </time>
        </div>
        <div className="notice-row-foot">
          <p className="notice-row-impact">
            {/* "已恢复" already shows as a status chip; repeating it as a prefix
                on the same line is noise, so the prefix is dropped for it. */}
            {item.kind !== 'recovered' && KIND_LABEL[item.kind] ? `${t(KIND_LABEL[item.kind])} · ` : ''}
            {t(item.impact)}
          </p>
          {(route || (onRead && unread)) && (
            <div className="notice-row-actions">
              {route && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    onNavigate?.(route);
                    onClose?.();
                  }}
                >
                  {t('查看详情')}
                </Button>
              )}
              {onRead && unread && (
                <Button type="link" size="small" onClick={() => onRead(item.id)}>
                  {t('标为已读')}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
