import { useEffect, useMemo, useState } from 'react';
import { Button, Input, Spin } from 'antd';
import {
  ClockCircleOutlined,
  CustomerServiceOutlined,
  MessageOutlined,
  ReloadOutlined,
  SearchOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { errorText, t } from '../../i18n/index';
import {
  post,
  type ConversationDetail,
  type Handoff,
  type HandoffContext,
} from '../../shared/api/client';
import {
  Alert,
  Badge,
  Empty,
  time,
  useAccess,
  useAction,
  useResource,
} from '../../shared/components/ui';
import './handoff.css';

type HandoffFilter = 'all' | 'waiting' | 'mine';

interface HandoffRow extends Handoff {
  business_id?: string | null;
  workspace_id?: string | null;
  created_at?: string | null;
  closed_at?: string | null;
  updated_at?: string | null;
}

interface HandoffConversation extends ConversationDetail {
  business_id?: string | null;
  workspace_id?: string | null;
}

function elapsed(value?: string | null, until = Date.now()): string {
  if (!value) return t('未知');
  const started = new Date(value).getTime();
  if (Number.isNaN(started)) return t('未知');
  const minutes = Math.max(0, Math.floor((until - started) / 60000));
  if (minutes < 1) return t('少于 1 分钟');
  if (minutes < 60) return t('{{v0}} 分钟', { v0: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('{{v0}} 小时', { v0: hours });
  return t('{{v0}} 天', { v0: Math.floor(hours / 24) });
}

function queueDuration(row: HandoffRow, now: number): string {
  if (row.status === 'waiting') return `${t('等待接管')} · ${elapsed(row.created_at, now)}`;
  if (row.status === 'active') return `${t('处理中')} · ${elapsed(row.created_at, now)}`;
  return row.closed_at
    ? `${t('已完成')} · ${elapsed(row.created_at, new Date(row.closed_at).getTime())}`
    : t('已完成');
}

function sourceLabel(source?: string | null): string {
  if (source === 'business') return t('业务会话');
  if (source === 'playground') return t('试聊');
  return source || t('未知');
}

function modeLabel(mode?: string | null): string {
  if (mode === 'bot') return t('自动服务');
  if (mode === 'waiting') return t('等待接管');
  if (mode === 'human') return t('人工服务');
  if (mode === 'closed') return t('已关闭');
  return mode || t('未知');
}

function messageRole(role: string): string {
  return ({
    user: t('客户'),
    assistant: t('Agent'),
    human: t('人工客服'),
    system: t('系统'),
  } as Record<string, string>)[role] || role;
}

function handoffStatusLabel(status: string): string {
  if (status === 'waiting') return t('等待接管');
  if (status === 'active') return t('处理中');
  if (status === 'closed') return t('已完成');
  return status;
}

function displayValue(value?: string | null): string {
  return value || t('暂无数据');
}

function preview(summary?: string | null): string {
  return summary?.replace(/\s+/g, ' ').trim() || t('暂无历史消息');
}

function factValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return t('暂无数据');
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

function LoadingState({ label }: { label?: string }) {
  return <div className="handoff-state is-loading" role="status">
    <Spin size="small" />
    <span>{label || t('正在加载')}</span>
  </div>;
}

export function HandoffPage() {
  const rows = useResource<HandoffRow[]>('/handoffs', 3000);
  const actor = useResource<{ actor: string }>('/me');
  const action = useAction();
  const { operator, admin } = useAccess();

  const [filter, setFilter] = useState<HandoffFilter>('all');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [assignee, setAssignee] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const filters: Array<{ key: HandoffFilter; label: string }> = [
    { key: 'all', label: t('全部') },
    { key: 'waiting', label: t('等待接管') },
    { key: 'mine', label: t('我的处理中') },
  ];

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const currentActor = actor.data?.actor || '';
  const allRows = rows.data || [];
  const waitingRows = allRows.filter(row => row.status === 'waiting');
  const activeRows = allRows.filter(row => row.status === 'active');
  const mineRows = currentActor
    ? activeRows.filter(row => row.assignee === currentActor)
    : [];

  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return allRows.filter(row => {
      if (filter === 'waiting' && row.status !== 'waiting') return false;
      if (filter === 'mine' && (row.status !== 'active' || row.assignee !== currentActor)) {
        return false;
      }
      if (!needle) return true;
      return `${row.external_id || ''} ${row.reason || ''}`.toLowerCase().includes(needle);
    });
  }, [allRows, currentActor, filter, query]);

  useEffect(() => {
    if (!filteredRows.length) {
      if (selectedId) setSelectedId('');
      return;
    }
    if (!selectedId || !filteredRows.some(row => row.id === selectedId)) {
      setSelectedId(filteredRows[0].id);
    }
  }, [filteredRows, selectedId]);

  const selected = allRows.find(row => row.id === selectedId) || null;
  const detail = useResource<HandoffConversation>(
    selected?.conversation_id
      ? `/conversations/${encodeURIComponent(selected.conversation_id)}`
      : null,
    5000,
  );
  // The server aggregates the published application, object, facts and decisions; the workbench
  // never stitches this together from several internal endpoints.
  const context = useResource<HandoffContext>(
    selected
      ? `/handoffs/${encodeURIComponent(selected.id)}/context`
      : null,
    5000,
  );

  const canHandleActive = Boolean(
    operator
      && selected?.status === 'active'
      && (admin || !currentActor || selected.assignee === currentActor),
  );
  const canClaim = Boolean(operator && selected?.status === 'waiting');

  function refreshAll() {
    rows.refresh();
    detail.refresh();
    context.refresh();
  }

  function claim() {
    if (!selected) return;
    void action.run(async () => {
      await post(`/handoffs/${selected.id}/transition`, {
        operation: 'claim',
        assignee: admin ? assignee.trim() || null : null,
        revision: selected.revision,
      });
      refreshAll();
    }, t('已接管，请到会话工作台回复'));
  }

  function transition(operation: 'resume' | 'close') {
    if (!selected) return;
    void action.run(async () => {
      await post(`/handoffs/${selected.id}/transition`, {
        operation,
        revision: selected.revision,
      });
      refreshAll();
    }, operation === 'resume' ? t('已恢复自动服务') : t('会话已结束'));
  }

  const conversation = detail.data;
  const recentMessages = Array.isArray(conversation?.messages)
    ? conversation.messages.slice(-8)
    : [];
  const pendingActions = Array.isArray(conversation?.actions) ? conversation.actions : [];
  const recentRuns = Array.isArray(conversation?.runs) ? conversation.runs.slice(0, 3) : [];

  const serviceContext = context.data;
  const serviceFacts = Array.isArray(serviceContext?.facts) ? serviceContext.facts : [];
  const serviceDecisions = Array.isArray(serviceContext?.decisions) ? serviceContext.decisions : [];
  const serviceObject = serviceContext?.object || null;

  return <div className="handoff-workspace">
    <header className="handoff-page-head">
      <div>
        <span className="handoff-eyebrow">HUMAN HANDOFF</span>
        <h2>{t('人工服务队列')}</h2>
        <p>{t('转接、分配、交接与恢复自动服务')}</p>
      </div>
      <div className="handoff-head-stats" aria-label={t('状态')}>
        <span><b>{waitingRows.length}</b>{t('等待接管')}</span>
        <span><b>{activeRows.length}</b>{t('处理中')}</span>
        <span><b>{allRows.length}</b>{t('全部')}</span>
      </div>
    </header>

    <Alert error={rows.error || actor.error || detail.error || context.error || action.error} notice={action.notice} />

    {!operator && <div className="handoff-readonly" role="status">
      <WarningOutlined aria-hidden />
      <span>{t('当前为只读角色，可查看配置和对话记录。')}</span>
    </div>}

    <div className="handoff-shell">
      <aside className="handoff-queue" aria-label={t('人工服务队列')}>
        <div className="handoff-queue-tools">
          <div className="handoff-queue-topline">
            <strong>{t('处理队列')}</strong>
            <span className="handoff-live"><i aria-hidden />{t('状态自动刷新')}</span>
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined aria-hidden />}
              aria-label={t('刷新')}
              disabled={rows.loading}
              onClick={refreshAll}
            />
          </div>
          <div className="handoff-filters" role="group" aria-label={t('状态')}>
            {filters.map(item => {
              const count = item.key === 'all'
                ? allRows.length
                : item.key === 'waiting'
                  ? waitingRows.length
                  : mineRows.length;
              return <button
                type="button"
                key={item.key}
                className={`handoff-filter ${filter === item.key ? 'is-active' : ''}`}
                aria-pressed={filter === item.key}
                onClick={() => setFilter(item.key)}
              >
                <span>{item.label}</span>
                <b>{count}</b>
              </button>;
            })}
          </div>
          <Input
            allowClear
            className="handoff-search"
            prefix={<SearchOutlined aria-hidden />}
            value={query}
            maxLength={120}
            placeholder={t('搜索交接编号或原因')}
            aria-label={t('搜索交接编号或原因')}
            onChange={event => setQuery(event.target.value)}
          />
        </div>

        <div className="handoff-queue-list" aria-live="polite">
          {rows.loading && !rows.data && <LoadingState />}
          {!rows.loading && rows.error && !rows.data && <div className="handoff-state is-error">
            <WarningOutlined aria-hidden />
            <strong>{t('加载失败')}</strong>
            <span>{errorText(rows.error)}</span>
            <Button size="small" onClick={rows.refresh}>{t('重新加载')}</Button>
          </div>}
          {rows.data && filteredRows.length === 0 && <Empty>
            {allRows.length === 0 ? t('当前没有人工转接记录') : t('暂无匹配记录')}
          </Empty>}
          {filteredRows.map(row => <button
            type="button"
            key={row.id}
            className={`handoff-card ${selectedId === row.id ? 'is-selected' : ''}`}
            aria-pressed={selectedId === row.id}
            onClick={() => setSelectedId(row.id)}
          >
            <span className="handoff-card-top">
              <strong className="mono">{row.external_id || row.conversation_id.slice(0, 12)}</strong>
              <Badge value={handoffStatusLabel(row.status)} />
            </span>
            <span className="handoff-card-reason">{row.reason || t('暂无描述')}</span>
            <span className="handoff-card-meta">
              <span><UserOutlined aria-hidden />{row.assignee || t('未分配')}</span>
              <span><ClockCircleOutlined aria-hidden />{queueDuration(row, now)}</span>
            </span>
            <span className="handoff-card-preview">{preview(row.summary)}</span>
          </button>)}
        </div>
      </aside>

      <section className="handoff-detail" aria-label={t('交接详情')}>
        {!selected && <div className="handoff-state handoff-detail-empty">
          <CustomerServiceOutlined aria-hidden />
          <strong>{t('人工服务队列')}</strong>
          <span>{t('选择左侧交接记录查看详情')}</span>
        </div>}

        {selected && <>
          <div className="handoff-detail-head">
            <div className="handoff-detail-title">
              <span className="handoff-eyebrow">HANDOFF DETAIL</span>
              <h3>{selected.external_id || selected.conversation_id}</h3>
              <p>{selected.reason || t('暂无描述')}</p>
            </div>
            <div className="handoff-detail-status">
              <Badge value={handoffStatusLabel(selected.status)} />
              <span>{queueDuration(selected, now)}</span>
            </div>
          </div>

          <div className="handoff-detail-body">
            <dl className="handoff-facts">
              <div>
                <dt>{t('状态')}</dt>
                <dd>{selected.status === 'waiting' ? t('等待接管') : selected.status === 'active' ? t('处理中') : t('已完成')}</dd>
              </div>
              <div>
                <dt>{t('处理人：')}</dt>
                <dd className="mono">{selected.assignee || t('未分配')}</dd>
              </div>
              <div>
                <dt>{t('创建时间')}</dt>
                <dd>{selected.created_at ? time(selected.created_at) : t('未知')}</dd>
              </div>
              <div>
                <dt>{t('最近更新')}</dt>
                <dd>{selected.updated_at || selected.closed_at ? time(String(selected.updated_at || selected.closed_at)) : t('未知')}</dd>
              </div>
            </dl>

            <section className="handoff-section">
              <div className="handoff-section-head">
                <h4>{t('交接摘要')}</h4>
                <span>{t('最近消息')}</span>
              </div>
              <pre className="handoff-summary">{selected.summary || t('暂无历史消息')}</pre>
            </section>

            <section className="handoff-section handoff-service-context">
              <div className="handoff-section-head">
                <h4>{t('自动服务')}</h4>
                <Button
                  type="text"
                  size="small"
                  icon={<ReloadOutlined aria-hidden />}
                  loading={context.loading}
                  onClick={context.refresh}
                >{t('刷新')}</Button>
              </div>

              {context.loading && !serviceContext && <LoadingState label={t('正在加载')} />}
              {!context.loading && context.error && !serviceContext && <div className="handoff-state is-error">
                <WarningOutlined aria-hidden />
                <strong>{t('服务应用上下文加载失败')}</strong>
                <span>{errorText(context.error)}</span>
                <Button size="small" onClick={context.refresh}>{t('重新加载')}</Button>
              </div>}

              {serviceContext && !serviceContext.application && <Empty>
                {t('自动服务尚未绑定服务应用版本')}
              </Empty>}

              {serviceContext?.application && <>
                <dl className="handoff-facts">
                  <div>
                    <dt>{t('服务应用')}</dt>
                    <dd>{serviceContext.application.name || serviceContext.application.key}</dd>
                  </div>
                  <div>
                    <dt>{t('应用版本')}</dt>
                    <dd className="mono">{serviceContext.application.version ?? t('暂无数据')}</dd>
                  </div>
                  <div>
                    <dt>{t('业务对象')}</dt>
                    <dd className="mono">
                      {serviceObject
                        ? [serviceObject.type, serviceObject.id].filter(Boolean).join(' · ')
                        : t('暂无数据')}
                    </dd>
                  </div>
                </dl>

                <div className="handoff-context-grid">
                  <div className="handoff-context-card">
                    <div className="handoff-context-title">
                      <h5>{t('业务事实')}</h5>
                    </div>
                    {serviceFacts.length === 0 && <p className="handoff-permission">{t('暂无数据')}</p>}
                    {serviceFacts.length > 0 && <dl>
                      {serviceFacts.map(fact => <div key={fact.key}>
                        <dt>{fact.label}</dt>
                        <dd>
                          {factValue(fact.value)}
                          {fact.masked && <Badge value={t('已脱敏')} />}
                        </dd>
                      </div>)}
                    </dl>}
                  </div>
                  <div className="handoff-context-card">
                    <div className="handoff-context-title">
                      <h5>{t('用户决策')}</h5>
                    </div>
                    {serviceDecisions.length === 0 && <p className="handoff-permission">{t('暂无数据')}</p>}
                    {serviceDecisions.length > 0 && <ul className="handoff-context-list">
                      {serviceDecisions.map(decision => <li key={decision.key}>
                        <strong>{decision.label}</strong>
                        <span>
                          {decision.state === 'selected'
                            ? t('已选择')
                            : t('待确认')}
                        </span>
                      </li>)}
                    </ul>}
                  </div>
                </div>
              </>}
            </section>

            {(selected.status === 'waiting' || selected.status === 'active') && <section className="handoff-actionbar">
              {admin && selected.status === 'waiting' && <label className="handoff-assignee">
                <span>{t('管理员分配主体（留空为本人）')}</span>
                <Input
                  value={assignee}
                  maxLength={100}
                  disabled={action.busy}
                  onChange={event => setAssignee(event.target.value)}
                />
              </label>}
              <div className="handoff-actions">
                {selected.status === 'waiting' && <Button
                  type="primary"
                  loading={action.busy}
                  disabled={!canClaim}
                  onClick={claim}
                >{t('接管')}</Button>}
                {selected.status === 'active' && <>
                  <Button
                    type="primary"
                    loading={action.busy}
                    disabled={!canHandleActive}
                    onClick={() => transition('resume')}
                  >{t('结束并恢复 Agent')}</Button>
                  <Button
                    danger
                    loading={action.busy}
                    disabled={!canHandleActive}
                    onClick={() => transition('close')}
                  >{t('关闭会话')}</Button>
                </>}
              </div>
              {!operator && <p className="handoff-permission">{t('当前角色没有执行此操作的权限')}</p>}
              {operator && selected.status === 'active' && !canHandleActive
                && <p className="handoff-permission">{t('当前角色没有执行此操作的权限')}</p>}
            </section>}

            <section className="handoff-section handoff-conversation">
              <div className="handoff-section-head">
                <h4>{t('会话上下文')}</h4>
                <Button
                  type="text"
                  size="small"
                  icon={<ReloadOutlined aria-hidden />}
                  loading={detail.loading}
                  disabled={!selected.conversation_id}
                  onClick={detail.refresh}
                >{t('刷新')}</Button>
              </div>

              {detail.loading && !conversation && <LoadingState label={t('正在加载')} />}
              {!detail.loading && detail.error && !conversation && <div className="handoff-state is-error">
                <WarningOutlined aria-hidden />
                <strong>{t('客户详情加载失败')}</strong>
                <span>{errorText(detail.error)}</span>
                <Button size="small" onClick={detail.refresh}>{t('重新加载')}</Button>
              </div>}

              {conversation && <>
                <div className="handoff-context-grid">
                  <div className="handoff-context-card">
                    <div className="handoff-context-title">
                      <UserOutlined aria-hidden />
                      <h5>{t('客户信息')}</h5>
                    </div>
                    <dl>
                      <div><dt>{t('客户标识')}</dt><dd className="mono">{displayValue(conversation.customer_id)}</dd></div>
                      <div><dt>{t('外部会话标识')}</dt><dd className="mono">{displayValue(conversation.external_id)}</dd></div>
                      <div><dt>{t('会话来源')}</dt><dd>{sourceLabel(conversation.source)}</dd></div>
                      <div><dt>{t('会话模式')}</dt><dd>{modeLabel(conversation.mode)}</dd></div>
                    </dl>
                  </div>
                  <div className="handoff-context-card">
                    <div className="handoff-context-title">
                      <CustomerServiceOutlined aria-hidden />
                      <h5>{t('业务上下文')}</h5>
                    </div>
                    <dl>
                      <div><dt>{t('业务标识')}</dt><dd className="mono">{displayValue(conversation.business_id)}</dd></div>
                      <div><dt>{t('工作区标识')}</dt><dd className="mono">{displayValue(conversation.workspace_id)}</dd></div>
                      <div><dt>Agent</dt><dd className="mono">{conversation.deleted_agent?.name || displayValue(conversation.agent_id)}</dd></div>
                      <div><dt>{t('关联动作')}</dt><dd>{pendingActions.length}</dd></div>
                    </dl>
                    {pendingActions.length > 0 && <ul className="handoff-context-list">
                      {pendingActions.slice(0, 3).map(item => <li key={item.id}>
                        <strong>{item.payload?.title || t('待确认')}</strong>
                        <span>{item.payload?.description || t('暂无描述')}</span>
                      </li>)}
                    </ul>}
                    {recentRuns.length > 0 && <div className="handoff-run-summary">
                      <span>{t('最近运行')}</span>
                      {recentRuns.map(run => <div key={run.id}>
                        <Badge value={run.status} />
                        <small className="mono">{run.error_code || run.id.slice(0, 8)}</small>
                      </div>)}
                    </div>}
                  </div>
                </div>

                <section className="handoff-messages">
                  <div className="handoff-section-head">
                    <h4>{t('最近消息')}</h4>
                    <span>{recentMessages.length}</span>
                  </div>
                  {recentMessages.length === 0 && <Empty>{t('暂无消息')}</Empty>}
                  <div className="handoff-message-list">
                    {recentMessages.map(message => <article
                      key={message.id}
                      className={`handoff-message is-${message.role}`}
                    >
                      <div className="handoff-message-meta">
                        <span>{messageRole(message.role)}</span>
                        <time>{time(message.created_at)}</time>
                      </div>
                      <p>{message.content}</p>
                    </article>)}
                  </div>
                </section>
              </>}

              {!conversation && !detail.loading && !detail.error && <div className="handoff-state">
                <MessageOutlined aria-hidden />
                <span>{t('暂无会话数据')}</span>
              </div>}
            </section>
          </div>
        </>}
      </section>
    </div>
  </div>;
}
