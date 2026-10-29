import { t } from '../../i18n/index';
import { useState, type ReactNode } from 'react';
import { Button, Popconfirm, Select, Space, Table, Tag } from 'antd';
import type { TableColumnsType } from 'antd';
import {
    retryExtensionEvent,
    type Audit,
    type CapabilityObservability,
    type CapabilityStatusItem,
    type ExtensionEventPage,
    type ExtensionEventStatus,
    type MemoryAgentRow,
    type MemoryAlert,
    type MemoryExtractionDay,
    type MemorySummary,
    type MemoryTaskKind,
    type Run,
    type Summary,
} from '../../shared/api/client';
import { Alert, Badge, Panel, Trace, time, useAccess, useAction, useResource } from '../../shared/components/ui';

interface Paged<T> {
    items: T[];
    total: number;
    page: number;
    page_size: number;
}

interface AuditPaged extends Paged<Audit> {
    action_types: { action: string; count: number }[];
}

interface GatewayModel {
    operation: string;
    status: string;
    calls: number;
    average_ms: number;
    p95_ms: number;
}

interface GatewayTool {
    adapter_type: string;
    effect: string;
    status: string;
    calls: number;
    average_ms: number;
}

interface GatewayUsage {
    operation: string;
    unit: string;
    amount: number;
}

interface GatewaySummary {
    models: GatewayModel[];
    tools: GatewayTool[];
    known_usage: GatewayUsage[];
    window_hours: number;
}

const PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];

/** Aggregate tables (memory, gateway billing) are small, so paging happens in the browser. */
const clientPagination = {
    pageSize: PAGE_SIZE,
    showSizeChanger: false,
    showTotal: (total: number) => t("总共 {{v0}} 条", { v0: total }),
};

/** Runs and audit records grow without bound, so their paging happens in SQL. */
function serverPagination(page: number, pageSize: number, total: number, onChange: (page: number, pageSize: number) => void) {
    return {
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        pageSizeOptions: PAGE_SIZE_OPTIONS,
        showTotal: (value: number) => t("总共 {{v0}} 条", { v0: value }),
        onChange,
    };
}

export function Metrics({ value }: { value: Summary | null }) {
    const cards = [[t("近 24h 运行"), value?.total], [t("执行中 / 排队"), value ? `${value.running} / ${value.queued}` : '—'], [t("成功完成"), value?.completed], [t("失败运行"), value?.failed], [t("P95 执行时间"), value?.p95_seconds == null ? '—' : `${Number(value.p95_seconds).toFixed(2)}s`], [t("P50 首字延迟"), value?.ttfc?.p50_ms == null ? '—' : `${Math.round(Number(value.ttfc.p50_ms))}ms`], [t("模型 Tokens"), value?.tokens]];
    return <div className="metrics">{cards.map(([label, count]) => <div className="metric" key={label}><span>{label}</span><strong>{count ?? '—'}</strong></div>)}</div>;
}

/** Rate as a whole percent, or an em dash when the window had no calls. */
function percent(rate: number | null | undefined): string {
    return rate == null ? '—' : `${Math.round(Number(rate) * 100)}%`;
}
/** Milliseconds like the gateway tables render them, or an em dash when unmeasured. */
function millis(value: number | null | undefined): string {
    return value == null ? '—' : `${Math.round(Number(value))}ms`;
}
/** Task age: minutes below two hours, then hours like the existing backlog age card. */
function taskAge(minutes: number | null | undefined): string {
    if (minutes == null) return '—';
    return minutes < 120 ? `${Math.round(minutes)}min` : `${Math.round(minutes / 60)}h`;
}
/** One decimal for fractional aggregates (avg returned, avg injected), em dash when null. */
function decimal(value: number | null | undefined): string {
    return value == null ? '—' : Number(value).toFixed(1);
}

/** One group of metric cards, same .metrics/.metric idiom as the flat grids above. */
function MetricGrid({ cards }: { cards: [string, ReactNode][] }) {
    return <div className="metrics">{cards.map(([label, count]) => <div className="metric" key={label}><span>{label}</span><strong>{count ?? '—'}</strong></div>)}</div>;
}

/** Human label for a memory.alert.* rule name; unknown rules fall back to the raw name. */
function memoryAlertRuleLabel(rule: string): string {
    const labels: Record<string, string> = {
        task_failed: t("记忆任务执行失败"),
        pending_task_age: t("待办任务停留过久"),
        embedding_growing: t("Embedding 积压持续增长"),
        vector_fallback: t("向量检索频繁降级"),
        maintenance_silent: t("维护任务长时间未运行"),
        rule_scan_missed: t("规则扫描未按周期执行"),
        pending_backlog: t("待确认记忆积压过多"),
        worker_heartbeat: t("记忆 Worker 心跳失联"),
    };
    return labels[rule] || rule;
}

/**
 * Phase 4 memory governance observability (FR-7) + Phase 7 production health:
 * grouped metric cards (tasks / embedding / search / maintenance / agents /
 * injection / quality), with overdue maintenance jobs emphasised in red.
 */
export function MemoryMetrics({ value }: { value: MemorySummary | null }) {
    const rate = value && value.hit_rate.customer_runs > 0 ? `${Math.round((value.hit_rate.injected_runs / value.hit_rate.customer_runs) * 100)}%` : '—';
    const oldest = value?.backlog.oldest_age_seconds == null ? '—' : `${Math.round(Number(value.backlog.oldest_age_seconds) / 3600)}h`;
    const overdue = new Set(value?.maintenance.overdue || []);
    // job: audit resource name used by the backend maintenance.overdue list.
    const maintenanceJobs: { job: string; label: string; at: string | null | undefined }[] = [
        { job: 'ttl_purge', label: t("TTL 清理"), at: value?.maintenance.ttl_last_at },
        { job: 'decay', label: t("衰退迁移"), at: value?.maintenance.decay_last_at },
        { job: 'rule_scan', label: t("规则扫描"), at: value?.maintenance.rule_scan_last_at },
        { job: 'embedding_retry', label: t("Embedding 重试"), at: value?.maintenance.embedding_retry_last_at },
        { job: 'heartbeat', label: t("Worker 心跳"), at: value?.maintenance.heartbeat_last_at },
    ];
    const overdueNames = maintenanceJobs.filter(job => overdue.has(job.job)).map(job => job.label).join('、');

    const taskKindColumns: TableColumnsType<MemoryTaskKind> = [
        { title: t("任务类型"), dataIndex: 'kind', render: (kind: string) => <span className="mono">{kind}</span> },
        { title: t("平均耗时"), dataIndex: 'avg_ms', render: (v: number | null) => millis(v) },
        { title: t("P95 耗时"), dataIndex: 'p95_ms', render: (v: number | null) => millis(v) },
        { title: t("完成"), dataIndex: 'done' },
        { title: t("失败"), dataIndex: 'failed' },
    ];
    const agentColumns: TableColumnsType<MemoryAgentRow> = [
        { title: t("Agent"), dataIndex: 'agent_id', render: (id: string | null) => id ? <span className="mono">{id.slice(0, 8)}</span> : t("未归属 Agent") },
        { title: t("客户运行"), dataIndex: 'customer_runs' },
        { title: t("注入运行"), dataIndex: 'injected_runs' },
        { title: t("注入率"), dataIndex: 'inject_rate', render: (v: number | null) => percent(v) },
        { title: t("写入条数"), dataIndex: 'items_written', render: (v: number | null) => v ?? '—' },
        { title: t("任务失败"), dataIndex: 'tasks_failed', render: (v: number | null) => v ?? '—' },
    ];

    return <>
        <h3 className="gateway-group-title">{t("任务健康")}</h3>
        <MetricGrid cards={[
            [t("待处理任务"), value?.tasks.pending],
            [t("执行中任务"), value?.tasks.running],
            [t("近 15 分钟失败"), value?.tasks.failed_15m],
            [t("最老待办年龄"), taskAge(value?.tasks.oldest_pending_age_minutes)],
            [t("强化任务（完成 / 失败）"), value ? `${value.reinforce.tasks_done} / ${value.reinforce.tasks_failed}` : '—'],
            [t("强化刷新条目"), value?.reinforce.ids_refreshed],
        ]}/>
        <Table<MemoryTaskKind> rowKey="kind" size="small" columns={taskKindColumns}
            dataSource={value?.tasks.by_kind || []} pagination={clientPagination} locale={{ emptyText: t("暂无数据") }}/>

        <h3 className="gateway-group-title">{t("Embedding")}</h3>
        <MetricGrid cards={[
            [t("Embedding 失败积压"), value?.embedding.failed_backlog],
            [t("重试扫描（7 天）"), value?.embedding.retry_scanned_7d],
            [t("重试成功（7 天）"), value?.embedding.retry_succeeded_7d],
        ]}/>

        <h3 className="gateway-group-title">{t("检索")}</h3>
        <MetricGrid cards={[
            [t("向量检索"), value?.search_modes.vector],
            [t("文本检索"), value?.search_modes.text],
            [t("关键词降级"), value?.search_modes.keyword_fallback],
            [t("降级率"), percent(value?.search_modes.fallback_rate)],
            [t("空结果率"), percent(value?.search_quality.empty_rate)],
            [t("平均返回条数"), decimal(value?.search_quality.avg_returned)],
            [t("记忆检索（调用 / 空结果）"), value ? `${value.search.calls} / ${value.search.empty}` : '—'],
        ]}/>

        <h3 className="gateway-group-title">{t("维护任务")}</h3>
        {overdueNames && <Alert error={t("以下维护任务已超期：{{v0}}", { v0: overdueNames })}/>}
        <MetricGrid cards={maintenanceJobs.map((job): [string, ReactNode] => [job.label,
            <span className={overdue.has(job.job) ? 'error-text' : undefined}>{job.at ? time(job.at) : '—'}</span>,
        ])}/>
        <MetricGrid cards={[
            [t("衰退迁移（待确认 / 过期）"), value ? `${value.decay.decay_pending} / ${value.decay.decay_expired}` : '—'],
            [t("容量淘汰（7 天）"), value?.decay.evicted],
            [t("过期恢复（7 天）"), value?.decay.expired_restored],
        ]}/>

        <h3 className="gateway-group-title">{t("Agent 维度")}</h3>
        <Table<MemoryAgentRow> rowKey={row => row.agent_id || '-'} size="small" columns={agentColumns}
            dataSource={value?.agents || []} pagination={clientPagination} locale={{ emptyText: t("暂无数据") }}/>

        <h3 className="gateway-group-title">{t("记忆注入")}</h3>
        <MetricGrid cards={[
            [t("记忆注入命中率"), `${rate} (${value?.hit_rate.injected_runs ?? '—'}/${value?.hit_rate.customer_runs ?? '—'})`],
            [t("平均注入条数"), decimal(value?.injection.avg_items)],
            [t("服务标记"), value?.injection.by_section.flag],
            [t("画像"), value?.injection.by_section.profile],
            [t("偏好"), value?.injection.by_section.preference],
            [t("事件"), value?.injection.by_section.event],
        ]}/>

        <h3 className="gateway-group-title">{t("记忆质量")}</h3>
        <MetricGrid cards={[
            [t("待确认积压"), value ? `${value.backlog.pending} · ${t("最久 {{v0}}", { v0: oldest })}` : '—'],
            [t("PII 脱敏命中（24h）"), value?.pii_masked],
            [t("7 天确认"), value?.pending_quality.confirmed_7d],
            [t("7 天拒绝"), value?.pending_quality.rejected_7d],
            [t("确认率"), percent(value?.pending_quality.confirm_rate)],
        ]}/>
    </>;
}

function capabilityStatus(status: CapabilityStatusItem['status']) {
    const labels: Record<CapabilityStatusItem['status'], string> = {
        registered: t("已注册"),
        starting: t("启动中"),
        ready: t("就绪"),
        degraded: t("降级"),
        stopped: t("已停止"),
    };
    const colors: Record<CapabilityStatusItem['status'], string> = {
        registered: 'default',
        starting: 'processing',
        ready: 'success',
        degraded: 'warning',
        stopped: 'default',
    };
    return <Tag color={colors[status]}>{labels[status]}</Tag>;
}

function eventStatus(status: ExtensionEventStatus) {
    const labels: Record<ExtensionEventStatus, string> = {
        pending: t("待投递"),
        running: t("投递中"),
        done: t("已完成"),
        failed: t("失败"),
    };
    const colors: Record<ExtensionEventStatus, string> = {
        pending: 'processing',
        running: 'processing',
        done: 'success',
        failed: 'error',
    };
    return <Tag color={colors[status]}>{labels[status]}</Tag>;
}

export function ObservabilityPage() {
    const summary = useResource<Summary>('/observability/summary', 5000);
    const { admin } = useAccess();
    const extensions = useResource<CapabilityObservability>('/extensions/capabilities', 5000);
    const [eventStatusFilter, setEventStatusFilter] = useState<ExtensionEventStatus>();
    const [eventPage, setEventPage] = useState(1);
    const [eventPageSize, setEventPageSize] = useState(20);
    const eventQuery = eventStatusFilter ? `&status=${eventStatusFilter}` : '';
    const extensionEvents = useResource<ExtensionEventPage>(
        admin ? `/extensions/events?page=${eventPage}&page_size=${eventPageSize}${eventQuery}` : null,
        5000,
    );
    const eventAction = useAction();
    const [runPage, setRunPage] = useState(1);
    const [runPageSize, setRunPageSize] = useState(PAGE_SIZE);
    const runs = useResource<Paged<Run>>(`/observability/runs?page=${runPage}&page_size=${runPageSize}`, 3000);
    const [auditPage, setAuditPage] = useState(1);
    const [auditPageSize, setAuditPageSize] = useState(PAGE_SIZE);
    const [auditActionType, setAuditActionType] = useState<string>();
    const auditTypeQuery = auditActionType ? `&action_type=${encodeURIComponent(auditActionType)}` : '';
    const audit = useResource<AuditPaged>(admin ? `/audit?page=${auditPage}&page_size=${auditPageSize}${auditTypeQuery}` : null, 5000);
    const [memoryWindow, setMemoryWindow] = useState(24);
    const memory = useResource<MemorySummary>(`/observability/memory?window_hours=${memoryWindow}`, 5000);
    const memoryAlerts = useResource<MemoryAlert[]>(`/observability/memory/alerts?window_hours=${memoryWindow}`, 5000);
    const [selected, setSelected] = useState<string | null>(null);
    const gateways = useResource<GatewaySummary>('/observability/gateways', 5000);
    const correlation = useResource<Record<string, unknown>>(selected ? `/observability/runs/${selected}/trace` : null);

    const runColumns: TableColumnsType<Run> = [
        {
            title: t("运行"), dataIndex: 'id', width: 150,
            render: (id: string, run) => <>
                <button className="text-button mono" onClick={() => setSelected(id)}>{id.slice(0, 8)}</button>
                {run.error_code && <><br/><small className="error-text">{run.error_code}</small></>}
            </>,
        },
        { title: t("状态"), dataIndex: 'status', width: 100, render: (value: string) => <Badge value={value}/> },
        {
            title: t("首字延迟"), dataIndex: 'ttfc_ms', width: 110,
            render: (value: number | null | undefined) => value == null ? t("未测量") : `${Math.round(Number(value))}ms`,
        },
        { title: t("创建时间"), dataIndex: 'created_at', width: 175, render: (value: string) => time(value) },
    ];

    const auditColumns: TableColumnsType<Audit> = [
        { title: t("操作"), dataIndex: 'action', render: (value: string) => <span className="mono">{value}</span> },
        { title: t("操作者"), dataIndex: 'actor', ellipsis: true },
        { title: t("访问 IP"), dataIndex: 'ip', width: 150, render: (value?: string | null) => <span className="mono">{value || '—'}</span> },
        { title: t("资源"), dataIndex: 'resource', width: 150, render: (value: string) => <span className="mono">{value.slice(0, 12)}</span> },
        { title: t("时间"), dataIndex: 'created_at', width: 175, render: (value: string) => time(value) },
    ];

    const extractionColumns: TableColumnsType<MemoryExtractionDay> = [
        { title: t("日期"), dataIndex: 'day', render: (value: string) => value.slice(0, 10) },
        { title: t("运行"), dataIndex: 'runs' },
        { title: t("新增"), dataIndex: 'added' },
        { title: t("更新"), dataIndex: 'updated' },
        { title: t("待确认"), dataIndex: 'pending' },
        { title: t("丢弃"), dataIndex: 'dropped' },
        { title: t("脱敏"), dataIndex: 'pii_masked' },
    ];

    const governanceColumns: TableColumnsType<{ action: string; n: number }> = [
        { title: t("操作"), dataIndex: 'action', render: (value: string) => <span className="mono">{value}</span> },
        { title: t("次数"), dataIndex: 'n' },
    ];

    const memoryAlertColumns: TableColumnsType<MemoryAlert> = [
        { title: t("时间"), dataIndex: 'at', width: 175, render: (value: string) => time(value) },
        { title: t("规则"), dataIndex: 'rule', render: (value: string) => memoryAlertRuleLabel(value) },
        { title: t("当前值"), dataIndex: 'value', render: (value: number | null) => value ?? '—' },
        { title: t("阈值"), dataIndex: 'threshold', render: (value: number | null) => value ?? '—' },
    ];

    const modelColumns: TableColumnsType<GatewayModel> = [
        { title: t("操作"), dataIndex: 'operation' },
        { title: t("状态"), dataIndex: 'status', render: (value: string) => <Badge value={value}/> },
        { title: t("次数"), dataIndex: 'calls' },
        { title: t("平均耗时"), dataIndex: 'average_ms', render: (value: number) => `${Math.round(Number(value))}ms` },
        { title: t("P95 耗时"), dataIndex: 'p95_ms', render: (value: number) => `${Math.round(Number(value))}ms` },
    ];

    const toolColumns: TableColumnsType<GatewayTool> = [
        { title: t("适配器"), dataIndex: 'adapter_type' },
        { title: t("效果"), dataIndex: 'effect' },
        { title: t("状态"), dataIndex: 'status', render: (value: string) => <Badge value={value}/> },
        { title: t("次数"), dataIndex: 'calls' },
        { title: t("平均耗时"), dataIndex: 'average_ms', render: (value: number) => `${Math.round(Number(value))}ms` },
    ];

    const usageColumns: TableColumnsType<GatewayUsage> = [
        { title: t("操作"), dataIndex: 'operation' },
        { title: t("单位"), dataIndex: 'unit' },
        { title: t("数量"), dataIndex: 'amount', render: (value: number) => Number(value).toLocaleString() },
    ];

    const capabilityColumns: TableColumnsType<CapabilityStatusItem> = [
        { title: t("能力"), dataIndex: 'capability_id', render: (value: string) => <span className="mono">{value}</span> },
        { title: t("版本"), dataIndex: 'version', render: (value: string) => <span className="mono">v{value}</span> },
        { title: t("状态"), dataIndex: 'status', render: (value: CapabilityStatusItem['status']) => capabilityStatus(value) },
        { title: t("失败次数"), dataIndex: 'failure_count' },
        { title: t("最近失败"), dataIndex: 'last_failure_at', render: (value: string | null) => value ? time(value) : '—' },
        { title: t("原因"), dataIndex: 'reason', render: (value: string | null) => value || '—' },
    ];

    const eventColumns: TableColumnsType<ExtensionEventPage['items'][number]> = [
        { title: t("事件类型"), dataIndex: 'event_type', render: (value: string) => <span className="mono">{value}</span> },
        {
            title: t("聚合对象"),
            key: 'aggregate',
            render: (_, row) => <span className="mono">{row.aggregate_type}:{row.aggregate_id.slice(0, 12)}</span>,
        },
        { title: t("状态"), dataIndex: 'status', render: (value: ExtensionEventStatus) => eventStatus(value) },
        { title: t("尝试次数"), key: 'attempts', render: (_, row) => `${row.attempts}/${row.max_attempts}` },
        { title: t("错误"), dataIndex: 'error', render: (value: string | null) => value || '—' },
        { title: t("创建时间"), dataIndex: 'created_at', render: (value: string) => time(value) },
        {
            title: t("操作"),
            key: 'actions',
            render: (_, row) => row.status === 'failed' ? (
                <Popconfirm
                    title={t("确认重新投递此事件？")}
                    onConfirm={() => eventAction.run(async () => {
                        await retryExtensionEvent(row.id);
                        extensionEvents.refresh();
                        extensions.refresh();
                    }, t("事件已重新排队"))}
                >
                    <Button type="link" size="small" loading={eventAction.busy}>{t("重试")}</Button>
                </Popconfirm>
            ) : null,
        },
    ];

    return <>
        <Alert error={eventAction.error || extensions.error || extensionEvents.error || gateways.error || correlation.error || summary.error || runs.error || audit.error || memory.error || memoryAlerts.error}/>
        <Metrics value={summary.data}/>
        <Panel title={t("记忆观测")} action={
            <Select
                aria-label={t("统计窗口")}
                style={{ width: 220 }}
                value={memoryWindow}
                onChange={setMemoryWindow}
                options={[{ value: 24, label: t("近 24 小时") }, { value: 168, label: t("近 7 天") }]}
            />
        }>
            <MemoryMetrics value={memory.data}/>
            {memory.data && memory.data.extraction_daily.length > 0 && <details>
                <summary>{t("记忆抽取量（近 7 天）")}</summary>
                <Table<MemoryExtractionDay> rowKey="day" size="small" columns={extractionColumns}
                    dataSource={memory.data.extraction_daily} pagination={clientPagination} scroll={{ x: 700 }}/>
            </details>}
            {memory.data && memory.data.governance.length > 0 && <details>
                <summary>{t("治理操作（近 24 小时）")}</summary>
                <Table<{ action: string; n: number }> rowKey="action" size="small" columns={governanceColumns}
                    dataSource={memory.data.governance} pagination={clientPagination}/>
            </details>}
        </Panel>
        <Panel title={t("记忆告警")}>
            <Table<MemoryAlert> rowKey={row => `${row.rule}-${row.at}`} size="small" loading={memoryAlerts.loading} columns={memoryAlertColumns}
                dataSource={memoryAlerts.data || []} pagination={clientPagination} locale={{ emptyText: t("暂无告警事件") }}/>
        </Panel>
        <Panel title={t("扩展运行状态")}>
            <div className="metrics">
                {[
                    [t("扩展总数"), extensions.data?.capabilities.summary.total],
                    [t("就绪能力"), extensions.data?.capabilities.summary.by_status.ready],
                    [t("降级能力"), extensions.data?.capabilities.summary.by_status.degraded],
                    [t("待投递事件"), extensions.data?.events.queue?.pending ?? 0],
                    [t("失败事件"), extensions.data?.events.queue?.failed ?? 0],
                    [t("投递失败"), extensions.data?.events.failures ?? 0],
                ].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value ?? '—'}</strong></div>)}
            </div>
            <Table<CapabilityStatusItem>
                rowKey="capability_id"
                size="small"
                loading={extensions.loading}
                columns={capabilityColumns}
                dataSource={extensions.data?.capabilities.items || []}
                locale={{ emptyText: t("暂无能力状态") }}
                scroll={{ x: 760 }}
            />
        </Panel>
        {admin && <Panel title={t("事件投递运维")} action={
            <Space>
                <Select
                    aria-label={t("事件状态")}
                    allowClear
                    placeholder={t("全部状态")}
                    value={eventStatusFilter}
                    onChange={(value?: ExtensionEventStatus) => {
                        setEventStatusFilter(value);
                        setEventPage(1);
                    }}
                    options={[
                        { value: 'pending', label: t("待投递") },
                        { value: 'running', label: t("投递中") },
                        { value: 'done', label: t("已完成") },
                        { value: 'failed', label: t("失败") },
                    ]}
                />
            </Space>
        }>
            <Table<ExtensionEventPage['items'][number]>
                rowKey="id"
                size="small"
                loading={extensionEvents.loading}
                columns={eventColumns}
                dataSource={extensionEvents.data?.items || []}
                locale={{ emptyText: eventStatusFilter ? t("暂无符合条件的事件") : t("暂无事件") }}
                scroll={{ x: 1100 }}
                pagination={serverPagination(eventPage, eventPageSize, extensionEvents.data?.total || 0, (page, size) => {
                    setEventPage(size === eventPageSize ? page : 1);
                    setEventPageSize(size);
                })}
            />
        </Panel>}
        <div className="split">
            <Panel title={t("最近运行")}>
                <Table<Run> rowKey="id" size="small" loading={runs.loading} columns={runColumns}
                    dataSource={runs.data?.items || []} scroll={{ x: 560 }} locale={{ emptyText: t("暂无数据") }}
                    pagination={serverPagination(runPage, runPageSize, runs.data?.total || 0, (page, size) => {
                        setRunPage(size === runPageSize ? page : 1);
                        setRunPageSize(size);
                    })}/>
            </Panel>
            <Panel title={t("运行详情")}>
                <Trace runId={selected}/>
                {correlation.data && <details><summary>{t("模型与工具调用关联")}</summary><pre>{JSON.stringify(correlation.data, null, 2)}</pre></details>}
            </Panel>
        </div>
        <Panel title={t("近 24 小时网关计量")}>
            <p>{t("按操作、结果和计量单位分别统计；未返回的用量不按零计算。")}</p>
            <h3 className="gateway-group-title">{t("模型调用")}</h3>
            <Table<GatewayModel> rowKey={row => `${row.operation}-${row.status}`} size="small" columns={modelColumns}
                dataSource={gateways.data?.models || []} pagination={clientPagination} scroll={{ x: 640 }} locale={{ emptyText: t("暂无数据") }}/>
            <h3 className="gateway-group-title">{t("工具调用")}</h3>
            <Table<GatewayTool> rowKey={row => `${row.adapter_type}-${row.effect}-${row.status}`} size="small" columns={toolColumns}
                dataSource={gateways.data?.tools || []} pagination={clientPagination} scroll={{ x: 640 }} locale={{ emptyText: t("暂无数据") }}/>
            <h3 className="gateway-group-title">{t("用量")}</h3>
            <Table<GatewayUsage> rowKey={row => `${row.operation}-${row.unit}`} size="small" columns={usageColumns}
                dataSource={gateways.data?.known_usage || []} pagination={clientPagination} locale={{ emptyText: t("暂无数据") }}/>
        </Panel>
        {admin && <Panel title={t("操作审计")} action={
            <Select
                aria-label={t("操作类型")}
                className="audit-type-filter"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder={t("全部类型")}
                value={auditActionType}
                onChange={(value?: string) => {
                    setAuditActionType(value);
                    setAuditPage(1);
                }}
                options={(audit.data?.action_types || []).map(item => ({
                    value: item.action,
                    label: `${item.action} (${item.count})`,
                }))}
            />
        }>
            <Table<Audit> rowKey="id" size="small" loading={audit.loading} columns={auditColumns}
                dataSource={audit.data?.items || []} scroll={{ x: 920 }}
                locale={{ emptyText: auditActionType ? t("暂无符合条件的审计记录") : t("暂无记录") }}
                pagination={serverPagination(auditPage, auditPageSize, audit.data?.total || 0, (page, size) => {
                    setAuditPage(size === auditPageSize ? page : 1);
                    setAuditPageSize(size);
                })}/>
        </Panel>}
    </>;
}
