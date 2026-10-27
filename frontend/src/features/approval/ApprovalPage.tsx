import { Button, Drawer, Pagination, Select, Space, Spin, Tag } from 'antd';
import { useState } from 'react';
import {
  cancelApproval,
  createApproval,
  decideApproval,
  type ApprovalAuditEvent,
  type ApprovalRequest,
  type ApprovalStatus,
} from '../../shared/api/client';
import { Alert, Empty, Field, Panel, time, useAccess, useAction, useResource } from '../../shared/components/ui';
import { t } from '../../i18n/index';
import './approval.css';

const PAGE_SIZE = 12;
const statuses: Array<ApprovalStatus | 'all'> = ['all', 'draft', 'pending', 'approved', 'rejected', 'cancelled'];

function statusLabel(status: ApprovalStatus | 'all') {
  const labels: Record<ApprovalStatus | 'all', string> = {
    all: t('全部状态'),
    draft: t('草稿'),
    pending: t('待审批'),
    approved: t('已批准'),
    rejected: t('已拒绝'),
    cancelled: t('已取消'),
  };
  return labels[status];
}

function statusColor(status: ApprovalStatus) {
  const colors: Record<ApprovalStatus, string> = {
    draft: 'default',
    pending: 'processing',
    approved: 'success',
    rejected: 'error',
    cancelled: 'default',
  };
  return colors[status];
}

function ApprovalStatusTag({ status }: { status: ApprovalStatus }) {
  return <Tag color={statusColor(status)}>{statusLabel(status)}</Tag>;
}

function auditActionLabel(action: string) {
  const labels: Record<string, string> = {
    'approval.requested': t('提交审批'),
    'approval.approved': t('审批已通过'),
    'approval.rejected': t('审批已驳回'),
    'approval.cancelled': t('审批申请已取消'),
  };
  return labels[action] || action;
}

export function ApprovalPage() {
  const { operator } = useAccess();
  const actor = useResource<{ actor: string }>('/me');
  const [status, setStatus] = useState<ApprovalStatus | 'all'>('all');
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const action = useAction();
  const rows = useResource<{
    items: ApprovalRequest[];
    total: number;
    page: number;
    page_size: number;
  }>(`/approvals?status=${status}&page=${page}&page_size=${PAGE_SIZE}`, 3000);
  const detail = useResource<ApprovalRequest>(selectedId ? `/approvals/${selectedId}` : null, 2500);
  const audit = useResource<{ items: ApprovalAuditEvent[] }>(
    selectedId ? `/approvals/${selectedId}/audit?limit=100` : null,
    5000,
  );

  function refreshAfterChange() {
    rows.refresh();
    detail.refresh();
    audit.refresh();
  }

  function submit() {
    const nextTitle = title.trim();
    if (!nextTitle) {
      void action.run(async () => {
        throw new Error(t('审批标题不能为空'));
      }, '');
      return;
    }
    void action.run(async () => {
      await createApproval({ title: nextTitle, description: description.trim() || undefined });
      setTitle('');
      setDescription('');
      rows.refresh();
    }, t('审批请求已提交'));
  }

  function decide(decision: 'approve' | 'reject') {
    const approval = detail.data;
    if (!approval) return;
    void action.run(async () => {
      await decideApproval(approval.id, decision, approval.revision);
      refreshAfterChange();
    }, decision === 'approve' ? t('审批已通过') : t('审批已驳回'));
  }

  function cancel() {
    const approval = detail.data;
    if (!approval) return;
    void action.run(async () => {
      await cancelApproval(approval.id, approval.revision);
      refreshAfterChange();
    }, t('审批申请已取消'));
  }

  const selected = detail.data;
  const currentActor = actor.data?.actor;
  const canCancel = Boolean(
    operator && selected && currentActor && selected.requested_by === currentActor
      && (selected.status === 'draft' || selected.status === 'pending'),
  );
  const canDecide = Boolean(
    operator && selected && selected.status === 'pending'
      && (!currentActor || selected.requested_by !== currentActor),
  );

  return <div className="approval-workspace">
    <Alert error={action.error || rows.error || detail.error || audit.error || actor.error} notice={action.notice} />
    {operator && <Panel title={t('创建审批申请')}>
      <div className="approval-create-form">
        <Field label={t('审批标题')}>
          <input value={title} maxLength={200} onChange={event => setTitle(event.target.value)} placeholder={t('请输入审批标题')} />
        </Field>
        <Field label={t('描述')}>
          <textarea value={description} maxLength={4000} rows={3} onChange={event => setDescription(event.target.value)} placeholder={t('补充审批背景和执行说明')} />
        </Field>
        <div className="approval-form-actions">
          <Button type="primary" loading={action.busy} onClick={submit}>{t('提交审批')}</Button>
        </div>
      </div>
    </Panel>}
    <Panel title={t('审批申请列表')} action={
      <Space>
        <span className="approval-live-indicator"><span aria-hidden="true" />{t('状态自动刷新')}</span>
        <Select
          aria-label={t('审批状态')}
          value={status}
          options={statuses.map(value => ({ value, label: statusLabel(value) }))}
          onChange={(value: ApprovalStatus | 'all') => { setStatus(value); setPage(1); }}
        />
      </Space>
    }>
      <Spin spinning={rows.loading}>
        {rows.data?.items.length === 0 && <Empty>{t('暂无审批申请')}</Empty>}
        {rows.data && rows.data.items.length > 0 && <div className="approval-table-wrap">
          <table className="approval-table">
            <thead><tr>
              <th>{t('审批标题')}</th>
              <th>{t('状态')}</th>
              <th>{t('申请人')}</th>
              <th>{t('申请时间')}</th>
              <th>{t('操作')}</th>
            </tr></thead>
            <tbody>{rows.data.items.map(item => <tr key={item.id}>
              <td><button className="text-button approval-title" onClick={() => setSelectedId(item.id)}>{item.title}</button><small className="mono muted">{item.id.slice(0, 8)}</small></td>
              <td><ApprovalStatusTag status={item.status} /></td>
              <td className="mono">{item.requested_by}</td>
              <td>{time(item.created_at)}</td>
              <td><Button type="link" onClick={() => setSelectedId(item.id)}>{t('查看详情')}</Button></td>
            </tr>)}</tbody>
          </table>
        </div>}
        {rows.data && rows.data.total > 0 && <Pagination
          className="approval-pagination"
          current={page}
          pageSize={PAGE_SIZE}
          total={rows.data.total}
          showSizeChanger={false}
          showTotal={total => t('总共 {{v0}} 条', { v0: total })}
          onChange={setPage}
        />}
      </Spin>
    </Panel>
    <Drawer
      className="approval-drawer"
      title={selected?.title || t('审批详情')}
      open={Boolean(selectedId)}
      onClose={() => setSelectedId(null)}
      size={560}
    >
      {detail.loading && <Spin />}
      {selected && <div className="approval-detail">
        <div className="approval-detail-heading">
          <ApprovalStatusTag status={selected.status} />
          <span className="mono muted">r{selected.revision}</span>
        </div>
        <dl className="approval-facts">
          <dt>{t('申请人')}</dt><dd className="mono">{selected.requested_by}</dd>
          <dt>{t('申请时间')}</dt><dd>{time(selected.created_at)}</dd>
          <dt>{t('决策人')}</dt><dd className="mono">{selected.decision_by || '—'}</dd>
          {selected.decided_at && <><dt>{t('决策时间')}</dt><dd>{time(selected.decided_at)}</dd></>}
        </dl>
        <section className="approval-description">
          <h3>{t('审批说明')}</h3>
          <p>{selected.description || t('暂无描述')}</p>
        </section>
        <section className="approval-audit">
          <h3>{t('操作审计')}</h3>
          {audit.loading && !audit.data && <Spin size="small" />}
          {!audit.loading && audit.data?.items.length === 0 && <Empty>{t('暂无审计记录')}</Empty>}
          {audit.data && audit.data.items.length > 0 && <ol className="approval-audit-list">
            {audit.data.items.map(event => <li key={event.id}>
              <div className="approval-audit-heading">
                <strong>{auditActionLabel(event.action)}</strong>
                <span>{time(event.created_at)}</span>
              </div>
              <div className="approval-audit-meta">
                <span>{t('操作者')}：<b className="mono">{event.actor}</b></span>
                {typeof event.details.revision === 'number' && <span className="mono">r{event.details.revision}</span>}
              </div>
            </li>)}
          </ol>}
        </section>
        {(canDecide || canCancel) && <Space wrap className="approval-detail-actions">
          {canDecide && <><Button type="primary" loading={action.busy} onClick={() => decide('approve')}>{t('批准')}</Button><Button danger loading={action.busy} onClick={() => decide('reject')}>{t('驳回')}</Button></>}
          {canCancel && <Button loading={action.busy} onClick={cancel}>{t('取消申请')}</Button>}
        </Space>}
        {!operator && <p className="hint">{t('当前角色为只读，只能查看审批记录。')}</p>}
        {selected.status === 'pending' && selected.requested_by === currentActor && <p className="hint">{t('申请人不能审批自己的申请。')}</p>}
      </div>}
    </Drawer>
  </div>;
}
