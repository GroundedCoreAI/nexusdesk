import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import {
    BugOutlined,
    CommentOutlined,
    CustomerServiceOutlined,
    InboxOutlined,
    ReloadOutlined,
    SearchOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Drawer,
    Empty,
    Input,
    Select,
    Spin,
    Table,
    Tag,
    Tooltip,
    Typography,
    type TableColumnsType,
} from 'antd';
import { dateTime } from '../../../i18n/index';
import {
    getApplicationConversation,
    getApplicationTurnDiagnostics,
    listApplicationConversations,
} from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationConversation,
    type ApplicationConversationDetail,
    type ApplicationConversationMessage,
    type ApplicationConversationRun,
    type ApplicationConversationTurn,
    type ApplicationDetail,
    type ApplicationTurnDiagnostics,
    type ConversationAnswerStatus,
} from '../contracts';
import { RunDiagnostics, type RunTrace } from '../components/RunDiagnostics';
import { useAccess } from '../../../shared/components/ui';
import { say } from '../labels';
import './conversation-records.css';

type StatusFilter = ConversationAnswerStatus | 'all';

const statusColors: Record<string, string> = {
    completed: 'green',
    failed: 'red',
    running: 'processing',
    queued: 'gold',
    cancelled: 'default',
    bot: 'blue',
    waiting: 'orange',
    human: 'cyan',
    closed: 'default',
    unknown: 'default',
};

function answerStatusLabel(status: string) {
    if (status === 'completed') return say('已完成');
    if (status === 'failed') return say('失败');
    if (status === 'running') return say('处理中');
    if (status === 'queued') return say('排队中');
    if (status === 'cancelled') return say('已取消');
    if (status === 'bot') return say('机器人');
    if (status === 'waiting') return say('待接管');
    if (status === 'human') return say('人工处理');
    if (status === 'closed') return say('已关闭');
    return say('未知');
}

function messageRoleLabel(role: string) {
    if (role === 'user' || role === 'customer') return say('客户');
    if (role === 'assistant') return say('应用回复');
    if (role === 'human') return say('人工回复');
    return say('系统');
}

function runStatusLabel(status: string) {
    if (status === 'completed') return say('已完成');
    if (status === 'failed') return say('失败');
    if (status === 'running') return say('运行中');
    if (status === 'queued') return say('排队中');
    if (status === 'cancelled') return say('已取消');
    return status;
}

function runStatusColor(status: string) {
    if (status === 'completed') return 'green';
    if (status === 'failed') return 'red';
    if (status === 'running') return 'processing';
    if (status === 'queued') return 'gold';
    return 'default';
}

function shortId(value: string) {
    return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

/** Open-platform visitors only carry a technical external id; make it readable. */
function visitorLabel(account: string | null | undefined, userName: string | null | undefined) {
    if (userName) return userName;
    if (!account) return '—';
    const match = account.match(/^enterprise:([0-9a-f]{8})/i);
    return match ? `${say('企业用户')} · ${match[1]}` : account;
}

function fmtDuration(start: string | null | undefined, end: string | null | undefined) {
    if (!start || !end) return '—';
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (!Number.isFinite(ms) || ms < 0) return '—';
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    const total = Math.round(ms / 1000);
    return `${Math.floor(total / 60)} min ${total % 60} s`;
}

/** Conversations created outside a channel object come from the open platform. */
function isPlatformConversation(conversation: ApplicationConversation) {
    return !conversation.channel_name;
}

function isCustomerConversation(conversation: ApplicationConversation) {
    return conversation.kind === 'customer';
}

function ConversationMessage({
    message,
    duration,
}: {
    message: ApplicationConversationMessage;
    duration?: string;
}) {
    // Ledger roles are customer/assistant; the bubble styles are keyed by
    // user/human/system, so map the customer role onto the user bubble.
    const bubbleRole = message.role === 'customer' ? 'user' : message.role;
    return <div className={`sa-conversation-message ${bubbleRole}`}>
        <div className="sa-conversation-message-meta">
            <span>{messageRoleLabel(message.role)}</span>
            {message.content_type !== 'text' && <Tag>{message.content_type}</Tag>}
            {duration && duration !== '—' && <small>{say('耗时')} {duration}</small>}
            {message.created_at && <small>{dateTime(message.created_at)}</small>}
        </div>
        <p>{message.content || say('暂无内容')}</p>
    </div>;
}

export function ConversationRecordsTab({
    application,
}: {
    application: ApplicationDetail;
}) {
    const [items, setItems] = useState<ApplicationConversation[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [queryInput, setQueryInput] = useState('');
    const [query, setQuery] = useState('');
    const [channelId, setChannelId] = useState<string>();
    const [status, setStatus] = useState<StatusFilter>('all');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [refreshKey, setRefreshKey] = useState(0);
    const [detailOpen, setDetailOpen] = useState(false);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState('');
    const [detail, setDetail] = useState<ApplicationConversationDetail | null>(null);
    const [diagnosticTurn, setDiagnosticTurn] = useState<ApplicationConversationTurn | null>(null);
    const [diagnostic, setDiagnostic] = useState<ApplicationTurnDiagnostics | null>(null);
    const [diagnosticLoading, setDiagnosticLoading] = useState(false);
    const [diagnosticError, setDiagnosticError] = useState('');
    const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pollCount = useRef(0);
    const { operator } = useAccess();

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        listApplicationConversations(application.key, {
            page,
            pageSize,
            query,
            channelId,
            status,
        })
            .then(result => {
                if (!active) return;
                setItems(result.items.filter(isCustomerConversation));
                // The backend paginates the customer ledger. Keep its authoritative
                // total even if a malformed response slips a non-customer row in.
                setTotal(result.total);
            })
            .catch(cause => {
                if (active) {
                    setItems([]);
                    setTotal(0);
                    setError(cause instanceof Error ? cause.message : say('加载失败'));
                }
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [application.key, channelId, page, pageSize, query, refreshKey, status]);

    // Turn boundaries for the thread: a divider goes before the customer
    // message that opens each turn, and the answer duration rides on the
    // assistant message of the same turn.
    const turnMarkers = useMemo(() => {
        const roundByCustomer = new Map<string, number>();
        const durationByAssistant = new Map<string, string>();
        (detail?.turns || []).forEach((turn, index) => {
            if (turn.customer_message_id) {
                roundByCustomer.set(turn.customer_message_id, index + 1);
            }
            if (turn.assistant_message_id) {
                durationByAssistant.set(
                    turn.assistant_message_id,
                    fmtDuration(turn.created_at, turn.finished_at),
                );
            }
        });
        return { roundByCustomer, durationByAssistant };
    }, [detail]);

    const channelOptions = useMemo(() => [
        { value: '', label: say('全部渠道') },
        ...application.channels.map(channel => ({
            value: channel.id,
            label: channel.name,
        })),
    ], [application.channels]);

    const statusOptions = [
        { value: 'all', label: say('全部状态') },
        { value: 'completed', label: say('已完成') },
        { value: 'failed', label: say('失败') },
        { value: 'running', label: say('处理中') },
        { value: 'queued', label: say('排队中') },
        { value: 'waiting', label: say('待接管') },
        { value: 'human', label: say('人工处理') },
    ];

    function search() {
        setPage(1);
        setQuery(queryInput.trim());
    }

    function resetFilters() {
        setQueryInput('');
        setQuery('');
        setChannelId(undefined);
        setStatus('all');
        setPage(1);
    }

    async function openDetail(conversation: ApplicationConversation) {
        if (!isCustomerConversation(conversation)) return;
        setDetailOpen(true);
        setDetail(null);
        setDetailError('');
        setDetailLoading(true);
        try {
            setDetail(await getApplicationConversation(application.key, conversation.id));
        } catch (cause) {
            setDetailError(cause instanceof Error ? cause.message : say('加载失败'));
        } finally {
            setDetailLoading(false);
        }
    }

    // A queued or running turn fills in as events land. Stop after ~30s so an
    // abandoned drawer cannot keep polling in the background.
    async function fetchDiagnostics(turn: ApplicationConversationTurn, conversationId: string) {
        setDiagnosticLoading(true);
        try {
            const value = await getApplicationTurnDiagnostics(
                application.key,
                conversationId,
                turn.id,
            );
            setDiagnostic(value);
            setDiagnosticError('');
            if (
                (value.status === 'running' || value.status === 'queued')
                && pollCount.current < 15
            ) {
                pollCount.current += 1;
                pollTimer.current = setTimeout(
                    () => void fetchDiagnostics(turn, conversationId),
                    2000,
                );
            }
        } catch (cause) {
            setDiagnosticError(cause instanceof Error ? cause.message : say('加载失败'));
        } finally {
            setDiagnosticLoading(false);
        }
    }

    function openDiagnostics(turn: ApplicationConversationTurn) {
        if (!detail) return;
        if (pollTimer.current) clearTimeout(pollTimer.current);
        pollCount.current = 0;
        setDiagnosticTurn(turn);
        setDiagnostic(null);
        setDiagnosticError('');
        void fetchDiagnostics(turn, detail.id);
    }

    function closeDiagnostics() {
        if (pollTimer.current) clearTimeout(pollTimer.current);
        pollCount.current = 0;
        setDiagnosticTurn(null);
        setDiagnostic(null);
    }

    useEffect(() => () => {
        if (pollTimer.current) clearTimeout(pollTimer.current);
    }, []);

    const columns: TableColumnsType<ApplicationConversation> = [
        {
            title: say('问题'),
            dataIndex: 'question',
            width: 250,
            render: (value, conversation) => <div className="sa-conversation-summary-cell">
                <strong>{value || say('暂无问题')}</strong>
                <span>
                    {conversation.updated_at ? dateTime(conversation.updated_at) : '—'}
                    {' · '}
                    {say('{{v0}} 条消息', { v0: conversation.message_count })}
                    {conversation.turn_count !== undefined
                        ? ` · ${say('{{v0}} 轮对话', { v0: conversation.turn_count })}`
                        : ''}
                </span>
            </div>,
        },
        {
            title: say('回答'),
            dataIndex: 'answer',
            width: 270,
            render: value => <div className="sa-conversation-answer-cell">
                {value || <span className="muted">{say('暂无回答')}</span>}
            </div>,
        },
        {
            title: say('回答状态'),
            dataIndex: 'status',
            width: 105,
            render: (value, conversation) => {
                const displayStatus = conversation.last_turn_status || value;
                return <Tag color={statusColors[displayStatus] || 'default'}>
                    {answerStatusLabel(displayStatus)}
                </Tag>;
            },
        },
        {
            title: say('来源'),
            dataIndex: 'channel_name',
            width: 150,
            render: (_, conversation) => isPlatformConversation(conversation)
                ? <Tag color="purple">{say('开放平台')}</Tag>
                : <div className="sa-table-primary compact">
                    <strong>{conversation.channel_name}</strong>
                    <span className="mono">{conversation.source}</span>
                </div>,
        },
        {
            title: say('访客'),
            key: 'visitor',
            width: 160,
            ellipsis: true,
            render: (_, conversation) => visitorLabel(conversation.account, conversation.user_name),
        },
        {
            title: say('对话名称'),
            dataIndex: 'conversation_title',
            width: 190,
            ellipsis: true,
            render: (value, conversation) => <Tooltip title={value || conversation.id}>
                <span>{value || shortId(conversation.id)}</span>
            </Tooltip>,
        },
        {
            title: say('操作'),
            key: 'actions',
            width: 120,
            fixed: 'right',
            render: (_, conversation) => <Button type="link" onClick={() => void openDetail(conversation)}>
                {say('查看完整对话')}
            </Button>,
        },
    ];

    const turnColumns: TableColumnsType<ApplicationConversationTurn> = [
        {
            title: '#',
            key: 'index',
            width: 44,
            render: (_, _record, index) => index + 1,
        },
        {
            title: say('状态'),
            dataIndex: 'status',
            width: 100,
            render: value => <Tag color={runStatusColor(value)}>
                {answerStatusLabel(value)}
            </Tag>,
        },
        {
            title: say('开始时间'),
            dataIndex: 'created_at',
            width: 170,
            render: value => value ? dateTime(value) : '—',
        },
        {
            title: say('耗时'),
            key: 'duration',
            width: 110,
            render: (_, turn) => fmtDuration(turn.created_at, turn.finished_at),
        },
        {
            title: say('版本'),
            key: 'versions',
            width: 110,
            render: (_, turn) => <span className="mono">
                {turn.application_version ? `v${turn.application_version}` : '—'}
                {' / '}
                {turn.agent_version ? `v${turn.agent_version}` : '—'}
            </span>,
        },
        {
            title: say('错误码'),
            dataIndex: 'error_code',
            width: 150,
            render: value => value || '—',
        },
    ];

    // The trace is a run-time inspection tool, so it stays with operators.
    if (operator) {
        turnColumns.push({
            title: say('诊断'),
            key: 'diagnostics',
            width: 110,
            render: (_, turn) => <Button
                type="link"
                size="small"
                icon={<BugOutlined/>}
                onClick={() => openDiagnostics(turn)}
            >
                {say('查看诊断')}
            </Button>,
        });
    }

    const turnIdRow = (label: string, value: string | null | undefined) => value
        ? <div className="sa-conversation-turn-ids-row">
            <small>{label}</small>
            <Tooltip title={value}>
                <Typography.Text className="mono" copyable={{ text: value, tooltips: [say('复制'), say('复制成功')] }}>
                    {shortId(value)}
                </Typography.Text>
            </Tooltip>
        </div>
        : null;

    const runColumns: TableColumnsType<ApplicationConversationRun> = [
        {
            title: say('运行状态'),
            dataIndex: 'status',
            width: 110,
            render: value => <Tag color={runStatusColor(value)}>{runStatusLabel(value)}</Tag>,
        },
        {
            title: 'Run ID',
            dataIndex: 'id',
            render: value => <Tooltip title={value}>
                <Typography.Text className="mono" copyable={{ text: value, tooltips: [say('复制'), say('复制成功')] }}>
                    {shortId(value)}
                </Typography.Text>
            </Tooltip>,
        },
        {
            title: say('开始时间'),
            dataIndex: 'started_at',
            width: 170,
            render: value => value ? dateTime(value) : '—',
        },
        {
            title: say('耗时'),
            key: 'duration',
            width: 110,
            render: (_, run) => fmtDuration(run.started_at, run.finished_at),
        },
        {
            title: say('错误码'),
            dataIndex: 'error_code',
            width: 160,
            render: value => value || '—',
        },
    ];

    return <div className="sa-conversation-records-tab">
        <section className="sa-conversation-records-hero">
            <div>
                <span className="sa-eyebrow">{say('客户对话')}</span>
                <h3>{say('对话记录')}</h3>
                <p>{say('仅展示通过客服渠道产生的真实业务会话，不包含体验与调试中的实时预览记录。')}</p>
            </div>
            <div className="sa-conversation-records-count">
                <span>{say('会话总数')}</span>
                <strong>{total}</strong>
            </div>
        </section>

        {error && <Alert
            type="error"
            showIcon
            message={error}
            action={<Button size="small" onClick={() => setRefreshKey(value => value + 1)}>
                {say('重试')}
            </Button>}
        />}

        <section className="sa-conversation-records-panel">
            <div className="sa-conversation-records-toolbar">
                <Input
                    allowClear
                    value={queryInput}
                    prefix={<SearchOutlined/>}
                    placeholder={say('搜索问题、回答、渠道或账号')}
                    onChange={event => setQueryInput(event.target.value)}
                    onPressEnter={search}
                />
                <Select
                    value={channelId || ''}
                    options={channelOptions}
                    onChange={value => {
                        setChannelId(value || undefined);
                        setPage(1);
                    }}
                />
                <Select<StatusFilter>
                    value={status}
                    options={statusOptions}
                    onChange={value => {
                        setStatus(value);
                        setPage(1);
                    }}
                />
                <Button type="primary" icon={<SearchOutlined/>} onClick={search}>
                    {say('搜索')}
                </Button>
                <Button icon={<ReloadOutlined/>} onClick={resetFilters}>
                    {say('重置')}
                </Button>
            </div>

            <Table<ApplicationConversation>
                className="sa-ant-table sa-conversation-records-table"
                rowKey="id"
                columns={columns}
                dataSource={items}
                loading={loading}
                size="middle"
                scroll={{ x: 1250 }}
                pagination={{
                    current: page,
                    pageSize,
                    total,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50],
                    position: ['bottomRight'],
                    showTotal: value => say('共 {{v0}} 条', { v0: value }),
                    onChange: (nextPage, nextPageSize) => {
                        setPage(nextPageSize !== pageSize ? 1 : nextPage);
                        setPageSize(nextPageSize);
                    },
                }}
                locale={{
                    emptyText: <div className="sa-table-empty">
                        <InboxOutlined/>
                        <span>{say('暂无真实客户对话记录')}</span>
                        <small>{say('客户通过渠道产生消息后，会话会自动出现在这里。')}</small>
                    </div>,
                }}
            />
        </section>

        <Drawer
            open={detailOpen}
            onClose={() => setDetailOpen(false)}
            width={920}
            title={say('完整对话')}
            // The drawer portals to body, outside the .module-service-apps
            // shell; re-attach the scope so themed styles apply inside.
            rootClassName="module-service-apps"
            destroyOnHidden
            extra={detail
                ? <Tag color={statusColors[detail.last_turn_status || detail.status] || 'default'}>
                    {answerStatusLabel(detail.last_turn_status || detail.status)}
                </Tag>
                : null}
        >
            {detailError && <Alert type="error" showIcon message={detailError}/>}
            {detailLoading
                ? <div className="sa-conversation-detail-loading"><Spin/></div>
                : detail
                    ? <div className="sa-conversation-detail">
                        <header className="sa-conversation-detail-header">
                            <div className="sa-conversation-detail-title">
                                <CustomerServiceOutlined/>
                                <div>
                                    <h4>{detail.conversation_title || shortId(detail.id)}</h4>
                                    <span className="mono">{detail.id}</span>
                                </div>
                            </div>
                            <div className="sa-conversation-detail-meta">
                                <div>
                                    <span>{say('来源')}</span>
                                    <strong>
                                        {detail.channel_name || say('开放平台')}
                                    </strong>
                                </div>
                                <div>
                                    <span>{say('访客')}</span>
                                    <strong>{visitorLabel(detail.account, detail.user_name)}</strong>
                                </div>
                                <div>
                                    <span>{say('应用版本')}</span>
                                    <strong>{detail.application_version ? `v${detail.application_version}` : '—'}</strong>
                                </div>
                                <div>
                                    <span>{say('消息数')}</span>
                                    <strong>
                                        {say('{{v0}} 条消息', { v0: detail.message_count })}
                                        {' · '}
                                        {say('{{v0}} 轮对话', { v0: detail.turn_count ?? detail.turns.length })}
                                    </strong>
                                </div>
                                <div>
                                    <span>{say('最后更新')}</span>
                                    <strong>{detail.updated_at ? dateTime(detail.updated_at) : '—'}</strong>
                                </div>
                            </div>
                        </header>

                        {detail.messages_truncated && <Alert
                            type="warning"
                            showIcon
                            message={say('对话过长，仅展示最近 500 条消息。')}
                        />}

                        <section className="sa-conversation-detail-section">
                            <div className="sa-section-head">
                                <div>
                                    <span className="sa-eyebrow">{say('客户消息')}</span>
                                    <h4>{say('客户对话')}</h4>
                                </div>
                                <Tag icon={<CommentOutlined/>}>
                                    {say('{{v0}} 条消息', { v0: detail.messages.length })}
                                </Tag>
                            </div>
                            <p className="sa-conversation-section-note">
                                {say('客服业务消息仅包含客户可见内容，Agent 执行事件不会进入客户对话。')}
                            </p>
                            {detail.messages.length
                                ? <div className="sa-conversation-thread">
                                    {detail.messages.map(message => <Fragment key={message.id}>
                                        {turnMarkers.roundByCustomer.has(message.id)
                                            ? <div className="sa-conversation-turn-divider">
                                                <span>
                                                    {say('第 {{v0}} 轮', { v0: turnMarkers.roundByCustomer.get(message.id) })}
                                                </span>
                                            </div>
                                            : null}
                                        <ConversationMessage
                                            message={message}
                                            duration={turnMarkers.durationByAssistant.get(message.id)}
                                        />
                                    </Fragment>)}
                                </div>
                                : <Empty description={say('暂无消息')}/>}
                        </section>

                        <section className="sa-conversation-detail-section">
                            <div className="sa-section-head">
                                <div>
                                    <span className="sa-eyebrow">{say('运行信息')}</span>
                                    <h4>{say('Agent 运行诊断')}</h4>
                                </div>
                            </div>
                            <p className="sa-conversation-section-note">
                                {say('以下数据用于关联客服业务轮次与 Agent 执行过程，不进入客户对话记录。')}
                            </p>

                            <div className="sa-conversation-diagnostic-block">
                                <div className="sa-conversation-diagnostic-head">
                                    <h5>{say('对话轮次')}</h5>
                                    <Tag>{detail.turns.length}</Tag>
                                </div>
                                <Table<ApplicationConversationTurn>
                                    className="sa-ant-table sa-conversation-diagnostic-table"
                                    rowKey="id"
                                    columns={turnColumns}
                                    dataSource={detail.turns}
                                    size="small"
                                    scroll={{ x: operator ? 800 : 690 }}
                                    pagination={false}
                                    expandable={{
                                        rowExpandable: turn => Boolean(
                                            turn.customer_message_id
                                            || turn.assistant_message_id
                                            || turn.runtime_conversation_id
                                            || turn.runtime_run_id,
                                        ),
                                        expandedRowRender: turn => <div className="sa-conversation-turn-ids">
                                            {turnIdRow(say('客户消息 ID'), turn.customer_message_id)}
                                            {turnIdRow(say('助手消息 ID'), turn.assistant_message_id)}
                                            {turnIdRow('Runtime conversation', turn.runtime_conversation_id)}
                                            {turnIdRow('Runtime run', turn.runtime_run_id)}
                                        </div>,
                                    }}
                                    locale={{ emptyText: say('暂无对话轮次') }}
                                />
                            </div>

                            <div className="sa-conversation-diagnostic-block">
                                <div className="sa-conversation-diagnostic-head">
                                    <h5>{say('Agent 运行')}</h5>
                                    <Tag>{detail.runs.length}</Tag>
                                </div>
                                <Table<ApplicationConversationRun>
                                    className="sa-ant-table sa-conversation-diagnostic-table"
                                    rowKey="id"
                                    columns={runColumns}
                                    dataSource={detail.runs}
                                    size="small"
                                    scroll={{ x: 760 }}
                                    pagination={false}
                                    locale={{ emptyText: say('暂无 Agent 运行诊断') }}
                                />
                            </div>
                        </section>
                    </div>
                    : <Empty description={say('暂无对话详情')}/>}
        </Drawer>

        <Drawer
            open={Boolean(diagnosticTurn)}
            onClose={closeDiagnostics}
            width={720}
            title={say('诊断详情')}
            rootClassName="module-service-apps"
            destroyOnHidden
            extra={diagnosticTurn
                ? <Tag color={statusColors[diagnosticTurn.status] || 'default'}>
                    {answerStatusLabel(diagnosticTurn.status)}
                </Tag>
                : null}
        >
            {diagnosticError && <Alert type="error" showIcon message={diagnosticError}/>}
            {diagnostic
                ? <RunDiagnostics
                    status={diagnostic.status}
                    runId={diagnostic.run_id}
                    input={diagnostic.input}
                    reply={diagnostic.reply}
                    error={diagnostic.error_code}
                    skills={diagnostic.skills}
                    trace={diagnostic.trace as RunTrace}
                    createdAt={diagnostic.created_at}
                    unavailableReason={diagnostic.available
                        ? null
                        : diagnostic.reason || 'run_events_missing'}
                    meta={[
                        {
                            label: say('应用版本'),
                            value: diagnostic.application_version
                                ? `v${diagnostic.application_version}`
                                : '—',
                        },
                        {
                            label: say('Agent 版本'),
                            value: diagnostic.agent_version ? `v${diagnostic.agent_version}` : '—',
                        },
                        {
                            label: say('耗时'),
                            value: diagnostic.duration_ms != null
                                ? `${diagnostic.duration_ms} ms`
                                : '—',
                        },
                    ]}
                />
                : diagnosticLoading
                    ? <div className="sa-conversation-detail-loading"><Spin/></div>
                    : <Empty description={say('暂无诊断数据')}/>}
        </Drawer>
    </div>;
}
