import {AuthBoundary} from '../features/auth/AuthBoundary';
import {AccountMenu} from '../features/auth/AccountMenu';
import { NotificationButton } from '../features/notifications/NotificationButton';
import { useTranslation } from 'react-i18next';
import { LanguageSelector } from '../i18n/LanguageSelector';
import { t } from '../i18n/index';
import { lazy, Suspense, useState, useRef, useEffect, type ReactNode } from 'react';
import { Layout, Button, Avatar, Tag, Spin, Grid } from 'antd';
import { DownOutlined, MenuFoldOutlined, MenuUnfoldOutlined, SearchOutlined } from '@ant-design/icons';
import { type CapabilityObservability, type PlatformModule, type Summary, setToken, token } from '../shared/api/client';
import { Alert, Badge, Empty, Field, Panel, Role, useResource } from '../shared/components/ui';
import type { UiExtensionManifest, UiNavigationItem } from '../contracts';
import { AgentsPage } from '../features/agents/AgentsPage';
import { ServiceAppsPage } from '../features/service-apps/ServiceAppsPage';
const KnowledgePage = lazy(() => import('../features/knowledge/KnowledgePage').then(module => ({ default: module.KnowledgePage })));
const SkillsPage = lazy(() => import('../features/skills/SkillsPage').then(module => ({ default: module.SkillsPage })));
import { ConversationsPage } from '../features/conversations/ConversationsPage';
import { ToolsPage } from '../features/tools/ToolsPage';
import { HandoffPage } from '../features/handoff/HandoffPage';
const TicketsPage = lazy(() => import('../features/tickets/TicketsPage').then(module => ({ default: module.TicketsPage })));
const MemoryPage = lazy(() => import('../features/memory/MemoryPage').then(module => ({ default: module.MemoryPage })));
import { QualityPage } from '../features/evaluation/QualityPage';
import { Metrics, ObservabilityPage } from '../features/observability/ObservabilityPage';
import { WorkbenchSso } from '../features/open-platform/SsoLogin';
import { StaffPanel } from '../features/handoff/StaffPanel';
import { ExtensionsPage } from '../features/extensions/ExtensionsPage';
import { SampleOperationsPage } from '../features/extensions/SampleOperationsPage';
import { useHashRouter, type ModelSection } from './hashRouter';
import { ModelsPage } from '../features/models/ModelsPage';
import { MembersPage, RolesPage, SecurityPage } from '../features/access-control/AccessControlPages';
import { ConsoleSidebar } from './ConsoleSidebar';
const OpenPlatformPage = lazy(() => import('../features/open-platform/OpenPlatformPage').then(module => ({ default: module.OpenPlatformPage })));
const sections = () => ([['overview', t("平台总览")], ['conversations', t("会话工作台")], ['service-apps', t("服务应用")], ['agents', t("Agent 管理")], ['models', t("模型网关")], ['knowledge', t("知识库")], ['tools', t("工具目录")], ['skills', t("Skill 能力库")], ['handoff', t("人工协同")], ['tickets', t("服务工单")], ['memory', t("客户管理")], ['open-platform', t("开放平台")], ['evaluation', t("质量大盘")], ['observability', t("运行与审计")], ['access', t("访问与策略")], ['members', t("成员管理")], ['roles', t("角色与权限")], ['security', t("会话与安全")], ['extensions', t("插件平台")]] as const);
type Page = ReturnType<typeof sections>[number][0] | 'approvals';

interface ResolvedUiNavigation extends UiNavigationItem {
    extensionId: string;
    feature: string;
}

const uiFeatureRenderers: Record<string, () => ReactNode> = {
    'approval/workbench': () => <ApprovalPage />,
    'extensions/sample-operations': () => <SampleOperationsPage />,
};
const ApprovalPage = lazy(() => import('../features/approval/ApprovalPage').then(module => ({ default: module.ApprovalPage })));
function Overview() {
    const summary = useResource<Summary>('/observability/summary', 5000);
    const modules = useResource<PlatformModule[]>('/modules');
    return <><Alert error={summary.error || modules.error}/><Metrics value={summary.data}/><section className="welcome"><p>{t("在一个工作空间中连接知识、配置 Agent，并协同处理客户问题。")}</p></section><div className="module-grid">{modules.data?.map((m, index) => <article key={m.id} className="module-card"><div className="row"><span className="mono muted">{String(index + 1).padStart(2, '0')}</span><Badge value={m.status}/></div><h3>{t(m.name)}</h3><p>{t(m.description)}</p></article>)}</div></>;
}
function Access({ onChange }: {
    onChange: () => void;
}) {
    const [value, setValue] = useState(token());
    const me = useResource<{
        role: string;
        tenant: string;
        actor: string;
    }>('/me');
    const policy = useResource<{
        model_backend: string;
        model_name: string;
        max_model_rounds: number;
        max_tool_calls: number;
        worker_concurrency: number;
        tool_allowed_hosts: string[];
    }>('/policy');
    return <div className="split"><Panel title={t("工作台访问凭据")}><Alert error={me.error || policy.error}/><WorkbenchSso onChange={onChange}/><form onSubmit={e => { e.preventDefault(); setToken(value.trim()); onChange(); }}><Field label={t("Bearer 服务令牌")}><input type="password" autoComplete="off" value={value} onChange={e => setValue(e.target.value)} placeholder={t("本地开发模式可留空")}/></Field><button>{t("应用凭据")}</button></form><p className="hint">{t("凭据仅保存在当前浏览器会话。模型密钥在后端配置，不通过此页面传入。")}</p>{me.data && <p>{t("租户：")}{me.data.tenant}{t(" \u00B7 当前角色：")}{me.data.role}</p>}</Panel><Panel title={t("权限与运行策略")}><table><thead><tr><th>{t("角色")}</th><th>{t("能力")}</th></tr></thead><tbody><tr><td>admin</td><td>{t("配置、发布、接入、评测及客服操作")}</td></tr><tr><td>operator</td><td>{t("会话、接管、工单确认与处理")}</td></tr><tr><td>viewer</td><td>{t("只读查看")}</td></tr></tbody></table>{policy.data && <dl><dt>{t("模型模式")}</dt><dd>{policy.data.model_backend} / {policy.data.model_name || t("演示模型")}</dd><dt>{t("单 Worker 并发")}</dt><dd>{policy.data.worker_concurrency}</dd><dt>{t("单次运行预算")}</dt><dd>{policy.data.max_model_rounds}{t(" 轮模型 / ")}{policy.data.max_tool_calls}{t(" 次工具")}</dd><dt>{t("可注册 API 主机")}</dt><dd>{policy.data.tool_allowed_hosts.join('、')}</dd></dl>}<p className="hint">{t("服务令牌提供基础角色划分；员工账号、SSO 和客户身份系统需要按实际部署接入。")}</p></Panel></div>;
}
function Shell({ reset }: {
    reset: () => void;
}) {
    const leaveGuard = useRef<((destination?: string) => boolean) | null>(null);
    const router = useHashRouter(destination => !leaveGuard.current || leaveGuard.current(destination));
    const page = router.path.split('?')[0].split('/')[1] as Page;
    const me = useResource<{
        role: string;
        tenant: string;
        actor: string;
        name?: string | null;
        permissions: string[];
    }>('/me');
    const uiExtensions = useResource<UiExtensionManifest[]>('/extensions/ui');
    const capabilities = useResource<CapabilityObservability>('/extensions/capabilities', 5000);
    const screens = Grid.useBreakpoint();
    const mobile = !screens.lg;
    const [collapsed, setCollapsed] = useState(() => window.innerWidth < 992);
    const [agentWorkspace, setAgentWorkspace] = useState(false);
    const previousCollapsed = useRef(false);
    function navigate(next: Page, entry: 'models' | 'profiles' = 'models') {
        router.navigate(next === 'models' ? `/models/${entry}` : `/${next}`);
    }
    useEffect(() => {
        if (page !== 'agents') {
            if (page !== 'skills') leaveGuard.current = null;
            setAgentWorkspace(false);
            if (window.innerWidth < 992) setCollapsed(true);
        }
    }, [page]);
    function workspaceChanged(active: boolean) {
        setAgentWorkspace(active);
        if (active) {
            previousCollapsed.current = collapsed;
            setCollapsed(true);
        }
        else
            setCollapsed(window.innerWidth < 992 || previousCollapsed.current);
    }
    const role = me.data?.role || 'viewer';
    // Header label: the account's display name. `actor` is a machine identity
    // such as "enterprise:<uuid>" and `tenant` is the tenant slug, so they are
    // only fallbacks for principals without a user record (service tokens).
    const accountLabel = me.data?.name || me.data?.actor || me.data?.tenant || t("未连接");
    const hasPermission = (permissions: readonly string[] | undefined) =>
        !permissions?.some(permission => !(me.data?.permissions || []).includes(permission));
    const hasCapability = (capability: string | undefined) => {
        if (!capability) return true;
        return Boolean(capabilities.data?.capabilities?.items?.some(item =>
            item.capability_id === capability && item.status !== 'stopped',
        ));
    };
    const uiExtensionManifests = Array.isArray(uiExtensions.data) ? uiExtensions.data : [];
    const extensionNavigation: ResolvedUiNavigation[] = uiExtensionManifests.flatMap(manifest => (manifest.navigation || []).flatMap(item => {
        const route = manifest.routes.find(candidate => candidate.path === item.path);
        if (!route || !uiFeatureRenderers[route.feature]) return [];
        if (!hasPermission(item.requiredPermissions) || !hasPermission(route.requiredPermissions)) return [];
        if (!hasCapability(item.requiredCapability) || !hasCapability(route.requiredCapability)) return [];
        return [{ ...item, extensionId: manifest.extensionId, feature: route.feature }];
    }));
    const extensionLabels = new Map(extensionNavigation.map(item => [item.id, t(item.labelKey)]));
    const labelFor = (id: Page) => sections().find(item => item[0] === id)?.[1] || extensionLabels.get(id) || id;
    const extensionGroups = Array.from(extensionNavigation.reduce((groups, item) => {
        const ids = groups.get(item.group) || [];
        ids.push(item.id as Page);
        groups.set(item.group, ids);
        return groups;
    }, new Map<string, Page[]>())).map(([group, ids]) => ({
        title: group === 'approval' ? t('审批工作') : group,
        ids,
    }));
  const pages: Partial<Record<Page, ReactNode>> = { 'service-apps': <ServiceAppsPage route={router.path} onNavigate={router.navigate}/>, 'open-platform': <OpenPlatformPage route={router.path} onNavigate={router.navigate}/>, models: <ModelsPage routeSection={router.path.split('/')[2] as ModelSection} onNavigate={section => router.navigate(`/models/${section}`)}/>, overview: <Overview />, conversations: <ConversationsPage route={router.path} onNavigate={router.navigate} />, agents: <AgentsPage route={router.path} onNavigate={router.navigate} onConfigureModels={() => navigate('models', 'profiles')} onWorkspaceChange={workspaceChanged} onGuardChange={guard => { leaveGuard.current = guard; }}/>, knowledge: <KnowledgePage />, skills: <SkillsPage route={router.path} onNavigate={router.navigate} onGuardChange={guard => { leaveGuard.current = guard; }} />, tools: <ToolsPage route={router.path} onNavigate={router.navigate}/>, handoff: <HandoffPage />, tickets: <TicketsPage />, memory: <MemoryPage route={router.path} onNavigate={router.navigate} />, evaluation: <QualityPage onNavigate={router.navigate} />, observability: <ObservabilityPage />, access: <><Access onChange={reset}/><StaffPanel /></>, members: <MembersPage />, roles: <RolesPage />, security: <SecurityPage />, extensions: <ExtensionsPage /> };
    const extensionPage = extensionNavigation.find(item => item.id === page);
    const pageContent = extensionPage ? uiFeatureRenderers[extensionPage.feature]?.() : pages[page];
    const serviceAppsShell = page === 'service-apps';
    const serviceApplicationWorkspace = page === 'service-apps' && /^\/service-apps\/(?!standards(?:\/|$))[a-z0-9-]+(?:\/(?:overview|agent|experience|skills|rules|conversations|release))?$/.test(router.path);
    return <Role.Provider value={role}><Layout className={`console-layout ${page === 'agents' ? 'agents-shell' : page === 'tools' ? 'tools-shell' : page === 'open-platform' ? 'open-platform-shell' : ''} ${page === 'skills' ? 'skills-shell' : ''} ${serviceAppsShell ? 'service-apps-shell' : ''} ${serviceApplicationWorkspace ? 'service-app-workspace' : ''} ${agentWorkspace ? 'agent-focus' : ''}`}>
    {mobile && !collapsed && !agentWorkspace && <button type="button" className="console-sidebar-mask" aria-label={t("收起导航")} onClick={() => setCollapsed(true)}/>}
    <Layout.Sider className="console-sider" theme="dark" width={228} collapsedWidth={mobile || agentWorkspace ? 0 : 72} collapsed={collapsed} breakpoint="lg" onBreakpoint={setCollapsed} trigger={null}>
      <ConsoleSidebar
        page={page}
        role={role}
        collapsed={collapsed}
        mobile={mobile}
        extensionGroups={extensionGroups}
        labelFor={id => labelFor(id as Page)}
        onNavigate={id => navigate(id as Page)}
        onCollapsedChange={setCollapsed}
      />
    </Layout.Sider><Layout className="console-body"><Layout.Header className="console-header">
    {page === 'service-apps'
      ? <Button className="service-apps-nav-toggle" type="text" aria-label={collapsed ? t("展开导航") : t("收起导航")} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)}/>
      : page === 'skills'
        ? <div className="skills-header-leading"><Button type="text" aria-label={collapsed ? t("展开导航") : t("收起导航")} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)}/><div className="skills-global-search"><SearchOutlined /><span>{t("搜索功能、智能体、任务…")}</span><kbd>Ctrl + K</kbd></div></div>
        : <div className="console-heading"><Button type="text" aria-label={collapsed ? t("展开导航") : t("收起导航")} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)}/><div><h1>{labelFor(page)}</h1><p className="page-description">{page === 'memory' ? t("查看客户档案与记忆，处理待确认的写入。") : page === 'tickets' ? t("跟进每一个问题，记录每一次处理。") : page === 'overview' ? t("了解服务运行情况，管理你的客服工作空间。") : page === 'models' ? t("统一接入模型服务，管理模型能力与发布方案。") : page === 'evaluation' ? t("跨 Agent 查看评测通过率、待复核队列与回归。") : page === 'members' ? t("管理组织成员、角色和访问状态。") : page === 'roles' ? t("查看固定角色的权限范围。") : page === 'security' ? t("管理当前账号的登录会话和访问安全。") : page === 'extensions' ? t("管理插件生命周期、配置版本和运行状态。") : page === 'approvals' ? t("处理待审批请求，查看决策记录。") : t("管理服务配置与协作，让客户问题得到持续跟进。")}</p></div></div>}
    <div className="console-header-actions">{page !== 'skills' && <LanguageSelector />}<NotificationButton onNavigate={path => router.navigate(path)} /><AccountMenu access={() => navigate('access')}>{page === 'skills'
      ? <Button type="text" className="skills-account" aria-label={t("账户菜单")}><Avatar size={44} src="/assets/skills/header-avatar.png" /><span>{accountLabel}</span><DownOutlined /></Button>
      : <Button type="text" aria-label={t("账户菜单")}><Avatar size="small">{role[0].toUpperCase()}</Avatar>{accountLabel}<Tag>{role}</Tag></Button>}</AccountMenu></div>
  </Layout.Header>
    <Layout.Content className="console-content">{me.error && page !== 'access' && <div role="alert" className="alert error">{t("无法连接后端或读取权限：")}{me.error} <Button onClick={() => me.refresh()}>{t("重试")}</Button> <Button onClick={() => navigate('access')}>{t("设置凭据")}</Button></div>}{uiExtensions.error && <div role="alert" className="alert error">{t("无法加载 UI 扩展：")}{uiExtensions.error}</div>}{capabilities.error && <div role="alert" className="alert error">{t("无法加载扩展能力状态：")}{capabilities.error}</div>}<div className={`page module-page module-${page}`} key={page}><Suspense fallback={<Spin tip={t("正在加载页面")}><div style={{ minHeight: 160 }}/></Spin>}>{pageContent || <Empty>{t("扩展页面不可用")}</Empty>}</Suspense></div></Layout.Content>
  </Layout></Layout></Role.Provider>;
}
export function App() { useTranslation(); const [revision, setRevision] = useState(0); return <AuthBoundary key={revision}><Shell reset={() => setRevision(v => v + 1)}/></AuthBoundary>; }
