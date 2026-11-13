import { useEffect, useMemo, useState } from 'react';
import {
    AppstoreOutlined,
    ArrowRightOutlined,
    ClockCircleOutlined,
    DeleteOutlined,
    EyeOutlined,
    InboxOutlined,
    MoreOutlined,
    PlusOutlined,
    ReloadOutlined,
    RobotOutlined,
    SearchOutlined,
    UndoOutlined,
} from '@ant-design/icons';
import {
    Alert as AntdAlert,
    Button,
    Dropdown,
    Empty,
    Form,
    Input,
    Modal,
    Pagination,
    Popconfirm,
    Select,
    Spin,
    Table,
    Tooltip,
    type MenuProps,
} from 'antd';
import { dateTime } from '../../../i18n/index';
import type { Agent } from '../../../shared/api/client';
import { Alert, toast, useAccess, useResource } from '../../../shared/components/ui';
import {
    archiveApplication,
    createApplication,
    getApplicationOverview,
    listApplications,
    purgeApplication,
    restoreApplication,
} from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationOverview,
    type ApplicationPage,
    type ApplicationStatus,
    type ApplicationSummary,
} from '../contracts';
import { say } from '../labels';

interface Props {
    onNavigate: (path: string) => void;
}

interface CreateValues {
    key: string;
    name: string;
    description?: string;
    agent_id: string;
    agent_version: number;
}

type StatusFilter = ApplicationStatus | 'all';

const statusOptions: Array<{ value: StatusFilter; label: string }> = [
    { value: 'all', label: '全部应用' },
    { value: 'draft', label: '配置中' },
    { value: 'review', label: '待发布' },
    { value: 'published', label: '生产运行中' },
    { value: 'offline', label: '已下线' },
];

const archivedPageSize = DEFAULT_PAGE_SIZE;

function statusLabel(status: ApplicationStatus) {
    if (status === 'draft') return say('配置中');
    if (status === 'review') return say('待发布');
    if (status === 'published') return say('生产运行中');
    return say('已下线');
}

function ApplicationCard({
    application,
    admin,
    onOpen,
    onOpenExperience,
    onArchive,
}: {
    application: ApplicationSummary;
    admin: boolean;
    onOpen: () => void;
    onOpenExperience: () => void;
    onArchive: () => void;
}) {
    const menuItems: MenuProps['items'] = [
        { key: 'open', label: say('打开应用'), icon: <ArrowRightOutlined/> },
        { key: 'experience', label: say('打开客户交互'), icon: <EyeOutlined/> },
        { type: 'divider' },
        {
            key: 'archive',
            label: say('归档应用'),
            icon: <DeleteOutlined/>,
            danger: true,
        },
    ];

    return <div className={`sa-app-cell ${application.status}`}>
        <button type="button" className="sa-app-card" onClick={onOpen}>
            <div className="sa-app-card-top">
                <span className="sa-app-icon"><RobotOutlined/></span>
                <span className={`sa-app-state ${application.status}`}>
                    <i/>{statusLabel(application.status)}
                </span>
            </div>
            <div className="sa-app-title-line">
                <h3>{application.name}</h3>
                {application.has_unpublished_changes && <Tooltip title={say('有未发布修改')}>
                    <span className="sa-app-draft-dot" aria-label={say('有未发布修改')}/>
                </Tooltip>}
            </div>
            <p>{application.description || say('尚未填写应用描述')}</p>
            <div className="sa-app-numbers">
                <span><strong>{application.skill_count}</strong><small>{say('技能')}</small></span>
                <span><strong>{application.connection_count}</strong><small>{say('连接')}</small></span>
                <span>
                    <strong>{application.published_version ? `v${application.published_version}` : '—'}</strong>
                    <small>{say('当前版本')}</small>
                </span>
            </div>
            <div className="sa-app-card-foot">
                <span>
                    <ClockCircleOutlined/>
                    {say('最近更新')} {application.updated_at ? dateTime(application.updated_at) : '—'}
                </span>
                <b>{say('打开应用')} <ArrowRightOutlined/></b>
            </div>
        </button>
        {admin && <div className="sa-app-more">
            <Dropdown
                trigger={['click']}
                placement="bottomRight"
                menu={{
                    items: menuItems,
                    onClick: ({ key }) => {
                        if (key === 'archive') onArchive();
                        else if (key === 'experience') onOpenExperience();
                        else onOpen();
                    },
                }}
            >
                <Button
                    type="text"
                    size="small"
                    aria-label={`${application.name} ${say('更多操作')}`}
                    icon={<MoreOutlined aria-hidden/>}
                />
            </Dropdown>
        </div>}
    </div>;
}

export function ApplicationCatalog({ onNavigate }: Props) {
    const { admin } = useAccess();
    const agents = useResource<Agent[]>('/agents');
    const [filter, setFilter] = useState<StatusFilter>('all');
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [version, setVersion] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [overview, setOverview] = useState<ApplicationOverview | null>(null);
    const [data, setData] = useState<ApplicationPage>({
        items: [],
        total: 0,
        page: 1,
        page_size: DEFAULT_PAGE_SIZE,
    });
    const [createOpen, setCreateOpen] = useState(false);
    const [selectedAgent, setSelectedAgent] = useState('');
    const [busy, setBusy] = useState(false);
    const [archiveTarget, setArchiveTarget] = useState<ApplicationSummary | null>(null);
    const [archiveBusy, setArchiveBusy] = useState(false);
    const [archiveListOpen, setArchiveListOpen] = useState(false);
    const [archivedPage, setArchivedPage] = useState(1);
    const [archivedLoading, setArchivedLoading] = useState(false);
    const [archivedError, setArchivedError] = useState('');
    const [archivedData, setArchivedData] = useState<ApplicationPage>({
        items: [],
        total: 0,
        page: 1,
        page_size: archivedPageSize,
    });
    const [createForm] = Form.useForm<CreateValues>();

    const publishedAgents = useMemo(
        () => (agents.data || []).filter(agent => agent.published_version && !agent.archived),
        [agents.data],
    );
    const selectedAgentRecord = publishedAgents.find(agent => agent.id === selectedAgent);
    const archiveBlocked = Boolean(
        archiveTarget?.published_version !== null
        && archiveTarget?.published_version !== undefined
        && archiveTarget.status !== 'offline',
    );

    useEffect(() => {
        setPage(1);
    }, [filter, pageSize]);

    useEffect(() => {
        const controller = new AbortController();
        const timer = window.setTimeout(async () => {
            setLoading(true);
            setError('');
            try {
                const [result, stats] = await Promise.all([
                    listApplications({
                        page,
                        pageSize,
                        origin: 'user',
                        status: filter === 'all' ? undefined : filter,
                        query: query.trim(),
                        archived: false,
                    }),
                    getApplicationOverview('user'),
                ]);
                if (!controller.signal.aborted) {
                    setData(result);
                    setOverview(stats);
                }
            } catch (cause) {
                if (!controller.signal.aborted) {
                    setError(cause instanceof Error ? cause.message : say('加载失败'));
                }
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        }, query ? 250 : 0);
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [filter, page, pageSize, query, version]);

    useEffect(() => {
        if (!archiveListOpen) return;
        const controller = new AbortController();
        setArchivedLoading(true);
        setArchivedError('');
        listApplications({
            page: archivedPage,
            pageSize: archivedPageSize,
            origin: 'user',
            archived: true,
        })
            .then(result => {
                if (!controller.signal.aborted) setArchivedData(result);
            })
            .catch(cause => {
                if (!controller.signal.aborted) {
                    setArchivedError(cause instanceof Error ? cause.message : say('加载失败'));
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) setArchivedLoading(false);
            });
        return () => controller.abort();
    }, [archiveListOpen, archivedPage, version]);

    function refresh() {
        setVersion(current => current + 1);
    }

    function openCreate() {
        setSelectedAgent('');
        createForm.resetFields();
        createForm.setFieldsValue({ description: '' });
        setCreateOpen(true);
    }

    async function submitCreate() {
        const values = await createForm.validateFields();
        setBusy(true);
        try {
            const created = await createApplication({
                key: values.key.trim(),
                name: values.name.trim(),
                description: (values.description || '').trim(),
                agent_id: values.agent_id,
                agent_version: values.agent_version,
            });
            setCreateOpen(false);
            toast.success(say('创建应用'));
            onNavigate(`/service-apps/${created.key}`);
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    async function confirmArchive() {
        if (!archiveTarget || archiveBlocked) return;
        setArchiveBusy(true);
        try {
            await archiveApplication(archiveTarget.key, archiveTarget.revision);
            setArchiveTarget(null);
            toast.success(say('应用已归档，可在“已归档”中恢复'));
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('归档失败'));
        } finally {
            setArchiveBusy(false);
        }
    }

    async function restoreArchived(application: ApplicationSummary) {
        try {
            await restoreApplication(application.key);
            setArchivedPage(1);
            toast.success(say('应用已恢复'));
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('恢复失败'));
        }
    }

    async function purgeArchived(application: ApplicationSummary) {
        try {
            await purgeApplication(application.key);
            setArchivedPage(1);
            toast.success(say('应用已彻底删除'));
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('删除失败'));
        }
    }

    const total = overview?.applications ?? data.total;
    const published = overview?.by_status.published ?? 0;
    const waiting = (overview?.by_status.draft ?? 0) + (overview?.by_status.review ?? 0);

    return <div className="sa-catalog">
        <header className="sa-catalog-hero">
            <div>
                <span className="sa-eyebrow">{say('服务应用')}</span>
                <h2>{say('我的应用')}</h2>
                <p>{say('把业务能力组合成可配置、可预览、可发布的服务应用。')}</p>
            </div>
            <div className="sa-hero-actions">
                <Button
                    icon={<AppstoreOutlined/>}
                    onClick={() => onNavigate('/service-apps/standards')}
                >
                    {say('标准案例')}
                </Button>
                <Button
                    type="primary"
                    icon={<PlusOutlined/>}
                    disabled={!admin}
                    onClick={openCreate}
                >
                    {say('新建服务应用')}
                </Button>
            </div>
        </header>

        <section className="sa-catalog-section-head">
            <div>
                <span className="sa-eyebrow">APPLICATIONS</span>
                <h3>{say('我的应用')}</h3>
                <p>
                    {say('共 {{v0}} 个应用', { v0: total })}
                    <span>·</span>
                    {say('{{v0}} 个生产运行中 · {{v1}} 个待完善', {
                        v0: published,
                        v1: waiting,
                    })}
                </p>
            </div>
            <div className="sa-catalog-toolbar">
                <Input
                    allowClear
                    aria-label={say('搜索应用名称、标识或描述')}
                    prefix={<SearchOutlined/>}
                    placeholder={say('搜索应用名称、标识或描述')}
                    value={query}
                    onChange={event => {
                        setQuery(event.target.value);
                        setPage(1);
                    }}
                />
                <Select
                    aria-label={say('应用状态')}
                    value={filter}
                    options={statusOptions.map(item => ({
                        value: item.value,
                        label: say(item.label),
                    }))}
                    onChange={value => setFilter(value)}
                />
                <Button
                    className="sa-archived-entry"
                    icon={<InboxOutlined/>}
                    onClick={() => {
                        setArchivedPage(1);
                        setArchiveListOpen(true);
                    }}
                >
                    {say('已归档')}
                </Button>
                <Button
                    type="text"
                    aria-label={say('刷新')}
                    icon={<ReloadOutlined/>}
                    onClick={refresh}
                />
            </div>
        </section>

        <Alert error={error || (agents.error ? agents.error : '')}/>

        {loading
            ? <div className="sa-loading"><Spin/></div>
            : data.items.length === 0
                ? <Empty description={query || filter !== 'all'
                    ? say('没有匹配的服务应用')
                    : say('还没有服务应用，创建第一个应用开始配置。')}/>
                : <div className="sa-app-grid">
                    {data.items.map(application => <ApplicationCard
                        key={application.id || application.key}
                        application={application}
                        admin={admin}
                        onOpen={() => onNavigate(`/service-apps/${application.key}`)}
                        onOpenExperience={() => onNavigate(
                            `/service-apps/${application.key}/experience`,
                        )}
                        onArchive={() => setArchiveTarget(application)}
                    />)}
                </div>}

        <div className="sa-pagination-bar">
            <Pagination
                current={page}
                pageSize={pageSize}
                total={data.total}
                showSizeChanger
                pageSizeOptions={[10, 20, 50]}
                hideOnSinglePage={false}
                showTotal={(itemTotal, range) =>
                    `${range[0]}-${range[1]} / ${itemTotal} ${say('服务应用')}`
                }
                onChange={(nextPage, nextSize) => {
                    setPage(nextPage);
                    setPageSize(nextSize);
                }}
            />
        </div>

        <Modal
            open={createOpen}
            title={say('创建应用')}
            okText={say('确认创建')}
            cancelText={say('取消')}
            confirmLoading={busy}
            destroyOnHidden
            onOk={() => void submitCreate()}
            onCancel={() => setCreateOpen(false)}
        >
            <Form<CreateValues>
                form={createForm}
                layout="vertical"
                requiredMark={false}
            >
                <Form.Item
                    name="name"
                    label={say('应用名称')}
                    rules={[{ required: true, message: say('请输入名称') }]}
                >
                    <Input maxLength={100} placeholder={say('例如：订单服务')}/>
                </Form.Item>
                <Form.Item
                    name="key"
                    label={say('应用标识')}
                    rules={[
                        { required: true, message: say('请输入应用标识') },
                        {
                            pattern: /^[a-z][a-z0-9-]{1,63}$/,
                            message: say('应用标识只能使用小写字母、数字和短横线'),
                        },
                    ]}
                >
                    <Input className="mono" maxLength={64} placeholder="order-service"/>
                </Form.Item>
                <Form.Item name="description" label={say('描述')}>
                    <Input.TextArea rows={3} maxLength={500} showCount/>
                </Form.Item>
                <Form.Item
                    name="agent_id"
                    label={say('智能体')}
                    rules={[{ required: true, message: say('请选择智能体') }]}
                >
                    <Select
                        showSearch
                        optionFilterProp="label"
                        placeholder={say('请选择已发布的智能体')}
                        options={publishedAgents.map(agent => ({
                            value: agent.id,
                            label: `${agent.name} · v${agent.published_version}`,
                        }))}
                        onChange={value => {
                            setSelectedAgent(value);
                            const agent = publishedAgents.find(item => item.id === value);
                            createForm.setFieldValue(
                                'agent_version',
                                agent?.published_version || undefined,
                            );
                        }}
                    />
                </Form.Item>
                <Form.Item
                    name="agent_version"
                    label={say('绑定版本')}
                    rules={[{ required: true, message: say('请选择绑定版本') }]}
                >
                    <Select
                        disabled={!selectedAgentRecord}
                        options={selectedAgentRecord?.published_version
                            ? [{
                                value: selectedAgentRecord.published_version,
                                label: `v${selectedAgentRecord.published_version}`,
                            }]
                            : []}
                    />
                </Form.Item>
            </Form>
        </Modal>

        <Modal
            open={Boolean(archiveTarget)}
            title={say('归档应用')}
            destroyOnHidden
            onCancel={() => setArchiveTarget(null)}
            footer={[
                <Button key="cancel" onClick={() => setArchiveTarget(null)}>
                    {say('取消')}
                </Button>,
                archiveBlocked
                    ? <Button
                        key="offline"
                        type="primary"
                        onClick={() => {
                            if (archiveTarget) {
                                onNavigate(`/service-apps/${archiveTarget.key}/release`);
                                setArchiveTarget(null);
                            }
                        }}
                    >
                        {say('前往下线处理')}
                    </Button>
                    : <Button
                        key="confirm"
                        danger
                        type="primary"
                        loading={archiveBusy}
                        onClick={() => void confirmArchive()}
                    >
                        {say('确认归档')}
                    </Button>,
            ]}
        >
            <AntdAlert
                type="warning"
                showIcon
                message={archiveBlocked ? say('需要先下线生产版本') : say('归档后仍可恢复')}
                description={archiveBlocked
                    ? say('该应用已有生产版本，请先在客户渠道与发布中下线，再归档。')
                    : say('归档会从我的应用列表隐藏，但保留发布版本、连接和审计记录。')}
            />
            {archiveTarget && <div className="sa-archive-target">
                <strong>{archiveTarget.name}</strong>
                <span className="mono">{archiveTarget.key}</span>
            </div>}
        </Modal>

        <Modal
            open={archiveListOpen}
            title={say('已归档应用')}
            width={760}
            footer={null}
            destroyOnHidden
            onCancel={() => setArchiveListOpen(false)}
        >
            <Alert error={archivedError}/>
            <Table<ApplicationSummary>
                className="sa-ant-table sa-archived-table"
                rowKey={application => application.id || application.key}
                dataSource={archivedData.items}
                loading={archivedLoading}
                locale={{
                    emptyText: <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={say('暂无已归档应用')}
                    />,
                }}
                pagination={{
                    current: archivedPage,
                    pageSize: archivedPageSize,
                    total: archivedData.total,
                    position: ['bottomRight'],
                    hideOnSinglePage: true,
                    showTotal: (itemTotal, range) =>
                        `${range[0]}-${range[1]} / ${itemTotal} ${say('服务应用')}`,
                    onChange: setArchivedPage,
                }}
                columns={[
                    {
                        key: 'application',
                        title: say('应用信息'),
                        render: (_, application) => <div className="sa-archived-app">
                                <strong>{application.name}</strong>
                                <p>{application.description || say('尚未填写应用描述')}</p>
                                <span className="mono">{application.key}</span>
                            </div>,
                    },
                    {
                        key: 'updated_at',
                        title: say('更新时间'),
                        width: 155,
                        render: (_, application) => <span className="sa-archived-updated">
                            {application.updated_at ? dateTime(application.updated_at) : '—'}
                        </span>,
                    },
                    {
                        key: 'actions',
                        title: say('操作'),
                        width: 190,
                        align: 'right',
                        render: (_, application) => <div className="sa-archived-actions">
                            <Button
                                type="primary"
                                ghost
                                size="small"
                                icon={<UndoOutlined/>}
                                disabled={!admin}
                                onClick={() => void restoreArchived(application)}
                            >
                                {say('恢复')}
                            </Button>
                            <Popconfirm
                                title={say('彻底删除应用？')}
                                description={say('彻底删除后无法恢复，相关配置和审计关联也会被清理。')}
                                okText={say('彻底删除')}
                                cancelText={say('取消')}
                                okButtonProps={{ danger: true }}
                                disabled={!admin}
                                onConfirm={() => void purgeArchived(application)}
                            >
                                <Button
                                    type="text"
                                    danger
                                    size="small"
                                    icon={<DeleteOutlined/>}
                                    disabled={!admin}
                                >
                                    {say('彻底删除')}
                                </Button>
                            </Popconfirm>
                        </div>,
                    },
                ]}
            />
        </Modal>
    </div>;
}
