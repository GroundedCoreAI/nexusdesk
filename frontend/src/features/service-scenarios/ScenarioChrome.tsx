import { Button, Spin } from 'antd';
import { ArrowLeftOutlined, RobotOutlined } from '@ant-design/icons';
import type { ServiceApplicationSummary, ServiceScenarioSummary } from '../../shared/api/client';
import { useResource } from '../../shared/components/ui';
import { demoText as demo } from './data';
import { appBasePath, scenarioBasePath, scenarioKeyFromPath } from './routes';
import { scenarioStatusLabel, scenarioTone } from './scenarioConfig';

interface ScenarioChromeProps {
    route: string;
    onNavigate: (path: string) => void;
}

function activeView(route: string) {
    if (route.endsWith('/simulator')) return 'simulator';
    if (route.endsWith('/customer')) return 'customer';
    return 'config';
}

function appKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/([a-z0-9-]+)/)?.[1] || '';
}

function updatedLabel(value?: string) {
    if (!value) return '配置已从服务端加载';
    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? '配置已从服务端加载'
        : `最近保存 ${date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
}

export function ScenarioSubnav({ route, onNavigate }: ScenarioChromeProps) {
    const active = activeView(route);
    const base = scenarioBasePath(route);
    const views = [
        { key: 'config', label: '场景配置', path: base },
        { key: 'simulator', label: '模拟与决策', path: `${base}/simulator` },
        { key: 'customer', label: '客户端预览', path: `${base}/customer` },
    ] as const;
    return <nav className="scenario-subnav" aria-label={demo('场景视图')}>
        {views.map(view => <button
            type="button"
            key={view.key}
            className={active === view.key ? 'is-active' : ''}
            aria-current={active === view.key ? 'page' : undefined}
            onClick={() => onNavigate(view.path)}
        >{demo(view.label)}</button>)}
    </nav>;
}

export function ScenarioTopline({ route, onNavigate, actions }: ScenarioChromeProps & { actions?: React.ReactNode }) {
    const appKey = appKeyFromRoute(route);
    const scenarioKey = scenarioKeyFromPath(route);
    const application = useResource<ServiceApplicationSummary>(appKey ? `/service-apps/${appKey}` : null);
    const scenario = useResource<ServiceScenarioSummary>(scenarioKey ? `/service-scenarios/${scenarioKey}` : null);
    const config = scenario.data?.config;
    const agentHandler = config?.handlers.find(handler => handler.type === 'agent' && handler.enabled !== false);

    return <header className="scenario-topline">
        <div className="scenario-topline-main">
            <Button type="text" icon={<ArrowLeftOutlined aria-hidden/>} onClick={() => onNavigate(appBasePath(route))}>
                {demo('返回服务应用')}
            </Button>
            <div className="scenario-breadcrumb">
                <span>{demo('服务应用')}</span><i>/</i>
                <span>{application.data?.name || (application.loading ? <Spin size="small"/> : appKey)}</span><i>/</i>
                <strong>{scenario.data?.name || (scenario.loading ? <Spin size="small"/> : scenarioKey)}</strong>
            </div>
            {scenario.data && <span className={`scenario-pill ${scenarioTone(scenario.data.status)}`}>
                <i/> {scenarioStatusLabel(scenario.data.status)}
                {scenario.data.published_version ? ` · v${scenario.data.published_version}` : ' · 未发布'}
            </span>}
            {agentHandler && <span className="scenario-agent-pill"><RobotOutlined/> Agent · {agentHandler.agent_name || '已引用'}
                {agentHandler.agent_version ? ` v${agentHandler.agent_version}` : ''}
            </span>}
        </div>
        <div className="scenario-top-actions">{actions}</div>
    </header>;
}

export function ScenarioTabs({ route, onNavigate }: ScenarioChromeProps) {
    const scenarioKey = scenarioKeyFromPath(route);
    const scenario = useResource<ServiceScenarioSummary>(scenarioKey ? `/service-scenarios/${scenarioKey}` : null);
    return <div className="scenario-tabs-row">
        <ScenarioSubnav route={route} onNavigate={onNavigate}/>
        <span className="scenario-save-state"><i/> {updatedLabel(scenario.data?.updated_at)}</span>
    </div>;
}
