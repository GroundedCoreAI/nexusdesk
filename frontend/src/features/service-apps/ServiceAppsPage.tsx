import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, Form, Input, InputNumber, Modal, Popconfirm, Select, Spin, Switch } from 'antd';
import {
    ApartmentOutlined,
    ApiOutlined,
    AppstoreOutlined,
    ArrowRightOutlined,
    BookOutlined,
    BranchesOutlined,
    BugOutlined,
    CheckCircleFilled,
    ClockCircleOutlined,
    CodeOutlined,
    CustomerServiceOutlined,
    DatabaseOutlined,
    DeleteOutlined,
    DeploymentUnitOutlined,
    EditOutlined,
    EyeOutlined,
    FileSearchOutlined,
    FileTextOutlined,
    GlobalOutlined,
    HistoryOutlined,
    InboxOutlined,
    InfoCircleOutlined,
    LinkOutlined,
    MessageOutlined,
    PlayCircleOutlined,
    PlusOutlined,
    ReloadOutlined,
    RobotOutlined,
    SafetyCertificateOutlined,
    SendOutlined,
    SettingOutlined,
    ShoppingOutlined,
    ThunderboltOutlined,
    ToolOutlined,
} from '@ant-design/icons';
import type {
    Agent,
    ApplicationCapability,
    ApplicationCapabilityType,
    ApplicationChannel,
    ApplicationChannelStatus,
    ScenarioConfig,
    ScenarioHandler,
    ScenarioTemplate,
    ServiceApplicationConfig,
    ServiceApplicationOverview,
    ServiceApplicationPage,
    ServiceApplicationStatus,
    ServiceApplicationSummary,
    ServiceApplicationVersion,
    ServiceApplicationVersionPage,
    ServiceScenarioPage,
    ServiceScenarioSummary,
    ServiceTracePage,
    SimulationDecision,
    SimulationFact,
    SimulationStep,
    SimulationTrace,
} from '../../shared/api/client';
import {
    createServiceApplication,
    createServiceScenario,
    publishServiceApplication,
    rollbackServiceApplication,
    setServiceApplicationStatus,
    simulateServiceApplication,
    updateServiceApplication,
} from '../../shared/api/client';
import { Alert, toast, useAccess, useResource } from '../../shared/components/ui';
import { CustomerExperiencePreview } from '../service-scenarios/CustomerExperiencePreview';
import { SceneSimulator } from '../service-scenarios/SceneSimulator';
import { SceneWorkbench } from '../service-scenarios/SceneWorkbench';
import { UnifiedExperience } from '../service-scenarios/UnifiedExperience';
import { appBasePath } from '../service-scenarios/routes';
import {
    effectiveServiceCategories,
    formatTraceValue,
    groupScenariosByCategory,
    handlerTypeLabel,
    newScenarioConfig,
    objectModeLabel,
    scenarioStatusLabel,
    defaultExecutionStages,
    withApplicationScenario,
} from '../service-scenarios/scenarioConfig';
import { ServiceCatalogManager } from './ServiceCatalogManager';
import './service-apps.css';

interface Props {
    route: string;
    onNavigate: (path: string) => void;
    onMetaChange?: (meta: { path: string; title: string; description?: string }) => void;
}

type StudioSection = 'overview' | 'orchestration' | 'capabilities' | 'preview' | 'deploy';
type MetaChange = (meta: { path: string; title: string; description?: string }) => void;

interface AppScenario {
    key: string;
    name: string;
    description: string;
    category: string;
    status: ServiceScenarioSummary['status'];
    version: number | null;
    enabled: boolean;
    config: ScenarioConfig;
    source: ServiceScenarioSummary;
}

const studioTabs: { key: StudioSection; label: string }[] = [
    { key: 'overview', label: '应用概览' },
    { key: 'orchestration', label: '业务编排' },
    { key: 'capabilities', label: '执行能力' },
    { key: 'preview', label: '预览与调试' },
    { key: 'deploy', label: '接入与发布' },
];

const applicationStatusLabel: Record<ServiceApplicationStatus, string> = {
    draft: '配置中',
    review: '待发布',
    published: '生产运行中',
    offline: '已下线',
};

const capabilityTypeLabel: Record<ApplicationCapabilityType, string> = {
    direct: 'Direct',
    knowledge: '知识检索',
    query: '业务查询',
    action: '业务办理',
    agent: 'Agent',
    human: '人工',
    tracking: '进度跟踪',
};

const applicationTones = ['violet', 'blue', 'green'] as const;

function updatedLabel(value?: string) {
    if (!value) return '刚刚';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '刚刚';
    return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function appKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/([a-z0-9-]+)/)?.[1] || '';
}

function scenarioKeyFromSceneRoute(route: string) {
    return route.match(/\/scenarios\/([a-z][a-z0-9_-]{0,63})(?:\/|$)/)?.[1] || '';
}

function scenarioVisual(scene: Pick<AppScenario, 'key' | 'name' | 'config'>) {
    const key = `${scene.key} ${scene.name}`.toLocaleLowerCase();
    if (key.includes('logistic') || key.includes('物流')) return <ThunderboltOutlined/>;
    if (key.includes('rule') || key.includes('规则')) return <BookOutlined/>;
    if (key.includes('invoice') || key.includes('发票')) return <FileTextOutlined/>;
    if (key.includes('complaint') || key.includes('投诉')) return <InboxOutlined/>;
    if (scene.config.template === 'action') return <ShoppingOutlined/>;
    return <FileSearchOutlined/>;
}

function capabilityIcon(type: ApplicationCapabilityType) {
    if (type === 'agent') return <RobotOutlined/>;
    if (type === 'human') return <CustomerServiceOutlined/>;
    if (type === 'knowledge') return <BookOutlined/>;
    if (type === 'query' || type === 'tracking') return <DatabaseOutlined/>;
    if (type === 'action') return <ToolOutlined/>;
    return <ThunderboltOutlined/>;
}

function capabilityTone(type: ApplicationCapabilityType) {
    if (type === 'agent') return 'violet';
    if (type === 'human') return 'rose';
    if (type === 'knowledge') return 'blue';
    if (type === 'query' || type === 'tracking') return 'green';
    if (type === 'action') return 'amber';
    return 'slate';
}

export function ServiceAppsPage({ route, onNavigate, onMetaChange }: Props) {
    if (route === '/service-apps') return <AppCatalog onNavigate={onNavigate}/>;
    if (/^\/service-apps\/[a-z0-9-]+\/experience(?:\/[a-z][a-z0-9_-]{0,63})?$/.test(route))
        return <UnifiedExperience route={route} onNavigate={onNavigate} onMetaChange={onMetaChange}/>;
    if (/^\/service-apps\/[a-z0-9-]+\/scenarios\/[a-z][a-z0-9_-]{0,63}\/simulator$/.test(route))
        return <SceneSimulator route={route} onNavigate={onNavigate} onMetaChange={onMetaChange}/>;
    if (/^\/service-apps\/[a-z0-9-]+\/scenarios\/[a-z][a-z0-9_-]{0,63}\/customer$/.test(route))
        return <CustomerExperiencePreview route={route} onNavigate={onNavigate} onMetaChange={onMetaChange}/>;
    if (/^\/service-apps\/[a-z0-9-]+\/scenarios\/[a-z][a-z0-9_-]{0,63}$/.test(route))
        return <ServiceAppStudio route={route} onNavigate={onNavigate} onMetaChange={onMetaChange}/>;
    return <ServiceAppStudio route={route} onNavigate={onNavigate} onMetaChange={onMetaChange}/>;
}

interface CreateApplicationValues {
    key: string;
    name: string;
    description?: string;
}

function AppCatalog({ onNavigate }: { onNavigate: (path: string) => void }) {
    const { admin } = useAccess();
    const applications = useResource<ServiceApplicationPage>('/service-apps');
    const overview = useResource<ServiceApplicationOverview>('/service-apps/overview');
    const [form] = Form.useForm<CreateApplicationValues>();
    const [query, setQuery] = useState('');
    const [statusFilter, setStatusFilter] = useState<'all' | 'draft' | 'published'>('all');
    const [createOpen, setCreateOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const items = applications.data?.items || [];
    const visibleItems = items.filter(app => {
        const term = query.trim().toLocaleLowerCase();
        const matchesQuery = !term || [app.name, app.description, app.key].some(value => value.toLocaleLowerCase().includes(term));
        const matchesStatus = statusFilter === 'all'
            || (statusFilter === 'published' ? app.status === 'published' : app.status === 'draft' || app.status === 'review');
        return matchesQuery && matchesStatus;
    });
    const stats = overview.data;
    const published = stats?.by_status.published ?? items.filter(app => app.status === 'published').length;
    const drafts = (stats?.by_status.draft ?? 0) + (stats?.by_status.review ?? 0);

    function openCreate() {
        setError('');
        form.resetFields();
        setCreateOpen(true);
    }

    async function createApplication(values: CreateApplicationValues) {
        setBusy(true);
        setError('');
        try {
            const config: ServiceApplicationConfig = {
                schema_version: 'v1',
                name: values.name,
                description: values.description?.trim() || '',
                service_categories: [],
                scenarios: [],
                capabilities: [],
                default_execution_order: ['deterministic', 'action', 'agent', 'human'],
                channels: [],
            };
            const created = await createServiceApplication(values.key, config);
            applications.refresh();
            overview.refresh();
            setCreateOpen(false);
            toast.success('服务应用已创建');
            onNavigate(`/service-apps/${created.key}`);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '创建服务应用失败');
        }
        finally {
            setBusy(false);
        }
    }

    return <div className="sa-catalog">
        <section className="sa-catalog-hero">
            <div>
                <span className="sa-eyebrow">SERVICE APPLICATIONS</span>
                <h2>把业务编排和执行能力交付成应用</h2>
                <p>应用负责服务目录、场景和对象；能力负责 Direct、查询、办理、Agent 与人工。配置、预览、调试和发布都在同一个应用内完成。</p>
            </div>
            <Button type="primary" icon={<PlusOutlined/>} disabled={!admin} onClick={openCreate}>新建服务应用</Button>
        </section>

        <Alert error={applications.error || overview.error}/>

        <section className="sa-catalog-metrics">
            <CatalogMetric label="服务应用" value={String(stats?.applications ?? items.length)} hint={`${published} 个已发布 · ${drafts} 个待完善`}/>
            <CatalogMetric label="服务场景" value={String(stats?.scenarios ?? items.reduce((sum, app) => sum + app.scenario_count, 0))} hint="已纳入应用编排"/>
            <CatalogMetric label="能力引用" value={String(stats?.capabilities ?? items.reduce((sum, app) => sum + app.capability_count, 0))} hint="Direct · 查询 · 办理 · Agent · 人工"/>
            <CatalogMetric label="模拟运行" value={String(stats?.simulations ?? 0)} hint="应用中持久化的模拟轨迹"/>
        </section>

        <div className="sa-section-head">
            <div><span className="sa-eyebrow">APPLICATIONS</span><h3>服务应用</h3></div>
            <div className="sa-catalog-filter">
                <Input.Search allowClear value={query} placeholder="搜索应用名称、标识或描述" onChange={event => setQuery(event.target.value)}/>
                <Select value={statusFilter} onChange={setStatusFilter} options={[
                    { value: 'all', label: '全部应用' },
                    { value: 'draft', label: '配置中' },
                    { value: 'published', label: '已发布' },
                ]}/>
            </div>
        </div>

        <div className="sa-app-grid">
            {visibleItems.map((app, index) => <button
                type="button"
                className={`sa-app-card ${applicationTones[index % applicationTones.length]}`}
                key={app.id}
                onClick={() => onNavigate(`/service-apps/${app.key}`)}
            >
                <div className="sa-app-card-top">
                    <span className="sa-app-icon"><ApartmentOutlined/></span>
                    <span className={`sa-app-state ${app.status === 'published' ? '' : 'waiting'}`}><i/>{applicationStatusLabel[app.status]}</span>
                </div>
                <h3>{app.name}</h3>
                <p>{app.description || '尚未填写应用描述'}</p>
                <div className="sa-app-numbers">
                    <span><strong>{app.scenario_count}</strong><small>业务场景</small></span>
                    <span><strong>{app.capability_count}</strong><small>执行能力</small></span>
                    <span><strong>{app.published_version ? `v${app.published_version}` : '未发布'}</strong><small>当前版本</small></span>
                </div>
                <div className="sa-app-card-foot">
                    <span><ClockCircleOutlined/> 最近更新 {updatedLabel(app.updated_at)}</span>
                    <b>打开应用 <ArrowRightOutlined/></b>
                </div>
            </button>)}
            {applications.loading && !applications.data && <div className="sa-catalog-loading"><Spin/></div>}
            {!applications.loading && !visibleItems.length && <div className="sa-app-empty">
                <ApartmentOutlined/>
                <strong>{items.length ? '没有匹配的服务应用' : '还没有服务应用'}</strong>
                <p>{items.length ? '调整搜索条件后再试。' : '新建应用后，从业务编排、执行能力和发布开始配置。'}</p>
            </div>}
            {admin && <button type="button" className="sa-app-card sa-app-card-create" onClick={openCreate}>
                <span><PlusOutlined/></span>
                <strong>新建服务应用</strong>
                <p>从服务目录、业务对象和执行能力开始组装。</p>
            </button>}
        </div>

        <Modal title="新建服务应用" open={createOpen} okText="创建应用" cancelText="取消" confirmLoading={busy} destroyOnHidden
            onCancel={() => {
                if (busy) return;
                setCreateOpen(false);
                setError('');
                form.resetFields();
            }}
            onOk={() => form.submit()}
        >
            <Alert error={error}/>
            <Form form={form} layout="vertical" onFinish={createApplication}>
                <Form.Item name="name" label="应用名称" rules={[{ required: true, whitespace: true, message: '请输入应用名称' }]}>
                    <Input maxLength={100} showCount placeholder="例如：账号安全服务应用"/>
                </Form.Item>
                <Form.Item name="key" label="应用标识" extra="小写字母开头，可包含小写字母、数字、- 和 _；创建后不可修改。"
                    rules={[
                        { required: true, message: '请输入应用标识' },
                        { pattern: /^[a-z][a-z0-9_-]{0,63}$/, message: '请使用小写字母、数字、- 或 _，并以小写字母开头' },
                    ]}
                >
                    <Input addonBefore="/service-apps/" maxLength={64} placeholder="account-service"/>
                </Form.Item>
                <Form.Item name="description" label="应用描述">
                    <Input.TextArea rows={3} maxLength={1000} showCount placeholder="说明这个应用承接哪些客户服务。"/>
                </Form.Item>
            </Form>
        </Modal>
    </div>;
}

function ServiceAppStudio({ route, onNavigate, onMetaChange }: { route: string; onNavigate: (path: string) => void; onMetaChange?: MetaChange }) {
    const { admin } = useAccess();
    const [section, setSection] = useState<StudioSection>('orchestration');
    const advancedSceneKey = route.match(/^\/service-apps\/[a-z0-9-]+\/scenarios\/([a-z][a-z0-9_-]{0,63})$/)?.[1] || '';
    const [debug, setDebug] = useState(false);
    const [activeSceneKey, setActiveSceneKey] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [scenarioOpen, setScenarioOpen] = useState(false);
    const [catalogOpen, setCatalogOpen] = useState(false);
    const [scenarioForm] = Form.useForm<{
        name: string;
        key: string;
        description?: string;
        template: ScenarioTemplate;
        category: string;
        objectType?: string;
    }>();
    const basePath = appBasePath(route);
    const appKey = appKeyFromRoute(route);
    const application = useResource<ServiceApplicationSummary>(`/service-apps/${appKey}`);
    const scenarios = useResource<ServiceScenarioPage>('/service-scenarios');
    const versions = useResource<ServiceApplicationVersionPage>(`/service-apps/${appKey}/versions`);
    const traces = useResource<ServiceTracePage>(`/service-apps/${appKey}/traces?limit=50`);
    const app = application.data;
    const appScenarios = useMemo<AppScenario[]>(() => {
        if (!app || !scenarios.data) return [];
        const byKey = new Map(scenarios.data.items.map(item => [item.key, item]));
        return app.config.scenarios.map(reference => {
            const source = byKey.get(reference.key);
            if (!source) return null;
            return {
                key: source.key,
                name: source.name,
                description: source.description,
                category: source.config.category || source.config.domain || '其他服务',
                status: source.status,
                version: reference.version ?? source.published_version,
                enabled: reference.enabled !== false,
                config: source.config,
                source,
            };
        }).filter((item): item is AppScenario => !!item);
    }, [app, scenarios.data]);
    const serviceCategories = useMemo(
        () => effectiveServiceCategories(app, scenarios.data?.items || []),
        [app, scenarios.data],
    );

    useEffect(() => {
        if (!app) return;
        onMetaChange?.({
            path: route,
            title: app.name,
            description: app.description,
        });
    }, [app, onMetaChange, route]);

    useEffect(() => {
        if (!appScenarios.length) {
            setActiveSceneKey('');
            return;
        }
        if (!appScenarios.some(item => item.key === activeSceneKey)) setActiveSceneKey(appScenarios[0].key);
    }, [activeSceneKey, appScenarios]);

    useEffect(() => {
        if (advancedSceneKey && appScenarios.some(item => item.key === advancedSceneKey)) {
            setActiveSceneKey(advancedSceneKey);
        }
    }, [advancedSceneKey, appScenarios]);

    const activeScene = appScenarios.find(item => item.key === activeSceneKey) || appScenarios[0];

    async function saveAppConfig(next: ServiceApplicationConfig, message = '应用配置已保存') {
        if (!app) return;
        setBusy(true);
        setError('');
        try {
            const updated = await updateServiceApplication(app.key, next, app.revision);
            application.refresh();
            scenarios.refresh();
            toast.success(`${message}${updated.revision ? `（r${updated.revision}）` : ''}`);
        }
        catch (cause) {
            const text = cause instanceof Error ? cause.message : '保存应用配置失败';
            setError(text);
            throw cause;
        }
        finally {
            setBusy(false);
        }
    }

    async function publish() {
        if (!app) return;
        setBusy(true);
        setError('');
        try {
            const updated = await publishServiceApplication(app.key, app.revision);
            application.refresh();
            versions.refresh();
            toast.success(`应用已发布${updated.published_version ? `为 v${updated.published_version}` : ''}`);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '发布服务应用失败');
        }
        finally {
            setBusy(false);
        }
    }

    function openCreateScenario(category?: string) {
        scenarioForm.resetFields();
        scenarioForm.setFieldsValue({
            template: 'consult',
            category: category || activeScene?.category || serviceCategories[0]?.name,
        });
        setError('');
        setScenarioOpen(true);
    }

    async function createScenario() {
        if (!app) return;
        const values = await scenarioForm.validateFields();
        const config = newScenarioConfig({
            name: values.name,
            description: values.description,
            template: values.template,
            category: values.category,
            objectType: values.objectType,
        });
        setBusy(true);
        setError('');
        try {
            await createServiceScenario(values.key, config);
            const next = withApplicationScenario(app.config, values.key);
            await updateServiceApplication(app.key, next, app.revision);
            setScenarioOpen(false);
            scenarioForm.resetFields();
            application.refresh();
            scenarios.refresh();
            toast.success('服务场景已创建并加入应用');
            onNavigate(`/service-apps/${app.key}/scenarios/${values.key}`);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '创建服务场景失败');
        }
        finally {
            setBusy(false);
        }
    }

    function openPreview(nextDebug: boolean) {
        setDebug(nextDebug);
        setSection('preview');
        if (advancedSceneKey) onNavigate(basePath);
    }

    if (!app && application.loading) return <div className="sa-studio-loading"><Spin/></div>;
    if (!app) return <div className="sa-studio">
        <div className="sa-app-bar">
            <div className="sa-app-identity">
                <button type="button" className="sa-back-link" onClick={() => onNavigate('/service-apps')} aria-label="返回服务应用"><AppstoreOutlined/></button>
                <div><h2>无法打开服务应用</h2><p>应用不存在，或当前账号没有访问权限。</p></div>
            </div>
            <Button onClick={() => onNavigate('/service-apps')}>返回服务应用列表</Button>
        </div>
        <Alert error={application.error || '服务应用不存在'}/>
    </div>;

    const hasScenarios = appScenarios.length > 0;
    return <div className="sa-studio">
        <div className="sa-app-bar">
            <div className="sa-app-identity">
                <button type="button" className="sa-back-link" onClick={() => onNavigate('/service-apps')} aria-label="返回服务应用"><AppstoreOutlined/></button>
                <span className="sa-app-mark"><ApartmentOutlined/></span>
                <div>
                    <div className="sa-app-title-line">
                        <h2>{app.name}</h2>
                        <span className="sa-app-version">{app.published_version ? `v${app.published_version}` : '未发布'}</span>
                        <span className={`sa-app-state ${app.status === 'published' ? '' : 'waiting'}`}><i/>{applicationStatusLabel[app.status]}</span>
                    </div>
                    <p>{app.description || '尚未填写应用描述'}</p>
                </div>
            </div>
            <div className="sa-app-actions">
                <Button aria-label="服务目录" disabled={!admin} icon={<BookOutlined/>} onClick={() => setCatalogOpen(true)}>服务目录</Button>
                <Button disabled={!hasScenarios} icon={<CustomerServiceOutlined/>} aria-label="统一体验" onClick={() => onNavigate(`${basePath}/experience`)}>统一体验</Button>
                <Button disabled={!hasScenarios} icon={<EyeOutlined/>} aria-label="预览" onClick={() => openPreview(false)}>预览</Button>
                <Button disabled={!hasScenarios} icon={<BugOutlined/>} aria-label="调试" onClick={() => openPreview(true)}>调试</Button>
                <Button type="primary" disabled={!admin || busy} loading={busy} onClick={() => void publish()}>发布新版本</Button>
            </div>
        </div>

        <Alert error={error || application.error || scenarios.error || versions.error || traces.error}/>

        {!hasScenarios ? <EmptyApplicationWorkspace
            application={app}
            admin={admin}
            catalogCount={serviceCategories.length}
            onCreate={() => openCreateScenario()}
            onManageCatalog={() => setCatalogOpen(true)}
        /> : <>
            <nav className="sa-studio-tabs" aria-label="服务应用工作区">
                {studioTabs.map(tab => <button
                    type="button"
                    key={tab.key}
                    className={section === tab.key && !advancedSceneKey ? 'is-active' : ''}
                    onClick={() => {
                        setSection(tab.key);
                        if (advancedSceneKey) onNavigate(basePath);
                    }}
                >
                    {tab.label}
                    {tab.key === 'preview' && section === 'preview' && !advancedSceneKey && <i>{debug ? '调试中' : '预览中'}</i>}
                </button>)}
                <button
                    type="button"
                    className={`sa-studio-advanced${advancedSceneKey ? ' is-active' : ''}`}
                    aria-label="高级设置"
                    aria-current={advancedSceneKey ? 'page' : undefined}
                    disabled={!activeScene}
                    onClick={() => {
                        if (!advancedSceneKey && activeScene) onNavigate(`${basePath}/scenarios/${activeScene.key}`);
                    }}
                >
                    <SettingOutlined/>
                    高级设置
                </button>
            </nav>

            {advancedSceneKey ? <SceneWorkbench
                route={route}
                onNavigate={onNavigate}
                onMetaChange={onMetaChange}
                onScenarioChanged={() => {
                    scenarios.refresh();
                    application.refresh();
                }}
                embedded
            /> : <>
            {section === 'overview' && <OverviewTab
                application={app}
                scenes={appScenarios}
                versions={versions.data}
                traces={traces.data}
                basePath={basePath}
                onNavigate={onNavigate}
                onPreview={() => openPreview(false)}
                onHistory={() => setSection('deploy')}
            />}
            {section === 'orchestration' && activeScene && <OrchestrationTab
                application={app}
                scenes={appScenarios}
                activeScene={activeScene}
                admin={admin}
                busy={busy}
                onScene={setActiveSceneKey}
                onCreate={() => openCreateScenario()}
                serviceCategories={serviceCategories}
                onManageCatalog={() => setCatalogOpen(true)}
                onToggleScene={scene => {
                    const next = {
                        ...app.config,
                        scenarios: app.config.scenarios.map(item => item.key === scene.key ? { ...item, enabled: !scene.enabled } : item),
                    };
                    void saveAppConfig(next, scene.enabled ? '场景已停用' : '场景已启用').catch(() => undefined);
                }}
                onNavigate={onNavigate}
                basePath={basePath}
                onDebug={() => openPreview(true)}
            />}
            {section === 'capabilities' && <CapabilitiesTab
                application={app}
                admin={admin}
                busy={busy}
                onSave={saveAppConfig}
                onNavigate={onNavigate}
            />}
            {section === 'preview' && <PreviewTab
                application={app}
                scenes={appScenarios}
                debug={debug}
                onDebug={setDebug}
                onError={setError}
            />}
            {section === 'deploy' && <DeployTab
                application={app}
                versions={versions.data}
                traces={traces.data}
                admin={admin}
                busy={busy}
                onNavigate={onNavigate}
                onPublish={publish}
                onRefresh={() => {
                    application.refresh();
                    versions.refresh();
                    traces.refresh();
                }}
                onSave={saveAppConfig}
            />}
            </>}
        </>}

        {admin && <ServiceCatalogManager
            open={catalogOpen}
            application={app}
            scenes={scenarios.data?.items || []}
            onClose={() => setCatalogOpen(false)}
            onSaved={() => {
                application.refresh();
                scenarios.refresh();
                toast.success('服务目录已保存，关联场景已同步');
            }}
        />}

        <Modal
            open={scenarioOpen}
            title="新建服务场景"
            okText="创建并配置"
            cancelText="取消"
            confirmLoading={busy}
            destroyOnHidden
            okButtonProps={{ disabled: !serviceCategories.length }}
            onCancel={() => {
                if (busy) return;
                setScenarioOpen(false);
                scenarioForm.resetFields();
            }}
            onOk={() => void createScenario()}
        >
            <Alert error={error}/>
            <Form form={scenarioForm} layout="vertical" initialValues={{ template: 'consult' }}>
                <Form.Item name="name" label="场景名称" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如：查询我的订单"/></Form.Item>
                <Form.Item name="key" label="场景标识" extra="小写字母开头，创建后不可修改" rules={[{ required: true }, { pattern: /^[a-z][a-z0-9_-]{0,63}$/ }]}>
                    <Input addonBefore="/scenarios/" placeholder="query-orders"/>
                </Form.Item>
                <Form.Item name="description" label="客户任务"><Input.TextArea rows={2} placeholder="说明这个场景帮助客户完成什么"/></Form.Item>
                <Form.Item
                    name="category"
                    label="服务目录"
                    extra={serviceCategories.length ? '分类由当前应用统一维护，场景不能自由填写。' : '当前应用还没有服务分类，请先管理服务目录。'}
                    rules={[{ required: true, message: '请选择服务目录' }]}
                >
                    <Select
                        placeholder="选择应用级服务分类"
                        showSearch
                        optionFilterProp="label"
                        options={serviceCategories.map(category => ({
                            value: category.name,
                            label: `${category.name}${category.scenarioCount ? ` · ${category.scenarioCount} 个场景` : ''}`,
                        }))}
                    />
                </Form.Item>
                <Form.Item name="template" label="场景模板" rules={[{ required: true }]}>
                    <Select options={[
                        { value: 'consult', label: '咨询 · Direct / 知识 / Agent' },
                        { value: 'query', label: '查询 · 带业务对象和查询承接' },
                        { value: 'action', label: '办理 · 带确认与业务动作' },
                    ]}/>
                </Form.Item>
                <Form.Item name="objectType" label="业务对象类型" extra="查询和办理模板会要求绑定业务对象"><Input placeholder="order"/></Form.Item>
            </Form>
        </Modal>
    </div>;
}

function EmptyApplicationWorkspace({ application, admin, catalogCount, onCreate, onManageCatalog }: {
    application: ServiceApplicationSummary;
    admin: boolean;
    catalogCount: number;
    onCreate: () => void;
    onManageCatalog: () => void;
}) {
    return <section className="sa-empty-workspace">
        <span className="sa-empty-workspace-mark"><DeploymentUnitOutlined/></span>
        <span className="sa-eyebrow">NEW SERVICE APPLICATION</span>
        <h3>{application.name} 已创建</h3>
        <p>应用还没有业务编排或执行能力。先建立应用级服务目录，再定义场景，把确定性查询、业务办理、Agent 和人工承接组合到应用版本中。</p>
        <div className="sa-empty-steps">
            <article><span>01</span><strong>服务目录</strong><small>{catalogCount ? `${catalogCount} 个分类可用` : '先建立统一分类'}</small></article>
            <article><span>02</span><strong>业务编排</strong><small>从目录选择分类并添加场景</small></article>
            <article><span>03</span><strong>执行能力</strong><small>绑定 Direct、查询、办理、Agent 或人工</small></article>
            <article><span>04</span><strong>预览调试</strong><small>用模拟客户和模拟对象验证完整路径</small></article>
            <article><span>05</span><strong>接入发布</strong><small>配置客户触点并发布不可变版本</small></article>
        </div>
        <div className="sa-empty-actions">
            <Button icon={<BookOutlined/>} disabled={!admin} onClick={onManageCatalog}>管理服务目录</Button>
            <Button type="primary" icon={<PlusOutlined/>} disabled={!admin || !catalogCount} onClick={onCreate}>新建服务场景</Button>
        </div>
    </section>;
}

function OverviewTab({ application, scenes, versions, traces, basePath, onNavigate, onPreview, onHistory }: {
    application: ServiceApplicationSummary;
    scenes: AppScenario[];
    versions?: ServiceApplicationVersionPage | null;
    traces?: ServiceTracePage | null;
    basePath: string;
    onNavigate: (path: string) => void;
    onPreview: () => void;
    onHistory: () => void;
}) {
    const published = versions?.items.find(item => item.version === application.published_version);
    const recentTraces = traces?.items.slice(0, 3) || [];
    const recentVersions = versions?.items.slice(0, 3) || [];
    const statusText = application.status === 'published' ? '应用已发布' : application.status === 'review' ? '应用待发布' : application.status === 'offline' ? '应用已下线' : '应用配置中';

    return <div className="sa-overview">
        <section className="sa-overview-hero">
            <div>
                <span className="sa-eyebrow">APPLICATION STATUS</span>
                <h3>{statusText}</h3>
                <p>{application.has_unpublished_changes
                    ? `当前草稿 revision ${application.revision} 尚未发布；最近发布版本 ${application.published_version ? `v${application.published_version}` : '暂无'}。`
                    : `当前草稿 revision ${application.revision} 与发布状态一致。`}</p>
                <div className="sa-hero-actions">
                    <Button type="primary" icon={<EyeOutlined/>} onClick={onPreview}>预览客户视角</Button>
                    <Button onClick={() => onNavigate(`${basePath}/scenarios/${scenes[0]?.key || ''}`)} disabled={!scenes.length}>打开场景高级配置</Button>
                </div>
            </div>
            <div className="sa-health-radar">
                <span className="sa-health-ring"><strong>{application.scenario_count}</strong><small>已编排场景</small></span>
                <div>
                    <span><i className={application.has_unpublished_changes ? 'amber' : 'green'}/>{application.has_unpublished_changes ? '存在未发布修改' : '草稿与发布一致'}</span>
                    <span><i className={scenes.every(item => item.source.status === 'published') ? 'green' : 'amber'}/>场景发布状态</span>
                    <span><i className={traces?.items.length ? 'green' : 'amber'}/>{traces?.items.length || 0} 次模拟轨迹</span>
                </div>
            </div>
        </section>

        <section className="sa-metric-grid">
            <StudioMetric label="服务场景" value={String(application.scenario_count)} hint={`${scenes.filter(item => item.source.status === 'published').length} 个已发布`}/>
            <StudioMetric label="执行能力" value={String(application.capability_count)} hint={`${application.config.capabilities.filter(item => item.enabled !== false).length} 个已启用`}/>
            <StudioMetric label="客户触点" value={String(application.channel_count)} hint="配置中的接入渠道"/>
            <StudioMetric label="模拟运行" value={String(traces?.items.length || 0)} hint="后端持久化 trace"/>
        </section>

        <section className="sa-composition">
            <div className="sa-section-head"><div><span className="sa-eyebrow">APPLICATION MAP</span><h3>应用组成</h3></div><span className="sa-muted-note">业务编排与执行能力通过引用关系组合</span></div>
            <div className="sa-composition-map">
                <CompositionCard icon={<ApartmentOutlined/>} title="业务编排" value={`${application.scenario_count} 个服务场景`} hint={scenes.map(item => item.name).slice(0, 3).join(' · ') || '尚未添加场景'} tone="violet"/>
                <span className="sa-map-arrow"><ArrowRightOutlined/></span>
                <CompositionCard icon={<ToolOutlined/>} title="执行能力" value={`${application.capability_count} 个能力引用`} hint={application.config.capabilities.slice(0, 4).map(item => capabilityTypeLabel[item.type]).join(' · ') || '尚未添加能力'} tone="blue"/>
                <span className="sa-map-arrow"><ArrowRightOutlined/></span>
                <CompositionCard icon={<GlobalOutlined/>} title="客户触点" value={`${application.channel_count} 个渠道`} hint={application.config.channels.map(item => item.name).join(' · ') || '尚未接入渠道'} tone="green"/>
            </div>
        </section>

        <div className="sa-overview-bottom">
            <section className="sa-panel">
                <div className="sa-panel-head"><div><span className="sa-eyebrow">RECENT ACTIVITY</span><h3>最近变更</h3></div><Button type="link" onClick={onHistory}>查看全部</Button></div>
                {recentVersions.map(version => <ChangeRow key={`version-${version.id}`} icon={<CheckCircleFilled/>} title={`应用 v${version.version}`} detail={`由 ${version.created_by} 发布，包含 ${version.config.scenarios.length} 个场景`} time={updatedLabel(version.created_at)} tone="green"/>)}
                {recentTraces.map(item => <ChangeRow key={`trace-${item.id}`} icon={<BugOutlined/>} title={item.scenario_key} detail={`${item.outcome} · ${item.result_summary || '无结果摘要'}`} time={updatedLabel(item.created_at)} tone="violet"/>)}
                {!recentVersions.length && !recentTraces.length && <p className="sa-muted-note">尚无发布或模拟记录。</p>}
            </section>
            <section className="sa-panel sa-version-panel">
                <div className="sa-panel-head"><div><span className="sa-eyebrow">VERSION</span><h3>发布版本</h3></div><span className="sa-app-published"><i/>{application.published_version ? '已发布' : '未发布'}</span></div>
                <div className="sa-version-current"><span>{application.published_version ? `v${application.published_version}` : '草稿'}</span><div><strong>{published ? '当前生产版本' : '当前应用草稿'}</strong><small>{published ? `${updatedLabel(published.created_at)} · ${published.created_by}` : `revision ${application.revision}`}</small></div></div>
                <div className="sa-version-row"><span>业务编排</span><b>{application.scenario_count} 个场景</b></div>
                <div className="sa-version-row"><span>能力引用</span><b>{application.capability_count} 个能力</b></div>
                <div className="sa-version-row"><span>接入渠道</span><b>{application.channel_count} 个</b></div>
                <Button block icon={<HistoryOutlined/>} onClick={onHistory}>查看版本历史</Button>
            </section>
        </div>
    </div>;
}

function OrchestrationTab({ application, scenes, activeScene, admin, busy, onScene, onCreate, onToggleScene, onNavigate, basePath, onDebug, serviceCategories, onManageCatalog }: {
    application: ServiceApplicationSummary;
    scenes: AppScenario[];
    activeScene: AppScenario;
    serviceCategories: ReturnType<typeof effectiveServiceCategories>;
    admin: boolean;
    busy: boolean;
    onScene: (key: string) => void;
    onCreate: () => void;
    onToggleScene: (scene: AppScenario) => void;
    onNavigate: (path: string) => void;
    basePath: string;
    onDebug: () => void;
    onManageCatalog: () => void;
}) {
    const [query, setQuery] = useState('');
    const groups = useMemo(() => {
        const filtered = scenes.filter(item => !query.trim()
            || `${item.name} ${item.description} ${item.key}`
                .toLocaleLowerCase()
                .includes(query.trim().toLocaleLowerCase()));
        return groupScenariosByCategory(filtered, serviceCategories);
    }, [query, scenes, serviceCategories]);
    const enabledHandlers = activeScene.config.handlers.filter(item => item.enabled !== false);

    return <div className="sa-orchestration">
        <aside className="sa-scene-tree">
            <div className="sa-scene-tree-head"><div><span className="sa-eyebrow">BUSINESS ORCHESTRATION</span><h3>业务编排</h3></div>
                <div className="sa-scene-tree-actions">
                    <Button type="text" shape="circle" icon={<BookOutlined/>} aria-label="管理服务目录" disabled={!admin} onClick={onManageCatalog}/>
                    <Button type="text" shape="circle" icon={<PlusOutlined/>} aria-label="新建场景" disabled={!admin || !serviceCategories.length} onClick={onCreate}/>
                </div>
            </div>
            <Input.Search placeholder="搜索场景" size="small" allowClear value={query} onChange={event => setQuery(event.target.value)}/>
            <div className="sa-tree-groups">
                {groups.map(([group, items]) => <div className="sa-tree-group" key={group}>
                    <span className="sa-tree-label">{group}</span>
                    {items.map(scene => <button
                        type="button"
                        key={scene.key}
                        className={`sa-tree-scene ${scene.key === activeScene.key ? 'is-active' : ''} ${scene.enabled ? '' : 'is-disabled'}`}
                        onClick={() => onScene(scene.key)}
                    >
                        <span className="sa-tree-scene-icon">{scenarioVisual(scene)}</span>
                        <span><strong>{scene.name}</strong><small>{scene.config.object ? `${scene.config.object.type}对象` : '无需业务对象'}</small></span>
                        <i className={scene.status}/>
                    </button>)}
                </div>)}
                {!groups.length && <p className="sa-muted-note">没有匹配场景。</p>}
            </div>
            <button type="button" className="sa-tree-foot" onClick={onManageCatalog} disabled={!admin}>
                <BookOutlined/><span>{serviceCategories.length} 个服务分类 · 由应用统一维护</span>
            </button>
        </aside>

        <main className="sa-scene-canvas">
            <header className="sa-canvas-head">
                <div className="sa-canvas-title">
                    <span className="sa-canvas-icon">{scenarioVisual(activeScene)}</span>
                    <div><span className="sa-eyebrow">SCENE ORCHESTRATION</span><h3>{activeScene.name}</h3><p>{activeScene.description}</p></div>
                </div>
                <div className="sa-canvas-actions">
                    <span className={`sa-scene-status ${activeScene.status}`}><i/>{scenarioStatusLabel(activeScene.status)}{activeScene.version ? ` · v${activeScene.version}` : ' · 未发布'}</span>
                    <Button icon={<BugOutlined/>} onClick={onDebug}>调试</Button>
                    <Button type="primary" icon={<CodeOutlined/>} onClick={() => onNavigate(`${basePath}/scenarios/${activeScene.key}`)}>编辑场景</Button>
                </div>
            </header>

            <div className="sa-orchestration-summary">
                <span><strong>{activeScene.config.entries.length}</strong> 个入口</span>
                <span><strong>{activeScene.config.facts.length}</strong> 项业务事实</span>
                <span><strong>{activeScene.config.decisions.length}</strong> 个用户决策</span>
                <span><strong>{enabledHandlers.length}</strong> 个可用承接</span>
            </div>

            <section className="sa-flow">
                <FlowStage number="01" title="入口方式" hint="客户从哪里到达场景" icon={<BranchesOutlined/>} tone="slate">
                    <div className="sa-flow-chips">{activeScene.config.entries.filter(item => item.enabled !== false).map(item => <span key={item.key}>{item.label}</span>)}</div>
                </FlowStage>
                <FlowStage number="02" title="业务对象" hint="场景围绕什么业务实体继续" icon={<DatabaseOutlined/>} tone="blue">
                    <div className="sa-object-card">
                        <span><ShoppingOutlined/></span>
                        <div><strong>{activeScene.config.object?.type || '无需对象'}</strong><small>{activeScene.config.object ? `${activeScene.config.object.provider} · ${activeScene.config.object.mode}` : '可由知识或固定规则直接处理'}</small></div>
                        <b>{activeScene.config.object?.required ? '必填' : '可选'}</b>
                    </div>
                </FlowStage>
                <FlowStage number="03" title="业务事实" hint="只向后续能力投影必要事实" icon={<FileSearchOutlined/>} tone="amber">
                    <div className="sa-flow-chips facts">{activeScene.config.facts.map(item => <span key={item.key}>{item.label}</span>)}</div>
                </FlowStage>
                <FlowStage number="04" title="用户决策" hint="把模糊问题收敛成可执行选择" icon={<MessageOutlined/>} tone="violet">
                    <div className="sa-decision-list">{activeScene.config.decisions.map((item, index) => <span key={item.key}><i>{String(index + 1).padStart(2, '0')}</i>{item.label}</span>)}</div>
                </FlowStage>
                <FlowStage number="05" title="处理承接" hint="确定性优先，复杂问题才升级 Agent" icon={<DeploymentUnitOutlined/>} tone="green" last>
                    <div className="sa-capability-chain">
                        {activeScene.config.fallback_order.map(key => activeScene.config.handlers.find(item => item.key === key)).filter((item): item is ScenarioHandler => !!item).map((item, index) => <span key={item.key} className={item.type === 'agent' ? 'agent' : ''}>
                            {item.type === 'agent' ? <RobotOutlined/> : item.type === 'human' ? <CustomerServiceOutlined/> : <ThunderboltOutlined/>}
                            {item.label}{index < activeScene.config.fallback_order.length - 1 && <ArrowRightOutlined/>}
                        </span>)}
                    </div>
                </FlowStage>
            </section>
        </main>

        <aside className="sa-inspector">
            <div className="sa-inspector-head"><div><span className="sa-eyebrow">INSPECTOR</span><h3>场景设置</h3></div><SettingOutlined/></div>
            <div className="sa-inspector-group">
                <label>场景名称<Input value={activeScene.name} readOnly/></label>
                <label>所属服务目录<Input value={activeScene.category} readOnly/></label>
                <div className="sa-inspector-switch"><span><strong>在应用中启用</strong><small>关闭后请求不会路由到该场景</small></span>
                    <Switch checked={activeScene.enabled} disabled={!admin || busy} onChange={() => onToggleScene(activeScene)} size="small"/>
                </div>
            </div>
            <div className="sa-inspector-group">
                <div className="sa-inspector-label"><span>处理能力</span></div>
                {enabledHandlers.map((handler, index) => <CapabilityBinding key={handler.key} index={String(index + 1)} title={handler.label} hint={`${handlerTypeLabel(handler.type)}${handler.tool ? ` · ${handler.tool}` : ''}${handler.queue ? ` · ${handler.queue}` : ''}`} icon={handler.type === 'agent' ? <RobotOutlined/> : handler.type === 'human' ? <CustomerServiceOutlined/> : <ThunderboltOutlined/>} tone={handler.type === 'agent' ? 'violet' : handler.type === 'human' ? 'amber' : 'green'}/>)}
                {!enabledHandlers.length && <p className="sa-muted-note">该场景尚未启用执行能力。</p>}
            </div>
            <div className="sa-inspector-group">
                <div className="sa-inspector-label"><span>预览调试</span></div>
                <div className="sa-inspector-preview">
                    <span><EyeOutlined/></span>
                    <div><strong>客户视角预览</strong><small>调用后端模拟接口验证完整链路</small></div>
                    <Button size="small" onClick={onDebug}>打开</Button>
                </div>
            </div>
            <Button block icon={<CodeOutlined/>} onClick={() => onNavigate(`${basePath}/scenarios/${activeScene.key}`)}>打开场景高级配置</Button>
            <p className="sa-inspector-note"><SafetyCertificateOutlined/> Agent 是应用引用的执行资源，Prompt、模型和工具在 Agent 管理中维护。</p>
        </aside>
    </div>;
}

const capabilityTypes: ApplicationCapabilityType[] = [
    'direct',
    'knowledge',
    'query',
    'action',
    'agent',
    'human',
    'tracking',
];

interface CapabilityFormValues {
    key: string;
    type: ApplicationCapabilityType;
    label: string;
    description?: string;
    priority?: number;
    enabled?: boolean;
    agent_id?: string;
    queue?: string;
    tool?: string;
}

function capabilityDescription(capability: ApplicationCapability) {
    return capability.description
        || String(capability.config?.description || '')
        || '尚未填写能力说明';
}

function CapabilitiesTab({ application, admin, busy, onSave, onNavigate }: {
    application: ServiceApplicationSummary;
    admin: boolean;
    busy: boolean;
    onSave: (next: ServiceApplicationConfig, message?: string) => Promise<void>;
    onNavigate: (path: string) => void;
}) {
    const agents = useResource<Agent[]>('/agents');
    const [form] = Form.useForm<CapabilityFormValues>();
    const [modalOpen, setModalOpen] = useState(false);
    const [editingKey, setEditingKey] = useState<string | null>(null);
    const selectedType = Form.useWatch('type', form);
    const capabilities = application.config.capabilities;
    const nextPriority = capabilities.reduce((max, item) => Math.max(max, item.priority || 0), 0) + 10;

    function openCreate() {
        setEditingKey(null);
        form.resetFields();
        form.setFieldsValue({
            type: 'direct',
            priority: nextPriority,
            enabled: true,
            key: `capability-${nextPriority}`,
            label: '新执行能力',
        });
        setModalOpen(true);
    }

    function openEdit(capability: ApplicationCapability) {
        setEditingKey(capability.key);
        form.resetFields();
        form.setFieldsValue({
            key: capability.key,
            type: capability.type,
            label: capability.label,
            description: capabilityDescription(capability),
            priority: capability.priority ?? 0,
            enabled: capability.enabled !== false,
            agent_id: capability.agent_id || undefined,
            queue: capability.queue || undefined,
            tool: capability.tool || undefined,
        });
        setModalOpen(true);
    }

    async function saveCapability() {
        const values = await form.validateFields();
        const previous = capabilities.find(item => item.key === editingKey);
        const selectedAgent = agents.data?.find(item => item.id === values.agent_id);
        const duplicate = capabilities.some(item => item.key === values.key && item.key !== editingKey);
        if (duplicate) {
            form.setFields([{ name: 'key', errors: ['能力标识不能重复'] }]);
            return;
        }
        if (values.type === 'agent' && !selectedAgent) {
            form.setFields([{ name: 'agent_id', errors: ['请选择一个已存在的 Agent'] }]);
            return;
        }
        const description = values.description?.trim() || '';
        const capability: ApplicationCapability = {
            key: values.key.trim(),
            type: values.type,
            label: values.label.trim(),
            description,
            enabled: values.enabled !== false,
            priority: values.priority ?? 0,
            when: previous?.when || {},
            agent_id: values.type === 'agent' ? selectedAgent?.id || null : null,
            agent_version: values.type === 'agent'
                ? selectedAgent?.published_version ?? previous?.agent_version ?? null
                : null,
            agent_name: values.type === 'agent'
                ? selectedAgent?.name || previous?.agent_name || null
                : null,
            queue: values.type === 'human' ? values.queue?.trim() || null : null,
            tool: ['query', 'action', 'tracking'].includes(values.type)
                ? values.tool?.trim() || null
                : null,
            config: {
                ...(previous?.config || {}),
                description,
            },
        };
        const nextCapabilities = editingKey
            ? capabilities.map(item => item.key === editingKey ? capability : item)
            : [...capabilities, capability];
        await onSave(
            { ...application.config, capabilities: nextCapabilities },
            editingKey ? '执行能力已更新' : '执行能力已添加',
        );
        setModalOpen(false);
        setEditingKey(null);
        form.resetFields();
    }

    function toggleCapability(capability: ApplicationCapability) {
        const next = {
            ...application.config,
            capabilities: capabilities.map(item => item.key === capability.key
                ? { ...item, enabled: item.enabled === false }
                : item),
        };
        void onSave(next, capability.enabled === false ? '执行能力已启用' : '执行能力已停用').catch(() => undefined);
    }

    function removeCapability(capability: ApplicationCapability) {
        const next = {
            ...application.config,
            capabilities: capabilities.filter(item => item.key !== capability.key),
        };
        void onSave(next, '执行能力已移除').catch(() => undefined);
    }

    return <div className="sa-capabilities">
        <Alert error={agents.error}/>
        <section className="sa-capabilities-hero">
            <div>
                <span className="sa-eyebrow">EXECUTION CAPABILITIES</span>
                <h3>把可执行资源组织成应用能力</h3>
                <p>Direct、知识、查询、办理、Agent、人工和进度跟踪都由应用引用。Agent 的 Prompt、模型和工具仍在 Agent 管理中维护，应用只保存引用关系。</p>
            </div>
            <Button type="primary" icon={<PlusOutlined/>} disabled={!admin || busy} onClick={openCreate}>添加执行能力</Button>
        </section>

        <section className="sa-capability-explainer">
            <span className="sa-explainer-icon"><SafetyCertificateOutlined/></span>
            <div><strong>Agent 不是应用内部配置</strong><p>这里选择 Agent 并记录版本引用；能力配置、提示词和知识工具不会复制到应用配置中。</p></div>
            {!!agents.data?.length && <Button type="link" onClick={() => onNavigate('/agents')}>打开 Agent 管理 →</Button>}
        </section>

        <section className="sa-capability-grid">
            {capabilities.map(capability => <article className={`sa-capability-card ${capabilityTone(capability.type)}${capability.type === 'agent' ? ' is-agent' : ''}`} key={capability.key}>
                <div className="sa-capability-top">
                    <span className="sa-capability-icon">{capabilityIcon(capability.type)}</span>
                    <span className="sa-capability-type">{capabilityTypeLabel[capability.type]}</span>
                    <span className="sa-capability-ready"><i/>{capability.enabled === false ? '已停用' : '已配置'}</span>
                </div>
                <h4>{capability.label}</h4>
                <p>{capabilityDescription(capability)}</p>
                <div className="sa-capability-meta">
                    <span>标识 · {capability.key}</span>
                    <span>优先级 · {capability.priority ?? 0}</span>
                    {capability.agent_id && <span>Agent · {capability.agent_name || capability.agent_id}{capability.agent_version ? ` · v${capability.agent_version}` : ''}</span>}
                    {capability.queue && <span>人工队列 · {capability.queue}</span>}
                    {capability.tool && <span>工具 · {capability.tool}</span>}
                </div>
                <div className="sa-capability-foot">
                    <span>{capability.enabled === false ? '已停用' : '参与场景承接'}</span>
                    <div style={{ display: 'flex', gap: 10 }}>
                        {capability.agent_id && <Button type="link" onClick={() => onNavigate(`/agents/${capability.agent_id}/usage`)}>查看 Agent 引用</Button>}
                        <Button type="link" disabled={!admin || busy} onClick={() => openEdit(capability)}>编辑</Button>
                        <Button type="link" disabled={!admin || busy} onClick={() => toggleCapability(capability)}>{capability.enabled === false ? '启用' : '停用'}</Button>
                        <Popconfirm title="移除这个执行能力？" description="只从当前应用草稿移除，不会删除能力背后的资源。" okText="移除" cancelText="取消" disabled={!admin || busy} onConfirm={() => removeCapability(capability)}>
                            <Button type="link" danger icon={<DeleteOutlined/>} disabled={!admin || busy}>移除</Button>
                        </Popconfirm>
                    </div>
                </div>
            </article>)}
            {!capabilities.length && <div className="sa-app-empty">
                <ToolOutlined/>
                <strong>还没有执行能力</strong>
                <p>添加 Direct、查询、办理、Agent 或人工能力后，场景才能使用它们承接客户问题。</p>
            </div>}
        </section>

        <section className="sa-execution-order">
            <div className="sa-section-head"><div><span className="sa-eyebrow">DEFAULT ORDER</span><h3>默认执行顺序</h3></div><span className="sa-muted-note">实际承接顺序仍由每个场景的 fallback_order 决定</span></div>
            <div className="sa-order-line">
                {defaultExecutionStages(application.config).map((stage, index) => <div key={stage} style={{ display: 'contents' }}>
                    <OrderStep index={String(index + 1).padStart(2, '0')} title={executionStageLabel(stage)} hint={executionStageHint(stage)} tone={executionStageTone(stage)}/>
                    {index < defaultExecutionStages(application.config).length - 1 && <ArrowRightOutlined/>}
                </div>)}
            </div>
        </section>

        <Modal
            title={editingKey ? '编辑执行能力' : '添加执行能力'}
            open={modalOpen}
            okText={editingKey ? '保存能力' : '添加能力'}
            cancelText="取消"
            confirmLoading={busy}
            destroyOnHidden
            onCancel={() => {
                if (busy) return;
                setModalOpen(false);
                setEditingKey(null);
                form.resetFields();
            }}
            onOk={() => void saveCapability()}
        >
            <Form form={form} layout="vertical">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <Form.Item name="type" label="能力类型" rules={[{ required: true }]}>
                        <Select disabled={!admin} options={capabilityTypes.map(type => ({ value: type, label: capabilityTypeLabel[type] }))}/>
                    </Form.Item>
                    <Form.Item name="key" label="能力标识" rules={[
                        { required: true, whitespace: true, message: '请输入能力标识' },
                        { pattern: /^[a-z][a-z0-9_-]{0,63}$/, message: '请使用小写字母、数字、- 或 _' },
                    ]}>
                        <Input disabled={!!editingKey} placeholder="business-query"/>
                    </Form.Item>
                </div>
                <Form.Item name="label" label="展示名称" rules={[{ required: true, whitespace: true, message: '请输入展示名称' }]}>
                    <Input maxLength={100} placeholder="例如：业务查询"/>
                </Form.Item>
                <Form.Item name="description" label="能力说明">
                    <Input.TextArea rows={3} maxLength={1000} showCount placeholder="说明这项能力负责处理什么。"/>
                </Form.Item>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <Form.Item name="priority" label="优先级">
                        <InputNumber min={0} max={100000} style={{ width: '100%' }}/>
                    </Form.Item>
                    <Form.Item name="enabled" label="启用" valuePropName="checked">
                        <Switch/>
                    </Form.Item>
                </div>
                {selectedType === 'agent' && <Form.Item name="agent_id" label="引用 Agent" rules={[{ required: true, message: '请选择 Agent' }]} extra={agents.loading ? '正在加载 Agent…' : '发布应用时会固定 Agent 版本。'}>
                    <Select
                        showSearch
                        optionFilterProp="label"
                        placeholder="选择一个 Agent"
                        options={(agents.data || []).map(item => ({
                            value: item.id,
                            label: `${item.name}${item.published_version ? ` · v${item.published_version}` : ' · 未发布'}`,
                        }))}
                    />
                </Form.Item>}
                {selectedType === 'human' && <Form.Item name="queue" label="人工队列">
                    <Input placeholder="order-support"/>
                </Form.Item>}
                {selectedType && ['query', 'action', 'tracking'].includes(selectedType) && <Form.Item name="tool" label="工具标识" extra="只保存工具引用，工具的实现和授权在工具目录中维护。">
                    <Input placeholder="business_query"/>
                </Form.Item>}
            </Form>
        </Modal>
    </div>;
}

function executionStageLabel(stage: string) {
    return {
        deterministic: '确定性优先',
        direct: 'Direct',
        knowledge: '知识检索',
        query: '业务查询',
        action: '业务办理',
        tracking: '进度跟踪',
        agent: 'Agent 升级',
        human: '人工兜底',
    }[stage] || stage;
}

function executionStageHint(stage: string) {
    return {
        deterministic: '固定规则、固定应答与无需外部资源的处理',
        direct: '无需外部资源的固定回复',
        knowledge: '知识库、FAQ 与政策文档',
        query: '订单、物流、发票等只读接口',
        action: '需要确认的业务办理动作',
        tracking: '工单与服务处理进度',
        agent: '复杂解释和多步推理',
        human: '带上下文转人工',
    }[stage] || '应用默认执行阶段';
}

function executionStageTone(stage: string) {
    if (stage === 'human') return 'rose';
    if (stage === 'agent') return 'amber';
    if (stage === 'action' || stage === 'tracking') return 'green';
    return '';
}

interface PreviewFormState {
    message: string;
    entry: string;
    objectId: string;
    objectStatus: string;
    factsText: string;
    decision?: string;
    handler?: string;
}

const previewDefaults: PreviewFormState = {
    message: '',
    entry: 'natural_language',
    objectId: 'SIM-ORDER-10001',
    objectStatus: '运输中',
    factsText: '{\n  "order_status": "运输中",\n  "logistics_status": "深圳转运中心停留 2 天"\n}',
};

function PreviewTab({ application, scenes, debug, onDebug, onError }: {
    application: ServiceApplicationSummary;
    scenes: AppScenario[];
    debug: boolean;
    onDebug: (debug: boolean) => void;
    onError: (error: string) => void;
}) {
    const [scenarioKey, setScenarioKey] = useState(scenes[0]?.key || '');
    const [form, setForm] = useState<PreviewFormState>(previewDefaults);
    const [running, setRunning] = useState(false);
    const [error, setError] = useState('');
    const [trace, setTrace] = useState<SimulationTrace | null>(null);
    const scene = scenes.find(item => item.key === scenarioKey) || scenes[0];

    useEffect(() => {
        if (scene && !scenes.some(item => item.key === scenarioKey)) {
            setScenarioKey(scene.key);
        }
    }, [scene, scenarioKey, scenes]);

    useEffect(() => {
        if (!scene || form.message) return;
        setForm(current => ({
            ...current,
            message: scene.config.recommendations[0]?.message || `我想咨询${scene.name}`,
        }));
    }, [form.message, scene]);

    function selectScenario(nextKey: string) {
        const next = scenes.find(item => item.key === nextKey);
        setScenarioKey(nextKey);
        setTrace(null);
        setError('');
        onError('');
        if (next) {
            setForm(current => ({
                ...current,
                message: next.config.recommendations[0]?.message || `我想咨询${next.name}`,
                decision: undefined,
                handler: undefined,
                objectId: 'SIM-ORDER-10001',
            }));
        }
    }

    async function run(overrides: Partial<PreviewFormState> = {}) {
        const state = { ...form, ...overrides };
        if (!scene) {
            setError('当前应用还没有可模拟的服务场景');
            return;
        }
        if (!state.message.trim()) {
            setError('请输入要模拟的客户消息');
            return;
        }
        let facts: Record<string, unknown> = {};
        try {
            facts = state.factsText.trim() ? JSON.parse(state.factsText) as Record<string, unknown> : {};
        }
        catch {
            setError('模拟对象事实必须是合法 JSON');
            return;
        }
        setRunning(true);
        setError('');
        onError('');
        try {
            const result = await simulateServiceApplication(application.key, {
                message: state.message.trim(),
                entry: state.entry as never,
                scenario_key: scene.key,
                object: scene.config.object?.required
                    ? {
                        id: state.objectId.trim() || 'SIM-OBJECT',
                        type: scene.config.object.type,
                        status: state.objectStatus,
                        facts,
                    }
                    : null,
                selected_decision: state.decision || null,
                selected_handler: state.handler || null,
            });
            setTrace(result);
            toast.success('后台模拟运行已完成');
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '模拟运行失败');
        }
        finally {
            setRunning(false);
        }
    }

    function reset() {
        setForm({
            ...previewDefaults,
            message: scene?.config.recommendations[0]?.message || (scene ? `我想咨询${scene.name}` : ''),
        });
        setTrace(null);
        setError('');
        onError('');
    }

    const entryOptions = (scene?.config.entries || [])
        .filter(item => item.enabled !== false)
        .map(item => ({ value: item.type, label: item.label }));
    const decisionOptions = (scene?.config.decisions || []).map(item => ({ value: item.key, label: item.label }));
    const handlerOptions = (scene?.config.handlers || [])
        .filter(item => item.enabled !== false)
        .map(item => ({ value: item.key, label: `${item.label} · ${handlerTypeLabel(item.type)}` }));
    const objectRequired = !!scene?.config.object?.required;
    const resultContent = trace?.result.content || '等待服务端模拟结果';

    return <div className="sa-preview-tab">
        <div className="sa-preview-toolbar">
            <div>
                <span className="sa-eyebrow">APPLICATION SANDBOX</span>
                <h3>{debug ? '在服务端轨迹中调试应用' : '预览客户会看到什么'}</h3>
                <p>每次运行都会调用服务应用模拟接口，并返回真实场景、对象、事实、决策、承接与结果轨迹。</p>
            </div>
            <div className="sa-preview-toolbar-actions">
                {trace?.trace_id && <span className="sa-muted-note">trace {trace.trace_id}</span>}
                <div className="sa-mode-switch">
                    <button type="button" className={!debug ? 'is-active' : ''} onClick={() => onDebug(false)}>预览</button>
                    <button type="button" className={debug ? 'is-active' : ''} onClick={() => onDebug(true)}>调试</button>
                </div>
                <Button icon={<ReloadOutlined/>} onClick={reset}>重置</Button>
            </div>
        </div>
        <Alert error={error}/>

        <div className="sa-preview-layout">
            <section className="sa-preview-stage">
                <div className="sa-preview-stage-bar">
                    <span><i/> {debug ? 'SERVER DEBUG' : 'CUSTOMER PREVIEW'}</span>
                    <span><InfoCircleOutlined/> 所有对象、订单与结果均为模拟数据</span>
                </div>
                <div className="sa-preview-device">
                    <header className="sa-customer-head">
                        <span className="sa-customer-avatar"><RobotOutlined/></span>
                        <div><strong>{application.name}</strong><small><i/> 服务端模拟 · {scene?.name || '未选择场景'}</small></div>
                        <button type="button" aria-label="更多">···</button>
                    </header>
                    <div className="sa-customer-chat">
                        <span className="sa-chat-time">今天 · 模拟会话</span>
                        <ChatBubble role="assistant">{scene?.config.recommendations[0]?.label || `您好，这里是${application.name}。请告诉我您需要处理的问题。`}</ChatBubble>
                        {form.message && <ChatBubble role="user">{form.message}</ChatBubble>}
                        {trace?.object_ref && <OrderPicker objectRef={trace.object_ref}/>}
                        {trace && <ChatBubble role="assistant">
                            <div className="sa-result-inline">
                                <span><CheckCircleFilled/> {trace.result.status}</span>
                                <strong>{String(trace.handler?.label || trace.scenario_name)}</strong>
                                <p>{resultContent}</p>
                            </div>
                        </ChatBubble>}
                        {!!trace?.recommendations.length && <div className="sa-quick-prompts">
                            {trace.recommendations.slice(0, 4).map(item => <button type="button" key={item.key} onClick={() => void run({ message: item.message })}>{item.label}</button>)}
                        </div>}
                    </div>
                    <div className="sa-customer-composer">
                        <Input.TextArea
                            aria-label="模拟客户消息"
                            autoSize={{ minRows: 1, maxRows: 4 }}
                            value={form.message}
                            placeholder="输入要模拟的客户消息"
                            onChange={event => setForm(current => ({ ...current, message: event.target.value }))}
                            onPressEnter={event => {
                                if (!event.shiftKey) {
                                    event.preventDefault();
                                    void run();
                                }
                            }}
                        />
                        <Button type="primary" shape="circle" icon={<SendOutlined aria-hidden/>} loading={running} aria-label="运行模拟" onClick={() => void run()}/>
                    </div>
                </div>
            </section>

            <aside className="sa-preview-side">
                <section>
                    <span className="sa-eyebrow">SIMULATION INPUT</span>
                    <h4>模拟上下文</h4>
                    <label>服务场景
                        <Select value={scene?.key} onChange={selectScenario} options={scenes.map(item => ({ value: item.key, label: item.name }))}/>
                    </label>
                    <label>入口
                        <Select value={form.entry} onChange={entry => setForm(current => ({ ...current, entry }))} options={entryOptions.length ? entryOptions : [{ value: 'natural_language', label: '自然语言' }]}/>
                    </label>
                    {objectRequired && <>
                        <label>模拟对象 ID
                            <Input value={form.objectId} onChange={event => setForm(current => ({ ...current, objectId: event.target.value }))}/>
                        </label>
                        <label>模拟对象状态
                            <Input value={form.objectStatus} onChange={event => setForm(current => ({ ...current, objectStatus: event.target.value }))}/>
                        </label>
                        <label>对象事实 JSON
                            <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} value={form.factsText} onChange={event => setForm(current => ({ ...current, factsText: event.target.value }))}/>
                        </label>
                    </>}
                    <label>用户决策
                        <Select allowClear value={form.decision} onChange={decision => setForm(current => ({ ...current, decision }))} options={decisionOptions}/>
                    </label>
                    <label>指定承接
                        <Select allowClear value={form.handler} onChange={handler => setForm(current => ({ ...current, handler }))} options={handlerOptions}/>
                    </label>
                    <Button type="primary" block icon={<PlayCircleOutlined aria-hidden/>} loading={running} onClick={() => void run()}>运行服务端模拟</Button>
                </section>
                {debug
                    ? <DebugPanel trace={trace} scene={scene} application={application}/>
                    : <section className="sa-preview-note">
                        <InfoCircleOutlined/>
                        <div><strong>模拟不会产生真实副作用</strong><p>不会创建真实订单、工单或人工队列；结果和轨迹均来自后端确定性模拟器。</p><Button type="link" onClick={() => onDebug(true)}>查看服务端轨迹 →</Button></div>
                    </section>}
            </aside>
        </div>
    </div>;
}

function DebugPanel({ trace, scene, application }: {
    trace: SimulationTrace | null;
    scene?: AppScenario;
    application: ServiceApplicationSummary;
}) {
    return <section className="sa-debug-panel">
        <header className="sa-debug-head">
            <div><span className="sa-live-dot"/><strong>SERVER TRACE</strong><small>{trace?.trace_id || '等待运行'}</small></div>
            <span className="sa-debug-ok"><CheckCircleFilled/> {trace ? '已完成' : '未运行'}</span>
        </header>
        <div className="sa-debug-context">
            <span>APPLICATION<strong>{application.key}</strong></span>
            <span>SCENARIO<strong>{trace?.scenario_key || scene?.key || '—'}</strong></span>
            <span>RESULT<strong>{trace?.result.status || '—'}</strong></span>
        </div>
        <div className="sa-debug-timeline">
            {trace?.steps.map((step, index) => <DebugStep
                key={`${step.step}-${index}`}
                index={String(index + 1).padStart(2, '0')}
                title={simulationStepTitle(step)}
                detail={simulationStepDetail(step)}
                status={step.status}
                active={index === trace.steps.length - 1}
            />)}
            {!trace && <p className="sa-muted-note">运行模拟后展示后端返回的逐步轨迹。</p>}
        </div>
        {trace && <section className="sa-debug-section">
            <span className="sa-debug-label">FACTS</span>
            {trace.facts.length
                ? trace.facts.map(fact => <div key={fact.key} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '4px 0', fontSize: 7 }}>
                    <span>{fact.label}</span><strong>{formatTraceValue(fact.value)}</strong>
                </div>)
                : <p>本次未投影业务事实。</p>}
        </section>}
        {trace && <section className="sa-debug-section">
            <span className="sa-debug-label">DECISIONS</span>
            <div className="sa-decision-explain">
                {trace.decisions.length
                    ? trace.decisions.map(item => <span key={item.key} className={item.selected ? '' : 'muted'}>{item.selected ? <CheckCircleFilled/> : <ClockCircleOutlined/>}{item.label}</span>)
                    : <span className="muted">本次无需用户决策</span>}
            </div>
        </section>}
        {trace && <section className="sa-debug-section">
            <span className="sa-debug-label">HANDLER · {String(trace.handler?.type || '—')}</span>
            <pre>{JSON.stringify(trace.handler || {}, null, 2)}</pre>
        </section>}
        {trace && <section className="sa-debug-section">
            <span className="sa-debug-label">EXPLANATION</span>
            {trace.explanation.map((item, index) => <p key={`${item}-${index}`}>{index + 1}. {item}</p>)}
        </section>}
        <footer className="sa-debug-foot"><DatabaseOutlined/> 轨迹来自 /service-apps/{application.key}/simulate</footer>
    </section>;
}

function simulationStepTitle(step: SimulationStep) {
    return {
        scene: '服务场景',
        object: '业务对象',
        facts: '业务事实',
        decision: '用户决策',
        handler: '处理承接',
        result: '处理结果',
    }[step.step];
}

function simulationStepDetail(step: SimulationStep) {
    if (step.step === 'scene') return `${String(step.scenario_name || '')} · ${String(step.reason || step.status)}`;
    if (step.step === 'object') {
        const object = step.object as Record<string, unknown> | undefined;
        return step.status === 'needs_input' ? '等待选择业务对象' : `对象 ${String(object?.id || '已绑定')} · ${step.status}`;
    }
    if (step.step === 'facts') return `${String(step.count || 0)} 项事实 · ${step.status}`;
    if (step.step === 'decision') return step.selected_decision ? `已选择 ${String(step.selected_decision)}` : `${(step.available_keys as string[] | undefined)?.length || 0} 个可选决策`;
    if (step.step === 'handler') return `${String(step.handler_type || '未选择')} · ${String(step.handler_key || '—')}`;
    return String(step.content || step.status);
}

function ChatBubble({ role, children }: { role: 'assistant' | 'user'; children: ReactNode }) {
    return <div className={`sa-chat-row ${role}`}>
        {role === 'assistant' && <span className="sa-chat-avatar"><RobotOutlined/></span>}
        <div className="sa-chat-bubble">{children}</div>
    </div>;
}

function OrderPicker({ objectRef }: { objectRef: Record<string, unknown> }) {
    return <div className="sa-order-picker">
        <div>
            <span><ShoppingOutlined/></span>
            <div><strong>{String(objectRef.type || '业务对象')} {String(objectRef.id || '')}</strong><small>模拟对象 · {String(objectRef.status || '状态未知')}</small></div>
        </div>
        <span className="sa-muted-note">该对象仅用于本次服务端模拟，不代表真实客户数据。</span>
    </div>;
}

function DebugStep({ index, title, detail, status, active }: {
    index: string;
    title: string;
    detail: string;
    status: string;
    active: boolean;
}) {
    return <div className={`sa-debug-step done${active ? ' active' : ''}`}>
        <span className="sa-debug-index">{index}</span>
        <div><strong>{title}</strong><p>{detail}</p></div>
        <small>{status}</small>
    </div>;
}

interface ChannelFormValues {
    key: string;
    name: string;
    type: string;
    status: ApplicationChannelStatus;
}

function DeployTab({ application, versions, traces, admin, busy, onNavigate, onPublish, onRefresh, onSave }: {
    application: ServiceApplicationSummary;
    versions?: ServiceApplicationVersionPage | null;
    traces?: ServiceTracePage | null;
    admin: boolean;
    busy: boolean;
    onNavigate: (path: string) => void;
    onPublish: () => Promise<void>;
    onRefresh: () => void;
    onSave: (next: ServiceApplicationConfig, message?: string) => Promise<void>;
}) {
    const [form] = Form.useForm<ChannelFormValues>();
    const [modalOpen, setModalOpen] = useState(false);
    const [editingKey, setEditingKey] = useState<string | null>(null);
    const [actionBusy, setActionBusy] = useState(false);
    const [error, setError] = useState('');
    const channels = application.config.channels;
    const latestVersions = versions?.items.slice(0, 5) || [];

    function openCreate() {
        setEditingKey(null);
        form.resetFields();
        form.setFieldsValue({
            key: `channel-${channels.length + 1}`,
            name: '新客户触点',
            type: 'web',
            status: 'active',
        });
        setModalOpen(true);
    }

    function openEdit(channel: ApplicationChannel) {
        setEditingKey(channel.key);
        form.resetFields();
        form.setFieldsValue({
            key: channel.key,
            name: channel.name,
            type: channel.type || 'web',
            status: channel.status || 'active',
        });
        setModalOpen(true);
    }

    async function saveChannel() {
        const values = await form.validateFields();
        const duplicate = channels.some(item => item.key === values.key && item.key !== editingKey);
        if (duplicate) {
            form.setFields([{ name: 'key', errors: ['触点标识不能重复'] }]);
            return;
        }
        const previous = channels.find(item => item.key === editingKey);
        const channel: ApplicationChannel = {
            key: values.key.trim(),
            name: values.name.trim(),
            type: values.type.trim(),
            status: values.status,
            config: previous?.config || {},
        };
        const nextChannels = editingKey
            ? channels.map(item => item.key === editingKey ? channel : item)
            : [...channels, channel];
        await onSave(
            { ...application.config, channels: nextChannels },
            editingKey ? '客户触点已更新' : '客户触点已添加',
        );
        setModalOpen(false);
        setEditingKey(null);
        form.resetFields();
    }

    function removeChannel(channel: ApplicationChannel) {
        const next = {
            ...application.config,
            channels: channels.filter(item => item.key !== channel.key),
        };
        void onSave(next, '客户触点已移除').catch(() => undefined);
    }

    async function rollback(version: number) {
        setActionBusy(true);
        setError('');
        try {
            await rollbackServiceApplication(application.key, version, application.revision);
            onRefresh();
            toast.success(`已切换应用发布版本到 v${version}`);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '版本切换失败');
        }
        finally {
            setActionBusy(false);
        }
    }

    async function changeStatus(status: 'draft' | 'review' | 'offline') {
        setActionBusy(true);
        setError('');
        try {
            await setServiceApplicationStatus(application.key, status, application.revision);
            onRefresh();
            toast.success(status === 'review' ? '应用已标记为待发布' : status === 'offline' ? '应用已下线' : '应用已回到草稿');
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '应用状态更新失败');
        }
        finally {
            setActionBusy(false);
        }
    }

    return <div className="sa-deploy">
        <section className="sa-deploy-hero">
            <div>
                <span className="sa-eyebrow">DELIVERY & RELEASE</span>
                <h3>把应用草稿交付到客户触点</h3>
                <p>当前草稿 revision {application.revision}，{application.published_version ? `生产版本 v${application.published_version}` : '尚未发布'}。客户触点、发布版本与模拟轨迹都来自后端。</p>
                <div className="sa-hero-actions">
                    <Button type="primary" icon={<SendOutlined/>} loading={busy} disabled={!admin} onClick={() => void onPublish()}>发布新版本</Button>
                    <Button icon={<EyeOutlined/>} onClick={() => onNavigate(`/service-apps/${application.key}/experience`)}>打开统一体验</Button>
                </div>
            </div>
            <span className={`sa-app-state ${application.status === 'published' ? '' : 'waiting'}`}><i/>{applicationStatusLabel[application.status]}</span>
        </section>
        <Alert error={error}/>

        <section className="sa-environment-grid">
            <EnvironmentCard title="当前草稿" badge={`r${application.revision}`} value={application.has_unpublished_changes ? '有未发布修改' : '与发布一致'} detail={`${application.scenario_count} 个场景 · ${application.capability_count} 个能力`} tone="blue" action={<Button size="small" disabled={!admin || actionBusy} onClick={() => void changeStatus('review')}>标记待发布</Button>}/>
            <EnvironmentCard title="生产版本" badge={application.published_version ? `v${application.published_version}` : '未发布'} value={application.published_version ? updatedLabel(versions?.items.find(item => item.version === application.published_version)?.created_at) : '尚未发布'} detail={`${application.channel_count} 个客户触点`} tone={application.published_version ? 'green' : 'amber'} action={<Button size="small" disabled={!admin || actionBusy || application.status === 'offline'} onClick={() => void changeStatus('offline')}>下线应用</Button>}/>
            <EnvironmentCard title="模拟运行" badge="SERVER" value={String(traces?.items.length || 0)} detail="后端持久化的服务应用模拟轨迹" tone="amber" action={<Button size="small" onClick={onRefresh}>刷新轨迹</Button>}/>
        </section>

        <div className="sa-deploy-grid">
            <section className="sa-panel">
                <div className="sa-panel-head"><div><span className="sa-eyebrow">CUSTOMER CHANNELS</span><h3>客户触点</h3></div><Button type="primary" size="small" icon={<PlusOutlined/>} disabled={!admin || busy} onClick={openCreate}>添加触点</Button></div>
                {channels.map(channel => <ChannelRow key={channel.key} channel={channel} admin={admin} busy={busy} onEdit={() => openEdit(channel)} onRemove={() => removeChannel(channel)}/>)}
                {!channels.length && <p className="sa-muted-note">尚未配置客户触点。发布前请至少接入一个实际渠道。</p>}
            </section>

            <section className="sa-panel">
                <div className="sa-panel-head"><div><span className="sa-eyebrow">RELEASES</span><h3>发布版本</h3></div><Button type="link" onClick={onRefresh}>刷新</Button></div>
                {latestVersions.map(version => <ReleaseRow key={version.id} version={version} admin={admin} busy={actionBusy} onRollback={() => void rollback(version.version)}/>)}
                {!latestVersions.length && <p className="sa-muted-note">尚无应用发布版本。</p>}
                <div className="sa-release-foot"><span>{versions?.published_version ? `当前生产版本 v${versions.published_version}` : '当前没有生产版本'}</span><Button type="link" disabled={!admin || busy} onClick={() => void onPublish()}>发布新版本 →</Button></div>
            </section>
        </div>

        <section className="sa-panel" style={{ marginTop: 13 }}>
            <div className="sa-panel-head"><div><span className="sa-eyebrow">RECENT SIMULATIONS</span><h3>最近模拟轨迹</h3></div><span className="sa-muted-note">仅用于发布前验证，不代表真实客户会话</span></div>
            {(traces?.items || []).slice(0, 6).map(item => <ChangeRow key={item.id} icon={<BugOutlined/>} title={`${item.scenario_key} · ${item.outcome}`} detail={item.result_summary || '无结果摘要'} time={updatedLabel(item.created_at)} tone="violet"/>)}
            {!traces?.items.length && <p className="sa-muted-note">尚无模拟运行记录。</p>}
        </section>

        <Modal
            title={editingKey ? '编辑客户触点' : '添加客户触点'}
            open={modalOpen}
            okText={editingKey ? '保存触点' : '添加触点'}
            cancelText="取消"
            confirmLoading={busy}
            destroyOnHidden
            onCancel={() => {
                if (busy) return;
                setModalOpen(false);
                setEditingKey(null);
                form.resetFields();
            }}
            onOk={() => void saveChannel()}
        >
            <Form form={form} layout="vertical">
                <Form.Item name="name" label="触点名称" rules={[{ required: true, whitespace: true, message: '请输入触点名称' }]}>
                    <Input maxLength={100} placeholder="例如：官网帮助中心"/>
                </Form.Item>
                <Form.Item name="key" label="触点标识" rules={[
                    { required: true, whitespace: true, message: '请输入触点标识' },
                    { pattern: /^[a-z][a-z0-9_-]{0,63}$/, message: '请使用小写字母、数字、- 或 _' },
                ]}>
                    <Input disabled={!!editingKey} placeholder="web"/>
                </Form.Item>
                <Form.Item name="type" label="渠道类型" rules={[
                    { required: true, whitespace: true, message: '请输入渠道类型' },
                    { pattern: /^[a-z][a-z0-9-]{0,39}$/, message: '请使用小写字母、数字或 -' },
                ]}>
                    <Input placeholder="web / wecom / api / h5"/>
                </Form.Item>
                <Form.Item name="status" label="接入状态">
                    <Select options={[
                        { value: 'active', label: '正式启用' },
                        { value: 'canary', label: '灰度接入' },
                        { value: 'disabled', label: '已停用' },
                    ]}/>
                </Form.Item>
            </Form>
        </Modal>
    </div>;
}

function EnvironmentCard({ title, badge, value, detail, tone, action }: {
    title: string;
    badge: string;
    value: string;
    detail: string;
    tone: 'green' | 'blue' | 'amber';
    action?: ReactNode;
}) {
    return <article className={`sa-environment ${tone}`}>
        <div><span>{title}</span><b>{badge}</b></div>
        <strong>{value}</strong>
        <p>{detail}</p>
        {action}
    </article>;
}

function ChannelRow({ channel, admin, busy, onEdit, onRemove }: {
    channel: ApplicationChannel;
    admin: boolean;
    busy: boolean;
    onEdit: () => void;
    onRemove: () => void;
}) {
    return <div className="sa-channel-row">
        <span><GlobalOutlined/></span>
        <div><strong>{channel.name}</strong><small>{channel.key} · {channel.type || 'web'}</small></div>
        <b className={channel.status === 'active' ? '' : 'gray'}><i/>{channelStatusLabel[channel.status || 'active']}</b>
        <Button type="link" size="small" disabled={!admin || busy} onClick={onEdit}>编辑</Button>
        <Popconfirm title="移除这个客户触点？" okText="移除" cancelText="取消" disabled={!admin || busy} onConfirm={onRemove}>
            <Button type="link" danger size="small" icon={<DeleteOutlined/>} disabled={!admin || busy}/>
        </Popconfirm>
    </div>;
}

const channelStatusLabel: Record<ApplicationChannelStatus, string> = {
    active: '正式启用',
    canary: '灰度接入',
    disabled: '已停用',
};

function ReleaseRow({ version, admin, busy, onRollback }: {
    version: ServiceApplicationVersion;
    admin: boolean;
    busy: boolean;
    onRollback: () => void;
}) {
    return <div className="sa-release-line">
        <span>v{version.version}</span>
        <strong>{updatedLabel(version.created_at)} · {version.created_by}</strong>
        {version.published
            ? <span className="sa-app-published"><i/> 当前版本</span>
            : <Button type="link" size="small" disabled={!admin || busy} onClick={onRollback}>切换到此版本</Button>}
    </div>;
}

function CatalogMetric({ label, value, hint }: { label: string; value: string; hint: string }) {
    return <article><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>;
}

function StudioMetric({ label, value, hint }: { label: string; value: string; hint: string }) {
    return <article className="sa-metric"><span>{label}</span><strong>{value}</strong><small className="positive">{hint}</small></article>;
}

function CompositionCard({ icon, title, value, hint, tone }: {
    icon: ReactNode;
    title: string;
    value: string;
    hint: string;
    tone: 'violet' | 'blue' | 'green';
}) {
    return <article className={`sa-composition-card ${tone}`}>
        <span>{icon}</span>
        <div><small>{title}</small><strong>{value}</strong><p>{hint}</p></div>
    </article>;
}

function ChangeRow({ icon, title, detail, time, tone }: {
    icon: ReactNode;
    title: string;
    detail: string;
    time: string;
    tone: 'violet' | 'blue' | 'green';
}) {
    return <div className="sa-change-row">
        <span className={tone}>{icon}</span>
        <div><strong>{title}</strong><p>{detail}</p></div>
        <small>{time}</small>
    </div>;
}

function FlowStage({ number, title, hint, icon, tone, last = false, children }: {
    number: string;
    title: string;
    hint: string;
    icon: ReactNode;
    tone: string;
    last?: boolean;
    children: ReactNode;
}) {
    return <div className={`sa-flow-stage${last ? ' is-last' : ''}`}>
        <div className="sa-flow-marker"><span>{number}</span>{!last && <i/>}</div>
        <div className="sa-flow-content">
            <header><span className={`sa-flow-icon ${tone}`}>{icon}</span><div><strong>{title}</strong><small>{hint}</small></div><ArrowRightOutlined/></header>
            {children}
        </div>
    </div>;
}

function CapabilityBinding({ index, title, hint, icon, tone }: {
    index: string;
    title: string;
    hint: string;
    icon: ReactNode;
    tone: string;
}) {
    return <div className="sa-binding-row">
        <span className={`sa-binding-icon ${tone}`}>{icon}</span>
        <div><strong>{title}</strong><small>{hint}</small></div>
        <b>{index}</b>
    </div>;
}

function OrderStep({ index, title, hint, tone = '' }: {
    index: string;
    title: string;
    hint: string;
    tone?: string;
}) {
    return <div className={`sa-order-step ${tone}`}>
        <span>{index}</span>
        <div><strong>{title}</strong><small>{hint}</small></div>
    </div>;
}
