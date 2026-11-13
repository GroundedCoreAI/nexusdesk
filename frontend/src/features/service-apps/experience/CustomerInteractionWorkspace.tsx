import { useEffect, useMemo, useRef, useState } from 'react';
import {
    AppstoreOutlined,
    BugOutlined,
    CheckCircleFilled,
    CustomerServiceOutlined,
    FormOutlined,
    HistoryOutlined,
    LoadingOutlined,
    MessageOutlined,
    ReloadOutlined,
    RightOutlined,
    SafetyCertificateOutlined,
    SendOutlined,
    SettingOutlined,
    UserOutlined,
    WarningFilled,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Drawer,
    Empty,
    Input,
    Segmented,
    Switch,
    Table,
    Tag,
    Timeline,
} from 'antd';
import type { TableProps } from 'antd';
import { dateTime } from '../../../i18n/index';
import { useAccess } from '../../../shared/components/ui';
import { getApplicationExperience, previewApplication } from '../api';
import type {
    ApplicationDetail,
    ApplicationPreviewResult,
    ExperienceCategory,
    ExperienceEntry,
    ServiceExperienceConfig,
} from '../contracts';
import { say, skillTypeLabel } from '../labels';
import './customer-interaction.css';

type PreviewScope = 'draft' | 'published';
type RunStatus = 'running' | 'completed' | 'failed' | 'other';

interface PreviewRun {
    id: string;
    createdAt: string;
    mode: PreviewScope;
    versionLabel: string;
    input: string;
    status: RunStatus;
    durationMs: number | null;
    result?: ApplicationPreviewResult;
    error?: string;
}

type ChatMessage =
    | {
        id: number;
        role: 'assistant';
        kind: 'welcome';
    }
    | {
        id: number;
        role: 'user';
        kind: 'text';
        text: string;
    }
    | {
        id: number;
        role: 'assistant';
        kind: 'text';
        text: string;
    }
    | {
        id: number;
        role: 'assistant';
        kind: 'category';
        category: ExperienceCategory;
    }
    | {
        id: number;
        role: 'assistant';
        kind: 'error';
    };

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
type ChatMessageDraft = DistributiveOmit<ChatMessage, 'id'>;

function categoryIcon(category: ExperienceCategory) {
    if (category.icon === 'member') return <SafetyCertificateOutlined/>;
    if (category.icon === 'order') return <AppstoreOutlined/>;
    if (category.icon === 'account') return <SettingOutlined/>;
    return <MessageOutlined/>;
}

function runStatusLabel(status: RunStatus) {
    if (status === 'running') return say('发送中');
    if (status === 'completed') return say('已完成');
    if (status === 'failed') return say('失败');
    return status;
}

function runStatusColor(status: RunStatus) {
    if (status === 'completed') return 'green';
    if (status === 'running') return 'processing';
    return 'red';
}

function entryKindColor(kind: ExperienceEntry['kind']) {
    if (kind === 'query') return 'blue';
    if (kind === 'action') return 'purple';
    if (kind === 'handoff') return 'orange';
    return 'green';
}

function resultStatus(status: string): RunStatus {
    if (status === 'completed') return 'completed';
    if (status === 'failed') return 'failed';
    return 'other';
}

export function CustomerInteractionWorkspace({
    application,
    draftExperience,
    readOnly,
    dirty,
    onEdit,
}: {
    application: ApplicationDetail;
    draftExperience: ServiceExperienceConfig;
    readOnly: boolean;
    dirty: boolean;
    onEdit: () => void;
}) {
    const { operator } = useAccess();
    const nextMessageId = useRef(0);
    const bottom = useRef<HTMLDivElement>(null);
    const [publishedExperience, setPublishedExperience] =
        useState<ServiceExperienceConfig | null>(null);
    const [experienceError, setExperienceError] = useState('');
    const [publishedLoading, setPublishedLoading] = useState(false);
    const [publishedRevision, setPublishedRevision] = useState(0);
    const [scope, setScope] = useState<PreviewScope>('draft');
    const [allowWrite, setAllowWrite] = useState(false);
    const [suggestionRound, setSuggestionRound] = useState(0);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [runs, setRuns] = useState<PreviewRun[]>([]);
    const [historyOpen, setHistoryOpen] = useState(false);
    const [diagnosticOpen, setDiagnosticOpen] = useState(false);
    const [selectedRun, setSelectedRun] = useState<PreviewRun | null>(null);

    useEffect(() => {
        if (scope !== 'published') {
            setExperienceError('');
            setPublishedLoading(false);
            return;
        }
        if (!application.published_version) return;
        let active = true;
        setExperienceError('');
        setPublishedExperience(null);
        setPublishedLoading(true);
        getApplicationExperience(application.key, application.published_version)
            .then(value => {
                if (active) setPublishedExperience(value.experience);
            })
            .catch(cause => {
                if (!active) return;
                setExperienceError(
                    cause instanceof Error ? cause.message : say('加载失败'),
                );
            })
            .finally(() => {
                if (active) setPublishedLoading(false);
            });
        return () => {
            active = false;
        };
    }, [application.key, application.published_version, publishedRevision, scope]);

    const experience = scope === 'published'
        ? publishedExperience || draftExperience
        : draftExperience;

    useEffect(() => {
        nextMessageId.current = 0;
        setSuggestionRound(0);
        setMessages([{
            id: ++nextMessageId.current,
            role: 'assistant',
            kind: 'welcome',
        }]);
        setInput('');
        setBusy(false);
    }, [application.key, experience.welcome_text, scope]);

    useEffect(() => {
        setRuns([]);
        setHistoryOpen(false);
        setDiagnosticOpen(false);
        setSelectedRun(null);
        setAllowWrite(false);
        setScope('draft');
    }, [application.key]);

    useEffect(() => {
        if (!application.published_version && scope === 'published') {
            setScope('draft');
        }
    }, [application.published_version, scope]);

    useEffect(() => {
        bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [busy, messages]);

    const suggestions = useMemo(() => {
        if (experience.suggestion_sets.length === 0) return [];
        return experience.suggestion_sets[suggestionRound % experience.suggestion_sets.length]
            .filter(Boolean);
    }, [experience.suggestion_sets, suggestionRound]);

    const lastRun = runs[0] || null;
    const versionLabel = scope === 'draft'
        ? `r${application.draft_revision}`
        : `v${application.published_version || 0}`;
    const draftIsStale = scope === 'draft' && dirty;
    const experienceReady = scope === 'draft' || Boolean(publishedExperience);
    const canSend = Boolean(operator) && !draftIsStale && experienceReady && !busy;

    function appendMessage(message: ChatMessageDraft) {
        setMessages(current => [
            ...current,
            { ...message, id: ++nextMessageId.current } as ChatMessage,
        ]);
    }

    function resetConversation() {
        nextMessageId.current = 0;
        setMessages([{
            id: ++nextMessageId.current,
            role: 'assistant',
            kind: 'welcome',
        }]);
        setInput('');
        setSuggestionRound(0);
        setBusy(false);
    }

    function openCategory(category: ExperienceCategory) {
        if (!canSend) return;
        appendMessage({ role: 'user', kind: 'text', text: category.label });
        appendMessage({ role: 'assistant', kind: 'category', category });
    }

    function updateRun(id: string, patch: Partial<PreviewRun>) {
        setRuns(current => current.map(run =>
            run.id === id ? { ...run, ...patch } : run,
        ));
    }

    async function send(value = input) {
        const message = value.trim();
        if (!message || !canSend) return;
        const createdAt = new Date().toISOString();
        const runId = `run-${Date.now().toString(36)}-${runs.length + 1}`;
        const selectedVersion = scope === 'draft' ? null : application.published_version;
        const run: PreviewRun = {
            id: runId,
            createdAt,
            mode: scope,
            versionLabel,
            input: message,
            status: 'running',
            durationMs: null,
        };

        setInput('');
        setBusy(true);
        appendMessage({ role: 'user', kind: 'text', text: message });
        setRuns(current => [run, ...current]);
        const startedAt = performance.now();

        try {
            const result = await previewApplication(application.key, {
                message,
                skill_key: null,
                version: selectedVersion,
                allow_write: scope === 'draft'
                    && allowWrite
                    && application.rules.preview_write_enabled,
            });
            const durationMs = Math.max(1, Math.round(performance.now() - startedAt));
            updateRun(runId, {
                status: resultStatus(result.status),
                durationMs,
                result,
            });
            appendMessage({
                role: 'assistant',
                kind: 'text',
                text: result.reply || say('暂无回复'),
            });
        } catch (cause) {
            updateRun(runId, {
                status: 'failed',
                durationMs: Math.max(1, Math.round(performance.now() - startedAt)),
                error: cause instanceof Error ? cause.message : String(cause),
            });
            appendMessage({ role: 'assistant', kind: 'error' });
        } finally {
            setBusy(false);
        }
    }

    function showDiagnostic(run: PreviewRun) {
        setSelectedRun(run);
        setDiagnosticOpen(true);
    }

    const runColumns: TableProps<PreviewRun>['columns'] = [
        {
            title: say('时间'),
            dataIndex: 'createdAt',
            width: 174,
            render: value => <span className="sa-cp-run-time">{dateTime(String(value))}</span>,
        },
        {
            title: say('模式'),
            dataIndex: 'mode',
            width: 94,
            render: value => <Tag color={value === 'draft' ? 'purple' : 'green'}>
                {value === 'draft' ? say('草稿预览') : say('已发布版本')}
            </Tag>,
        },
        {
            title: say('应用版本'),
            dataIndex: 'versionLabel',
            width: 94,
            render: value => <span className="mono">{String(value)}</span>,
        },
        {
            title: say('输入摘要'),
            dataIndex: 'input',
            ellipsis: true,
            render: value => <span title={String(value)}>{String(value)}</span>,
        },
        {
            title: say('状态'),
            dataIndex: 'status',
            width: 100,
            render: value => <Tag color={runStatusColor(value as RunStatus)}>
                {runStatusLabel(value as RunStatus)}
            </Tag>,
        },
        {
            title: say('耗时'),
            dataIndex: 'durationMs',
            width: 86,
            render: value => value == null ? '—' : `${value}ms`,
        },
        {
            title: say('技能'),
            dataIndex: 'result',
            width: 72,
            render: value => {
                const count = (value as ApplicationPreviewResult | undefined)?.skills.length || 0;
                return `${count}`;
            },
        },
        {
            title: say('诊断'),
            key: 'actions',
            width: 110,
            render: (_, run) => <Button
                type="link"
                size="small"
                icon={<BugOutlined/>}
                onClick={() => showDiagnostic(run)}
            >
                {say('查看诊断')}
            </Button>,
        },
    ];

    const timelineItems = selectedRun
        ? [
            {
                color: 'blue',
                children: <div className="sa-cp-timeline-item">
                    <strong>{say('收到客户消息')}</strong>
                    <p>{selectedRun.input}</p>
                    <small>{dateTime(selectedRun.createdAt)}</small>
                </div>,
            },
            ...(selectedRun.result?.skills || []).map(skill => ({
                color: skill.status === 'completed' ? 'green' : 'orange',
                children: <div className="sa-cp-timeline-item">
                    <strong>{skill.key}</strong>
                    <p>
                        {skill.status}
                        {skill.duration_ms == null ? '' : ` · ${skill.duration_ms}ms`}
                    </p>
                </div>,
            })),
            {
                color: selectedRun.status === 'failed' ? 'red' : 'green',
                children: <div className="sa-cp-timeline-item">
                    <strong>{selectedRun.status === 'failed'
                        ? say('失败')
                        : say('应用返回回复')}</strong>
                    <p>{selectedRun.result?.reply || selectedRun.error || say('暂无回复')}</p>
                </div>,
            },
        ]
        : [];

    return <div className="sa-cp-tab sa-cp-embedded">
        <section className="sa-cp-embedded-toolbar">
            <div className="sa-cp-embedded-heading">
                <span>{say('客户视角')}</span>
                <small>{say('配置、真实对话与运行诊断统一在这个画布中')}</small>
            </div>
            <div className="sa-cp-hero-controls">
                <Segmented
                    value={scope}
                    onChange={value => setScope(value as PreviewScope)}
                    options={[
                        { value: 'draft', label: `${say('草稿预览')} · r${application.draft_revision}` },
                        {
                            value: 'published',
                            label: application.published_version
                                ? `${say('发布版本')} · v${application.published_version}`
                                : say('暂无发布版本'),
                            disabled: !application.published_version,
                        },
                    ]}
                />
                <div className="sa-cp-write-control">
                    <SafetyCertificateOutlined/>
                    <div>
                        <span>{say('写操作保护')}</span>
                        <small>{application.rules.preview_write_enabled
                            ? say('当前应用允许在草稿预览中验证写操作。')
                            : say('当前应用默认禁用预览写操作。')}</small>
                    </div>
                    <Switch
                        size="small"
                        checked={scope === 'draft'
                            && allowWrite
                            && application.rules.preview_write_enabled}
                        disabled={scope !== 'draft'
                            || !application.rules.preview_write_enabled
                            || !operator}
                        onChange={setAllowWrite}
                    />
                </div>
                <Button
                    icon={<HistoryOutlined/>}
                    onClick={() => setHistoryOpen(true)}
                >
                    {say('运行记录')} · {runs.length}
                </Button>
                <Button
                    icon={<FormOutlined/>}
                    disabled={readOnly}
                    onClick={() => {
                        setScope('draft');
                        onEdit();
                    }}
                >
                    {say('编辑配置')}
                </Button>
            </div>
        </section>

        {experienceError && <Alert
            type="warning"
            showIcon
            message={experienceError}
            action={<Button
                size="small"
                onClick={() => setPublishedRevision(value => value + 1)}
            >
                {say('重试')}
            </Button>}
        />}

        {scope === 'published' && publishedLoading && <Alert
            type="info"
            showIcon
            message={say('正在加载发布版本配置')}
        />}

        {draftIsStale && <Alert
            type="warning"
            showIcon
            message={say('当前页面有未保存修改')}
            description={say('保存配置后才能测试新的欢迎语、目录和组件；当前运行仍使用已保存草稿。')}
        />}

        <div className="sa-cp-stage">
            <section className="sa-cp-canvas" aria-label={say('客户视角')}>
                <header className="sa-cp-canvas-header">
                    <div className="sa-cp-canvas-brand">
                        <div className="sa-cp-canvas-mark"><CustomerServiceOutlined/></div>
                        <div>
                            <strong>{application.name}</strong>
                            <span><i/> {say('在线客服')}</span>
                        </div>
                    </div>
                    <div className="sa-cp-canvas-meta">
                        <Tag bordered={false}>{scope === 'draft'
                            ? `${say('草稿预览')} · ${versionLabel}`
                            : `${say('已发布版本')} · ${versionLabel}`}</Tag>
                        <Button
                            type="text"
                            size="small"
                            icon={<ReloadOutlined/>}
                            aria-label={say('清空会话')}
                            onClick={resetConversation}
                        />
                    </div>
                </header>

                <div className="sa-cp-conversation">
                    {messages.map(message => {
                        if (message.kind === 'welcome') {
                            return <div className="sa-cp-welcome" key={message.id}>
                                <div className="sa-cp-avatar"><CustomerServiceOutlined/></div>
                                <div className="sa-cp-welcome-main">
                                    <div className="sa-cp-bubble">
                                        {experience.welcome_text || say('您好，请问有什么可以帮您？')}
                                    </div>
                                    {experience.components.suggestions && suggestions.length > 0 && <div className="sa-cp-suggestion-panel">
                                        <div className="sa-cp-suggestion-head">
                                            <span>{say('猜你想问')}</span>
                                            {experience.suggestion_sets.length > 1 && <Button
                                                type="link"
                                                size="small"
                                                onClick={() => setSuggestionRound(
                                                    value => (value + 1) % experience.suggestion_sets.length,
                                                )}
                                            >
                                                {say('换一批')}
                                            </Button>}
                                        </div>
                                        <div className="sa-cp-suggestion-list">
                                            {suggestions.map(suggestion => <button
                                                type="button"
                                                key={suggestion}
                                                onClick={() => void send(suggestion)}
                                                disabled={!canSend}
                                            >
                                                {suggestion}
                                                <RightOutlined/>
                                            </button>)}
                                        </div>
                                    </div>}
                                    {experience.components.quick_menu && experience.categories.length > 0 && <div className="sa-cp-category-strip">
                                        {experience.categories.map(category => <button
                                            type="button"
                                            key={category.key}
                                            className={`sa-cp-category-chip ${category.tone}`}
                                            onClick={() => openCategory(category)}
                                            disabled={!canSend}
                                        >
                                            <span className={`sa-cp-category-icon ${category.tone}`}>
                                                {categoryIcon(category)}
                                            </span>
                                            <span>{category.label}</span>
                                        </button>)}
                                    </div>}
                                </div>
                            </div>;
                        }
                        if (message.kind === 'category') {
                            return <div className="sa-cp-message assistant" key={message.id}>
                                <div className="sa-cp-avatar"><CustomerServiceOutlined/></div>
                                <div className="sa-cp-category-card">
                                    <div className="sa-cp-category-card-head">
                                        <span className={`sa-cp-category-icon ${message.category.tone}`}>
                                            {categoryIcon(message.category)}
                                        </span>
                                        <strong>{message.category.label}</strong>
                                    </div>
                                    <div className="sa-cp-category-entries">
                                        {message.category.entries.map(entry => <button
                                            type="button"
                                            key={entry.key}
                                            disabled={!canSend}
                                            onClick={() => void send(entry.label)}
                                        >
                                            <div>
                                                <strong>{entry.label}</strong>
                                                {entry.description && <span>{entry.description}</span>}
                                            </div>
                                            <Tag color={entryKindColor(entry.kind)}>
                                                {skillTypeLabel(entry.kind)}
                                            </Tag>
                                        </button>)}
                                    </div>
                                </div>
                            </div>;
                        }
                        if (message.role === 'user') {
                            return <div className="sa-cp-message user" key={message.id}>
                                <div className="sa-cp-bubble">{message.text}</div>
                                <div className="sa-cp-avatar user"><UserOutlined/></div>
                            </div>;
                        }
                        if (message.kind === 'error') {
                            return <div className="sa-cp-message assistant" key={message.id}>
                                <div className="sa-cp-avatar warning"><WarningFilled/></div>
                                <div className="sa-cp-bubble error">{say('运行失败，请稍后重试。')}</div>
                            </div>;
                        }
                        return <div className="sa-cp-message assistant" key={message.id}>
                            <div className="sa-cp-avatar"><CustomerServiceOutlined/></div>
                            <div className="sa-cp-bubble">{message.text}</div>
                        </div>;
                    })}
                    {busy && <div className="sa-cp-message assistant">
                        <div className="sa-cp-avatar"><CustomerServiceOutlined/></div>
                        <div className="sa-cp-bubble thinking">
                            <LoadingOutlined/>
                            <span>{say('正在思考')}</span>
                        </div>
                    </div>}
                    <div ref={bottom}/>
                </div>

                <footer className="sa-cp-composer">
                    <Input.TextArea
                        aria-label={say('客户消息')}
                        autoSize={{ minRows: 1, maxRows: 4 }}
                        maxLength={2000}
                        value={input}
                        placeholder={say('请输入客户消息')}
                        disabled={!canSend}
                        onChange={event => setInput(event.target.value)}
                        onPressEnter={event => {
                            if (event.shiftKey) return;
                            event.preventDefault();
                            void send();
                        }}
                    />
                    <Button
                        type="primary"
                        shape="circle"
                        aria-label={say('发送')}
                        icon={<SendOutlined/>}
                        loading={busy}
                        disabled={!input.trim() || !canSend}
                        onClick={() => void send()}
                    />
                    <div className="sa-cp-composer-caption">
                        <span>{say('客户视角')}</span>
                        <span>{say('诊断信息仅对运营人员展示')}</span>
                    </div>
                </footer>
            </section>

            <section className="sa-cp-run-card">
                <div className="sa-cp-run-card-head">
                    <div>
                        <span className="sa-cp-run-eyebrow">{say('最近运行')}</span>
                        <h4>{say('本次运行')}</h4>
                    </div>
                    {lastRun && <Tag color={runStatusColor(lastRun.status)}>
                        {runStatusLabel(lastRun.status)}
                    </Tag>}
                </div>
                {!lastRun
                    ? <div className="sa-cp-run-empty">
                        <BugOutlined/>
                        <span>{say('发送一条消息后，这里会显示本次运行摘要。')}</span>
                    </div>
                    : <>
                        <div className="sa-cp-run-metrics">
                            <div>
                                <span>{say('模式')}</span>
                                <strong>{lastRun.mode === 'draft'
                                    ? say('草稿预览')
                                    : say('已发布版本')}</strong>
                            </div>
                            <div>
                                <span>{say('应用版本')}</span>
                                <strong className="mono">{lastRun.versionLabel}</strong>
                            </div>
                            <div>
                                <span>{say('耗时')}</span>
                                <strong>{lastRun.durationMs == null ? '—' : `${lastRun.durationMs}ms`}</strong>
                            </div>
                            <div>
                                <span>{say('技能')}</span>
                                <strong>{lastRun.result?.skills.length || 0}</strong>
                            </div>
                        </div>
                        <div className="sa-cp-run-input">
                            <span>{say('输入摘要')}</span>
                            <p>{lastRun.input}</p>
                        </div>
                        <div className="sa-cp-run-actions">
                            <div>
                                {lastRun.status === 'completed'
                                    ? <CheckCircleFilled className="success"/>
                                    : <WarningFilled className="warning"/>}
                                <span>{say('诊断信息仅对运营人员展示')}</span>
                            </div>
                            <Button
                                icon={<BugOutlined/>}
                                onClick={() => showDiagnostic(lastRun)}
                            >
                                {say('查看诊断')}
                            </Button>
                        </div>
                    </>}
            </section>
        </div>

        <Drawer
            open={historyOpen}
            onClose={() => setHistoryOpen(false)}
            title={say('运行记录')}
            width={1040}
            extra={<Tag>{say('共 {{v0}} 条', { v0: runs.length })}</Tag>}
            destroyOnHidden
        >
            <Table<PreviewRun>
                rowKey="id"
                size="small"
                columns={runColumns}
                dataSource={runs}
                pagination={{
                    pageSize: 10,
                    showSizeChanger: false,
                    hideOnSinglePage: runs.length <= 10,
                    showTotal: total => say('共 {{v0}} 条', { v0: total }),
                }}
                locale={{ emptyText: say('暂无运行记录') }}
            />
        </Drawer>

        <Drawer
            open={diagnosticOpen}
            onClose={() => setDiagnosticOpen(false)}
            title={say('诊断详情')}
            width={720}
            destroyOnHidden
        >
            {selectedRun
                ? <div className="sa-cp-diagnostic">
                    <div className="sa-cp-diagnostic-head">
                        <div>
                            <span>{say('运行诊断')}</span>
                            <strong className="mono">#{selectedRun.id}</strong>
                        </div>
                        <Tag color={runStatusColor(selectedRun.status)}>
                            {runStatusLabel(selectedRun.status)}
                        </Tag>
                    </div>
                    {selectedRun.error && <Alert
                        type="error"
                        showIcon
                        message={selectedRun.error}
                    />}
                    <section className="sa-cp-diagnostic-section">
                        <h4>{say('对话记录')}</h4>
                        <div className="sa-cp-diagnostic-dialogue">
                            <div>
                                <span>{say('客户消息')}</span>
                                <p>{selectedRun.input}</p>
                            </div>
                            <div>
                                <span>{say('应用回复')}</span>
                                <p>{selectedRun.result?.reply || selectedRun.error || say('暂无回复')}</p>
                            </div>
                        </div>
                    </section>
                    <section className="sa-cp-diagnostic-section">
                        <h4>{say('运行时间线')}</h4>
                        <Timeline items={timelineItems}/>
                    </section>
                    <section className="sa-cp-diagnostic-section">
                        <div className="sa-cp-diagnostic-section-title">
                            <h4>{say('技能与 Trace')}</h4>
                            {selectedRun.result?.skills.length
                                ? <Tag>{selectedRun.result.skills.length}</Tag>
                                : <span>{say('暂无技能调用')}</span>}
                        </div>
                        <div className="sa-cp-skill-chips">
                            {(selectedRun.result?.skills || []).map(skill => <Tag
                                key={skill.key}
                                color={skill.status === 'completed' ? 'green' : 'orange'}
                            >
                                {skill.key} · {skill.status}
                            </Tag>)}
                        </div>
                    </section>
                    <section className="sa-cp-diagnostic-section">
                        <h4>{say('原始 JSON')}</h4>
                        <pre className="sa-cp-raw">{JSON.stringify({
                            skills: selectedRun.result?.skills || [],
                            trace: selectedRun.result?.trace || {},
                        }, null, 2)}</pre>
                    </section>
                </div>
                : <Empty/>}
        </Drawer>
    </div>;
}
