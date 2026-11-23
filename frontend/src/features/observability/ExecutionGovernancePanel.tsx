import { t } from '../../i18n/index';
import { useState, type ReactNode } from 'react';
import { Select, Table, Tag } from 'antd';
import type { TableColumnsType } from 'antd';
import {
    governancePath,
    type CleanupFailureRow,
    type CredentialAuditRow,
    type ExecutionCredentialSummary,
    type FencingDenialRow,
    type GovernanceScope,
    type MonitorChecklist,
    type MonitorNotificationPage,
    type OutboxView,
    type ParserDiagnosticRow,
    type ReplayGapRow,
    type UsageConflictRow,
} from '../../shared/api/client';
import { Alert, Panel, time, useResource } from '../../shared/components/ui';

const PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];

/** Runs/audit rows grow without bound; governance tables page in SQL like the overview page. */
function serverPagination(page: number, pageSize: number, total: number, onChange: (page: number, pageSize: number) => void) {
    return {
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        pageSizeOptions: PAGE_SIZE_OPTIONS,
        showTotal: (value: number) => t('总共 {{v0}} 条', { v0: value }),
        onChange,
    };
}

/** One group of metric cards, same `.metrics`/`.metric` idiom as the overview. */
function MetricGrid({ cards }: { cards: [string, ReactNode][] }) {
    return <div className="metrics">{cards.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value ?? '—'}</strong></div>)}</div>;
}

/**
 * Tenant/scope of a governance row. A null tenant (orphaned join, deployment-level
 * source, or missing context) is rendered as 部署级 — never fabricated as a
 * placeholder tenant. The object form is reduced to its known scope fields so no
 * unexpected payload is dumped into the DOM.
 */
function scopeText(scope: GovernanceScope): string {
    if (scope == null) return t('部署级');
    if (typeof scope === 'string') return sanitize(scope);
    if (typeof scope === 'object') {
        const value = scope as Record<string, unknown>;
        // Backend contract: scope = {business_id, workspace_id} | null. The
        // flat-name fallbacks keep older/alternate wire shapes readable too.
        const parts = [value.business_id, value.workspace_id, value.business_scope, value.workspace]
            .filter(part => part != null && part !== '')
            .map(part => sanitize(String(part)));
        if (parts.length) return parts.join(' / ');
    }
    return t('部署级');
}

function tenantText(tenantId: string | null | undefined): string {
    return sanitize(tenantId && tenantId !== '' ? tenantId : t('部署级'));
}

/**
 * Defence in depth for D-class content: the backend already returns bounded,
 * redacted values, but a leaked key/raw-sample canary must never reach the DOM
 * even if an upstream response regresses. Secret-shaped tokens are replaced,
 * never shown verbatim.
 */
function sanitize(value: string): string {
    return value
        .replace(/sk-[A-Za-z0-9_-]{4,}/gi, t('已隐藏'))
        .replace(/RAW_SAMPLE[A-Za-z0-9_-]*/gi, t('已隐藏'))
        .replace(/[A-Za-z0-9_-]*(?:SECRET|CANARY|PASSWORD|API_KEY)[A-Za-z0-9_-]*/gi, t('已隐藏'));
}

/** Bounded, non-secret display for aggregate/unknown wire values. */
function display(value: unknown): string {
    if (value == null || value === '') return '—';
    const text = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
        ? String(value)
        : (() => { try { return JSON.stringify(value); } catch { return '—'; } })();
    return sanitize(text);
}

function seconds(value: number | null | undefined): string {
    return value == null ? '—' : `${Number(value).toFixed(1)}s`;
}

const cleanupLabels: Record<string, string> = {
    failed: t('清理失败'),
    unconfirmed_cancel: t('取消未确认'),
};
const kindLabels: Record<string, string> = {
    chain: t('修正链'),
    duplicate: t('重复来源'),
};
const parserLabels: Record<string, string> = {
    malformed: t('格式错误'),
    unknown_schema: t('未知 Schema'),
    unknown_type: t('未知类型'),
    size_limit: t('大小超限'),
    critical_terminal: t('严重终止'),
};
const statusLabels: Record<string, string> = {
    pass: t('正常'),
    warn: t('告警'),
    fail: t('失败'),
    not_configured: t('未配置'),
    unknown: t('未知'),
    stale: t('过期'),
};

/**
 * Phase 6-2 · SIG-1~SIG-8 governance signals. Mounted by ObservabilityPage only
 * when the 执行治理 tab is active AND the viewer is admin, so ordinary users and
 * the 运行总览 tab issue zero governance requests. Every panel fails closed:
 * an error or empty response yields a stable empty state, never a faked recovery,
 * delivery success or conflict count. No Secret, raw sample or key reaches the
 * frontend model or the DOM.
 */
export function ExecutionGovernancePanel() {
    const [fencePage, setFencePage] = useState(1);
    const [fencePageSize, setFencePageSize] = useState(PAGE_SIZE);
    const fences = useResource<{ items: FencingDenialRow[]; total: number }>(
        governancePath('fencing-denials', { page: fencePage, page_size: fencePageSize }), 5000);

    const [cleanupCategory, setCleanupCategory] = useState<string>();
    const [cleanupPage, setCleanupPage] = useState(1);
    const [cleanupPageSize, setCleanupPageSize] = useState(PAGE_SIZE);
    const cleanups = useResource<{ items: CleanupFailureRow[]; total: number }>(
        governancePath('cleanup-failures', { category: cleanupCategory, page: cleanupPage, page_size: cleanupPageSize }), 5000);

    const [outboxPage, setOutboxPage] = useState(1);
    const [outboxPageSize, setOutboxPageSize] = useState(PAGE_SIZE);
    const outbox = useResource<OutboxView>(
        governancePath('outbox', { page: outboxPage, page_size: outboxPageSize }), 5000);

    const [gapPage, setGapPage] = useState(1);
    const [gapPageSize, setGapPageSize] = useState(PAGE_SIZE);
    const gaps = useResource<{ items: ReplayGapRow[]; total: number }>(
        governancePath('replay-gaps', { page: gapPage, page_size: gapPageSize }), 5000);

    const [usageKind, setUsageKind] = useState<string>();
    const [usagePage, setUsagePage] = useState(1);
    const [usagePageSize, setUsagePageSize] = useState(PAGE_SIZE);
    const usages = useResource<{ items: UsageConflictRow[]; total: number }>(
        governancePath('usage-conflicts', { kind: usageKind, page: usagePage, page_size: usagePageSize }), 5000);

    const [parserCategory, setParserCategory] = useState<string>();
    const [parserPage, setParserPage] = useState(1);
    const [parserPageSize, setParserPageSize] = useState(PAGE_SIZE);
    const parsers = useResource<{ items: ParserDiagnosticRow[]; total: number }>(
        governancePath('parser-diagnostics', { category: parserCategory, page: parserPage, page_size: parserPageSize }), 5000);

    const [credAction, setCredAction] = useState('revoked');
    const [credPage, setCredPage] = useState(1);
    const [credPageSize, setCredPageSize] = useState(PAGE_SIZE);
    const audit = useResource<{ items: CredentialAuditRow[]; total: number }>(
        governancePath('credential-audit', { action: credAction, page: credPage, page_size: credPageSize }), 5000);

    // SIG-8 status + SIG-2 Worker status reuse existing Reader/admin routes.
    // No new endpoint is introduced for these two signals.
    const credentials = useResource<{ items: ExecutionCredentialSummary[] }>('/execution-credentials', 5000);
    const checklist = useResource<MonitorChecklist>('/notifications/checklist', 5000);
    const notifications = useResource<MonitorNotificationPage>('/notifications?limit=20', 5000);

    const error = fences.error || cleanups.error || outbox.error || gaps.error || usages.error
        || parsers.error || audit.error || credentials.error || checklist.error || notifications.error;
    const emptyText = t('暂无治理数据');

    const fenceColumns: TableColumnsType<FencingDenialRow> = [
        { title: t('时间'), dataIndex: 'created_at', width: 170, render: (v: string) => time(v) },
        { title: t('运行'), dataIndex: 'run_id', width: 120, render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('操作'), dataIndex: 'operation', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('原因'), dataIndex: 'reason', render: (v: string) => <span className="mono">{display(v)}</span> },
        {
            title: t('旧持有者'), key: 'stale', render: (_, row) =>
                <span className="mono">{display(row.stale_owner)} / {display(row.stale_lease_epoch)}</span>,
        },
        {
            title: t('当前持有者'), key: 'current', render: (_, row) =>
                <span className="mono">{display(row.current_owner)} / {display(row.current_lease_epoch)}</span>,
        },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string | null) => tenantText(v) },
        { title: t('范围'), key: 'scope', render: (_, row) => scopeText(row.scope) },
    ];

    const cleanupColumns: TableColumnsType<CleanupFailureRow> = [
        {
            title: t('类别'), dataIndex: 'category', width: 130,
            render: (v: string) => <Tag color={v === 'failed' ? 'error' : 'warning'}>{cleanupLabels[v] || display(v)}</Tag>,
        },
        { title: t('运行'), dataIndex: 'run_id', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('清理状态'), dataIndex: 'cleanup_status', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('清理更新时间'), dataIndex: 'cleanup_updated_at', render: (v: string | null) => v ? time(v) : '—' },
        { title: t('取消请求时间'), dataIndex: 'cancel_requested_at', render: (v: string | null) => v ? time(v) : '—' },
        { title: t('取消确认时间'), dataIndex: 'cancel_confirmed_at', render: (v: string | null) => v ? time(v) : '—' },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string | null) => tenantText(v) },
        { title: t('范围'), key: 'scope', render: (_, row) => scopeText(row.scope) },
    ];

    const outboxColumns: TableColumnsType<OutboxView['last_errors'][number]> = [
        { title: t('运行'), dataIndex: 'run_id', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('序号'), dataIndex: 'seq', width: 80 },
        { title: t('尝试次数'), dataIndex: 'attempts', width: 100 },
        { title: t('可用时间'), dataIndex: 'available_at', render: (v: string) => time(v) },
        { title: t('最近错误'), dataIndex: 'last_error', render: (v: string | null) => <span className="mono">{display(v)}</span> },
    ];

    const gapColumns: TableColumnsType<ReplayGapRow> = [
        { title: t('时间'), dataIndex: 'created_at', width: 170, render: (v: string) => time(v) },
        { title: t('运行'), dataIndex: 'run_id', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('请求游标'), dataIndex: 'requested_cursor_seq' },
        { title: t('保留水位'), dataIndex: 'retention_floor_seq' },
        { title: t('原因码'), dataIndex: 'reason_code', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string | null) => tenantText(v) },
        { title: t('范围'), key: 'scope', render: (_, row) => scopeText(row.scope) },
    ];

    const usageColumns: TableColumnsType<UsageConflictRow> = [
        {
            title: t('类别'), dataIndex: 'kind', width: 120,
            render: (v: string) => <Tag color={v === 'duplicate' ? 'warning' : 'processing'}>{kindLabels[v] || display(v)}</Tag>,
        },
        { title: t('运行'), dataIndex: 'run_id', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string | null) => tenantText(v) },
        { title: t('来源'), dataIndex: 'source', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('来源事件'), dataIndex: 'source_event_id', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('被替代 ID'), dataIndex: 'supersedes_id', render: (v: string | null) => <span className="mono">{display(v)}</span> },
        { title: t('用量'), dataIndex: 'usage', render: (v: unknown) => display(v) },
        { title: t('成本'), dataIndex: 'cost', render: (v: unknown) => display(v) },
        { title: t('估算'), dataIndex: 'is_estimate', render: (v: boolean | null) => v == null ? '—' : v ? t('是') : t('否') },
    ];

    const parserColumns: TableColumnsType<ParserDiagnosticRow> = [
        { title: t('桶起始'), dataIndex: 'bucket_start', render: (v: string) => time(v) },
        {
            title: t('类别'), dataIndex: 'category',
            render: (v: string) => parserLabels[v] || <span className="mono">{display(v)}</span>,
        },
        { title: t('原因码'), dataIndex: 'reason_code', render: (v: string | null) => <span className="mono">{display(v)}</span> },
        { title: t('计数'), dataIndex: 'count' },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string | null) => tenantText(v) },
        { title: t('运行'), dataIndex: 'run_id', render: (v: string | null) => <span className="mono">{display(v)}</span> },
    ];

    const credentialColumns: TableColumnsType<ExecutionCredentialSummary> = [
        { title: t('凭据'), dataIndex: 'credential_ref', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('名称'), dataIndex: 'name', render: (v: string) => display(v) },
        { title: t('状态'), dataIndex: 'status', render: (v: string) => <Tag color={v === 'revoked' ? 'error' : v === 'superseded' ? 'warning' : 'success'}>{display(v)}</Tag> },
        { title: t('吊销时间'), dataIndex: 'revoked_at', render: (v: string | null) => v ? time(v) : '—' },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string) => tenantText(v) },
    ];

    const auditColumns: TableColumnsType<CredentialAuditRow> = [
        { title: t('时间'), dataIndex: 'created_at', width: 170, render: (v: string) => time(v) },
        { title: t('凭据'), dataIndex: 'credential_ref', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('动作'), dataIndex: 'action', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('结果'), dataIndex: 'outcome', render: (v: string | null) => display(v) },
        { title: t('原因码'), dataIndex: 'reason_code', render: (v: string | null) => <span className="mono">{display(v)}</span> },
        { title: t('参与者'), dataIndex: 'actor', render: (v: string | null) => display(v) },
        { title: t('租户'), dataIndex: 'tenant_id', render: (v: string | null) => tenantText(v) },
    ];

    const workerChecks = (checklist.data?.groups || []).flatMap(group => group.items)
        .filter(item => /worker|heartbeat|lease/i.test(`${item.check_id} ${item.title}`));
    const workerColumns: TableColumnsType<MonitorChecklist['groups'][number]['items'][number]> = [
        { title: t('检查项'), dataIndex: 'title', render: (v: string) => v ? display(v) : t('未知检查项') },
        { title: t('编号'), dataIndex: 'check_id', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('状态'), dataIndex: 'status', render: (v: string) => <Tag>{statusLabels[v] || display(v)}</Tag> },
        { title: t('最近检查'), dataIndex: 'checked_at', render: (v: string | null) => v ? time(v) : '—' },
    ];
    const notificationColumns: TableColumnsType<MonitorNotificationPage['items'][number]> = [
        { title: t('标题'), dataIndex: 'title', render: (v: string) => display(v) },
        { title: t('级别'), dataIndex: 'severity', render: (v: string) => <span className="mono">{display(v)}</span> },
        { title: t('状态'), dataIndex: 'status', render: (v: string) => <Tag>{display(v)}</Tag> },
        { title: t('最近时间'), dataIndex: 'last_seen_at', render: (v: string) => time(v) },
    ];

    return <>
        <Alert error={error}/>

        <Panel title={t('Fencing 拒绝')}>
            <Table<FencingDenialRow> rowKey={row => `${row.run_id}-${row.created_at}`} size="small" loading={fences.loading}
                columns={fenceColumns} dataSource={fences.data?.items || []} scroll={{ x: 1100 }}
                locale={{ emptyText }} pagination={serverPagination(fencePage, fencePageSize, fences.data?.total || 0, (page, size) => {
                    setFencePage(size === fencePageSize ? page : 1);
                    setFencePageSize(size);
                })}/>
        </Panel>

        <Panel title={t('Worker 状态')} action={<Tag color="processing">{t('部署级')}</Tag>}>
            <p className="hint">{t('Worker 心跳与租约检查为部署级信号，不按租户维度拆分。')}</p>
            <MetricGrid cards={[
                [t('检查项数'), workerChecks.length],
                [t('告警数'), workerChecks.filter(item => item.status === 'warn' || item.status === 'fail').length],
            ]}/>
            <Table<MonitorChecklist['groups'][number]['items'][number]> rowKey="check_id" size="small" loading={checklist.loading}
                columns={workerColumns} dataSource={workerChecks} scroll={{ x: 640 }} locale={{ emptyText }}/>
            <h3 className="gateway-group-title">{t('监控通知')}</h3>
            <Table<MonitorNotificationPage['items'][number]> rowKey="id" size="small" loading={notifications.loading}
                columns={notificationColumns} dataSource={notifications.data?.items || []} scroll={{ x: 640 }} locale={{ emptyText }}/>
        </Panel>

        <Panel title={t('清理失败与取消未确认')} action={
            <Select aria-label={t('清理类别')} allowClear placeholder={t('全部类别')} value={cleanupCategory}
                onChange={(value?: string) => { setCleanupCategory(value); setCleanupPage(1); }}
                options={[
                    { value: 'failed', label: t('清理失败') },
                    { value: 'unconfirmed_cancel', label: t('取消未确认') },
                ]}/>
        }>
            <Table<CleanupFailureRow> rowKey={row => `${row.run_id}-${row.category}`} size="small" loading={cleanups.loading}
                columns={cleanupColumns} dataSource={cleanups.data?.items || []} scroll={{ x: 1100 }} locale={{ emptyText }}
                pagination={serverPagination(cleanupPage, cleanupPageSize, cleanups.data?.total || 0, (page, size) => {
                    setCleanupPage(size === cleanupPageSize ? page : 1);
                    setCleanupPageSize(size);
                })}/>
        </Panel>

        <Panel title={t('Outbox 投递状态')}>
            <MetricGrid cards={[
                [t('待投递数'), outbox.data?.pending_count],
                [t('最老可用时间'), outbox.data?.oldest_available_at ? time(outbox.data.oldest_available_at) : '—'],
                [t('滞留秒数'), seconds(outbox.data?.stall_seconds)],
                [t('24h 已发布'), outbox.data?.published_24h],
            ]}/>
            <Table<OutboxView['last_errors'][number]> rowKey={row => `${row.run_id}-${row.seq}`} size="small" loading={outbox.loading}
                columns={outboxColumns} dataSource={outbox.data?.last_errors || []} scroll={{ x: 720 }} locale={{ emptyText }}
                pagination={serverPagination(outboxPage, outboxPageSize, outbox.data?.total || 0, (page, size) => {
                    setOutboxPage(size === outboxPageSize ? page : 1);
                    setOutboxPageSize(size);
                })}/>
        </Panel>

        <Panel title={t('SSE 重放缺口')}>
            <Table<ReplayGapRow> rowKey="id" size="small" loading={gaps.loading}
                columns={gapColumns} dataSource={gaps.data?.items || []} scroll={{ x: 900 }} locale={{ emptyText }}
                pagination={serverPagination(gapPage, gapPageSize, gaps.data?.total || 0, (page, size) => {
                    setGapPage(size === gapPageSize ? page : 1);
                    setGapPageSize(size);
                })}/>
        </Panel>

        <Panel title={t('Usage 冲突与修正链')} action={
            <Select aria-label={t('冲突类别')} allowClear placeholder={t('全部类别')} value={usageKind}
                onChange={(value?: string) => { setUsageKind(value); setUsagePage(1); }}
                options={[
                    { value: 'chain', label: t('修正链') },
                    { value: 'duplicate', label: t('重复来源') },
                ]}/>
        }>
            <Table<UsageConflictRow> rowKey={row => `${row.run_id}-${row.source}-${row.source_event_id}`} size="small" loading={usages.loading}
                columns={usageColumns} dataSource={usages.data?.items || []} scroll={{ x: 1200 }} locale={{ emptyText }}
                pagination={serverPagination(usagePage, usagePageSize, usages.data?.total || 0, (page, size) => {
                    setUsagePage(size === usagePageSize ? page : 1);
                    setUsagePageSize(size);
                })}/>
        </Panel>

        <Panel title={t('Parser 诊断')} action={
            <Select aria-label={t('诊断类别')} allowClear placeholder={t('全部类别')} value={parserCategory}
                onChange={(value?: string) => { setParserCategory(value); setParserPage(1); }}
                options={Object.entries(parserLabels).map(([value, label]) => ({ value, label }))}/>
        }>
            <p className="hint">{t('仅显示分类计数与脱敏原因码；原始样本与密钥不会进入此面板。')}</p>
            <Table<ParserDiagnosticRow> rowKey={row => `${row.bucket_start}-${row.category}`} size="small" loading={parsers.loading}
                columns={parserColumns} dataSource={parsers.data?.items || []} scroll={{ x: 900 }} locale={{ emptyText }}
                pagination={serverPagination(parserPage, parserPageSize, parsers.data?.total || 0, (page, size) => {
                    setParserPage(size === parserPageSize ? page : 1);
                    setParserPageSize(size);
                })}/>
        </Panel>

        <Panel title={t('凭据吊销与审计')}>
            <h3 className="gateway-group-title">{t('凭据状态')}</h3>
            <Table<ExecutionCredentialSummary> rowKey="credential_ref" size="small" loading={credentials.loading}
                columns={credentialColumns} dataSource={(credentials.data?.items || []).filter(item => item.status !== 'active')}
                scroll={{ x: 720 }} locale={{ emptyText }}/>
            <h3 className="gateway-group-title">{t('吊销审计')}</h3>
            <Select aria-label={t('审计动作')} allowClear placeholder={t('全部动作')} value={credAction}
                onChange={(value?: string) => { setCredAction(value ?? 'revoked'); setCredPage(1); }}
                options={[{ value: 'revoked', label: t('已吊销') }]}/>
            <Table<CredentialAuditRow> rowKey="id" size="small" loading={audit.loading}
                columns={auditColumns} dataSource={audit.data?.items || []} scroll={{ x: 1000 }} locale={{ emptyText }}
                pagination={serverPagination(credPage, credPageSize, audit.data?.total || 0, (page, size) => {
                    setCredPage(size === credPageSize ? page : 1);
                    setCredPageSize(size);
                })}/>
        </Panel>
    </>;
}
