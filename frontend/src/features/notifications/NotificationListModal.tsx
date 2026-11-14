import { useCallback, useEffect, useState } from 'react';
import { Button, Empty, Modal, Pagination, Spin, Tabs } from 'antd';
import { t, number } from '../../i18n';
import {
  getMonitorNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type MonitorNotification,
  type MonitorNotificationQuery,
} from '../../shared/api/client';
import { NotificationRow } from './NotificationRow';
import './notification-row.css';

const PAGE_SIZE = 20;

type TabKey = 'unread' | 'all' | 'resolved';

const TAB_QUERY: Record<TabKey, MonitorNotificationQuery> = {
  unread: { unread: true },
  all: {},
  resolved: { status: 'resolved' },
};

interface Props {
  open: boolean;
  onClose: () => void;
  /** The bell owns the badge; every read action must refresh it. */
  onChanged: () => void;
  onNavigate?: (path: string) => void;
}

export function NotificationListModal({ open, onClose, onChanged, onNavigate }: Props) {
  const [tab, setTab] = useState<TabKey>('unread');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<MonitorNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback((nextTab: TabKey, nextPage: number, signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    void getMonitorNotifications(
      { ...TAB_QUERY[nextTab], limit: PAGE_SIZE, offset: (nextPage - 1) * PAGE_SIZE },
      signal,
    )
      .then(result => {
        if (signal?.aborted) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch(cause => {
        if (!signal?.aborted) setError(String(cause));
      })
      .finally(() => {
        if (!signal?.aborted) setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    load(tab, page, controller.signal);
    return () => controller.abort();
  }, [open, tab, page, load]);

  // Reopening always starts from the top of the unread queue.
  useEffect(() => {
    if (!open) return;
    setTab('unread');
    setPage(1);
  }, [open]);

  const readOne = async (id: string) => {
    // Optimistic: the row greys out immediately, the refetch is the rollback.
    setItems(prev => prev.map(item => (
      item.id === id ? { ...item, read_at: item.read_at ?? new Date().toISOString() } : item
    )));
    try {
      await markNotificationRead(id);
      onChanged();
      load(tab, page);
    } catch {
      load(tab, page);
    }
  };

  const readAll = async () => {
    try {
      await markAllNotificationsRead();
      onChanged();
      setPage(1);
      load(tab, 1);
    } catch (cause) {
      setError(String(cause));
    }
  };

  const list = loading && items.length === 0
    ? <div className="notification-panel-loading"><Spin size="small" /></div>
    : items.length
      ? (
        <ul className="notification-modal-list">
          {items.map(item => (
            <NotificationRow
              key={item.id}
              item={item}
              onRead={readOne}
              onNavigate={onNavigate}
              onClose={onClose}
            />
          ))}
        </ul>
      )
      : <Empty className="notification-modal-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('暂无消息')} />;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('消息通知')}
      width={720}
      centered
      destroyOnHidden
      footer={(
        <div className="notification-modal-footer">
          <span className="notification-modal-total">
            {t('共 {{count}} 条', { count: number(total) })}
            <em className="notification-modal-hint">{t('已读只清除未读标记，不影响铃铛待处理数')}</em>
          </span>
          <Pagination
            size="small"
            current={page}
            pageSize={PAGE_SIZE}
            total={total}
            showSizeChanger={false}
            hideOnSinglePage
            onChange={next => setPage(next)}
          />
          <span className="notification-modal-actions">
            <Button onClick={onClose}>{t('关闭')}</Button>
            <Button type="primary" onClick={readAll} disabled={total === 0}>
              {t('全部标为已读')}
            </Button>
          </span>
        </div>
      )}
    >
      {error && <p className="notification-panel-error" role="alert">{error}</p>}
      <Tabs
        activeKey={tab}
        onChange={key => {
          setTab(key as TabKey);
          setPage(1);
        }}
        items={[
          { key: 'unread', label: t('未读') },
          { key: 'all', label: t('全部') },
          { key: 'resolved', label: t('已恢复') },
        ]}
      />
      {list}
    </Modal>
  );
}
