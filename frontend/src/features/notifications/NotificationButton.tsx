import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Popover } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { t } from '../../i18n';
import { getNotificationUnreadCount } from '../../shared/api/client';
import { NotificationListModal } from './NotificationListModal';
import { NotificationPanel } from './NotificationPanel';
import './notification-button.css';

const UNREAD_POLL_MS = 60_000;

export function NotificationButton({ onNavigate }: { onNavigate?: (path: string) => void }) {
  useTranslation();
  const [open, setOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  // "Cannot read the alert state" is not "no alerts": a deployment whose API is
  // down must not look like a clean bill of health, so the bell degrades to an
  // explicit unknown marker instead of silently showing zero.
  const [unreachable, setUnreachable] = useState(false);

  const refresh = useCallback((signal?: AbortSignal) => {
    if (document.hidden) return;
    void getNotificationUnreadCount(signal)
      .then(data => {
        setUnread(data.count);
        setUnreachable(false);
      })
      .catch(() => {
        if (!signal?.aborted) setUnreachable(true);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    const timer = window.setInterval(() => refresh(controller.signal), UNREAD_POLL_MS);
    const onVisible = () => refresh(controller.signal);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refresh]);

  return (
    <>
      <Popover
        trigger="click"
        placement="bottomRight"
        open={open}
        onOpenChange={next => {
          setOpen(next);
          if (next) refresh();
        }}
        arrow={false}
        destroyOnHidden
        classNames={{ root: 'notification-popover' }}
        styles={{
          container: {
            padding: 0,
            overflow: 'hidden',
            border: '1px solid #ececf3',
            borderRadius: 16,
            boxShadow: '0 12px 40px #25233f14, 0 3px 10px #25233f06',
          },
        }}
        content={(
          <NotificationPanel
            onNavigate={onNavigate}
            onClose={() => setOpen(false)}
            onOpenAll={() => {
              setOpen(false);
              setListOpen(true);
            }}
          />
        )}
      >
        <span className="notification-anchor">
          <Badge count={unreachable ? 0 : unread} size="small" offset={[-3, 3]}>
            <Button
              type="text"
              className={`notification-button ${open ? 'is-open' : ''}`}
              aria-label={
                unreachable
                  ? `${t('消息通知')} · ${t('无法获取告警状态')}`
                  : unread ? `${t('消息通知')} · ${unread}` : t('消息通知')
              }
              aria-expanded={open}
              icon={<BellOutlined aria-hidden />}
            />
          </Badge>
          {unreachable && <span className="notification-unreachable" title={t('无法获取告警状态')} aria-hidden />}
        </span>
      </Popover>
      <NotificationListModal
        open={listOpen}
        onClose={() => setListOpen(false)}
        onChanged={() => refresh()}
        onNavigate={onNavigate}
      />
    </>
  );
}
