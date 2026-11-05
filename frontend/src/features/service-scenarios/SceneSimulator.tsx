import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, Drawer, Input, Select, Spin } from 'antd';
import {
    CheckOutlined,
    ClockCircleOutlined,
    CustomerServiceOutlined,
    FileSearchOutlined,
    FileTextOutlined,
    HistoryOutlined,
    InfoCircleOutlined,
    MessageOutlined,
    PlayCircleOutlined,
    ReloadOutlined,
    RobotOutlined,
    SendOutlined,
    ShoppingOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import type {
    ServiceApplicationSummary,
    ServiceScenarioSummary,
    ServiceScenarioVersionPage,
    ServiceTraceItem,
    ServiceTracePage,
    SimulationStep,
    SimulationTrace,
} from '../../shared/api/client';
import { rollbackServiceScenario, simulateServiceApplication } from '../../shared/api/client';
import { Alert, useAccess, useResource, toast } from '../../shared/components/ui';
import { demoText as demo } from './data';
import { ScenarioTabs, ScenarioTopline } from './ScenarioChrome';
import { scenarioBasePath, scenarioKeyFromPath } from './routes';
import { formatTraceValue, handlerTypeLabel } from './scenarioConfig';
import './service-scenarios.css';

interface Props {
    route: string;
    onNavigate: (path: string) => void;
    onMetaChange?: (meta: { path: string; title: string; description?: string }) => void;
}

function appKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/([a-z0-9-]+)/)?.[1] || '';
}

function stepTitle(step: SimulationStep) {
    return {
        scene: '服务场景',
        object: '业务对象',
        facts: '业务事实',
        decision: '用户决策',
        handler: '处理承接',
        result: '处理结果',
    }[step.step];
}

function stepIcon(step: SimulationStep) {
    if (step.step === 'scene') return <FileSearchOutlined/>;
    if (step.step === 'object') return <ShoppingOutlined/>;
    if (step.step === 'facts') return <FileTextOutlined/>;
    if (step.step === 'decision') return <CheckOutlined/>;
    if (step.step === 'result') return <ThunderboltOutlined/>;
    return <CustomerServiceOutlined/>;
}

function stepDetail(step: SimulationStep): string {
    if (step.step === 'scene') return `${String(step.scenario_name || '')} · ${String(step.reason || step.status)}`;
    if (step.step === 'object') return step.status === 'needs_input' ? '等待选择业务对象' : `对象 ${String((step.object as Record<string, unknown> | undefined)?.id || '已绑定')} · ${step.status}`;
    if (step.step === 'facts') return `${String(step.count || 0)} 项事实 · ${step.status}`;
    if (step.step === 'decision') return step.selected_decision ? `已选择 ${String(step.selected_decision)}` : `${(step.available_keys as string[] | undefined)?.length || 0} 个可选决策`;
    if (step.step === 'handler') return `${String(step.handler_type || '未选择')} · ${String(step.handler_key || '—')}`;
    return String(step.content || step.status);
}

export function SceneSimulator({ route, onNavigate, onMetaChange }: Props) {
    const { admin } = useAccess();
    const appKey = appKeyFromRoute(route);
    const scenarioKey = scenarioKeyFromPath(route);
    const application = useResource<ServiceApplicationSummary>(`/service-apps/${appKey}`);
    const scenario = useResource<ServiceScenarioSummary>(`/service-scenarios/${scenarioKey}`);
    const versions = useResource<ServiceScenarioVersionPage>(`/service-scenarios/${scenarioKey}/versions`);
    const traces = useResource<ServiceTracePage>(`/service-apps/${appKey}/traces?limit=20`);
    const [message, setMessage] = useState('');
    const [entry, setEntry] = useState('natural_language');
    const [objectId, setObjectId] = useState('SIM-ORDER-20261031');
    const [objectStatus, setObjectStatus] = useState('运输中');
    const [factsText, setFactsText] = useState('{\n  "status": "运输中",\n  "logistics_status": "深圳转运中心停留 2 天"\n}');
    const [selectedDecision, setSelectedDecision] = useState<string | undefined>();
    const [selectedHandler, setSelectedHandler] = useState<string | undefined>();
    const [running, setRunning] = useState(false);
    const [error, setError] = useState('');
    const [trace, setTrace] = useState<SimulationTrace | null>(null);
    const [historyOpen, setHistoryOpen] = useState(false);
    const config = scenario.data?.config;
    const objectRequired = config?.object?.required;
    const base = scenarioBasePath(route);

    useEffect(() => {
        if (!scenario.data) return;
        onMetaChange?.({
            path: route,
            title: '场景模拟器',
            description: `验证「${scenario.data.name}」的场景识别、对象绑定、业务事实、用户决策和处理承接。`,
        });
        if (!message) {
            setMessage(scenario.data.config.recommendations[0]?.message || `我想咨询${scenario.data.name}`);
        }
    }, [message, onMetaChange, route, scenario.data]);

    const entryOptions = useMemo(() => (config?.entries || [])
        .filter(item => item.enabled !== false)
        .map(item => ({ value: item.type, label: item.label })), [config?.entries]);

    async function run(overrides: { message?: string; handler?: string; decision?: string } = {}) {
        const text = (overrides.message ?? message).trim();
        if (!text) {
            setError('请输入要模拟的客户消息');
            return;
        }
        let facts: Record<string, unknown> = {};
        try {
            facts = factsText.trim() ? JSON.parse(factsText) as Record<string, unknown> : {};
        }
        catch {
            setError('模拟对象事实必须是合法 JSON');
            return;
        }
        setRunning(true);
        setError('');
        try {
            const result = await simulateServiceApplication(appKey, {
                message: text,
                entry: entry as never,
                scenario_key: scenarioKey,
                object: objectRequired && objectId.trim()
                    ? {
                        id: objectId.trim(),
                        type: config?.object?.type || 'order',
                        status: objectStatus,
                        facts,
                    }
                    : null,
                selected_decision: overrides.decision ?? selectedDecision ?? null,
                selected_handler: overrides.handler ?? selectedHandler ?? null,
            });
            setTrace(result);
            traces.refresh();
            toast.success('模拟运行已完成');
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '模拟运行失败');
        }
        finally {
            setRunning(false);
        }
    }

    async function rollback(version: number) {
        if (!scenario.data) return;
        try {
            await rollbackServiceScenario(scenarioKey, version, scenario.data.revision);
            scenario.refresh();
            versions.refresh();
            toast.success(`已切换场景发布版本到 v${version}`);
            setHistoryOpen(false);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '回滚失败');
        }
    }

    if (scenario.loading && !scenario.data) return <div className="scene-simulator"><Spin/></div>;
    if (!scenario.data) return <div className="scene-simulator">
        <Alert error={scenario.error || '服务场景不存在'}/>
        <Button onClick={() => onNavigate(`/service-apps/${appKey}`)}>返回服务应用</Button>
    </div>;

    return <div className="scene-simulator">
        <ScenarioTopline
            route={route}
            onNavigate={onNavigate}
            actions={<>
                <Button icon={<HistoryOutlined/>} onClick={() => setHistoryOpen(true)}>{demo('查看发布记录')}</Button>
                <Button type="primary" onClick={() => onNavigate(base)}>{demo('进入编辑')}</Button>
            </>}
        />
        <ScenarioTabs route={route} onNavigate={onNavigate}/>
        <Alert error={error || application.error || scenario.error}/>

        <div className="simulator-intro">
            <div><span className="scenario-eyebrow">SANDBOX · SERVER TRACE</span><h2>{demo('模拟一次真实咨询')}</h2><p>{demo('每次运行都会调用服务端模拟器并持久化运行轨迹，便于复核。')}</p></div>
            <span><ClockCircleOutlined/> {trace?.trace_id ? `trace ${trace.trace_id.slice(0, 8)}` : '等待运行'}</span>
        </div>

        <div className="simulator-grid">
            <section className="simulator-panel simulator-input">
                <PanelHead eyebrow="01 · INPUT" title={demo('模拟输入')} extra="Server API"/>
                <label className="scene-field">
                    <span>{demo('用户消息')}</span>
                    <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} value={message} onChange={event => setMessage(event.target.value)}/>
                </label>
                <div className="scene-form-grid">
                    <label className="scene-field">
                        <span>{demo('入口')}</span>
                        <Select value={entry} onChange={setEntry} options={entryOptions.length ? entryOptions : [{ value: 'natural_language', label: '自然语言' }]}/>
                    </label>
                    <label className="scene-field">
                        <span>用户决策</span>
                        <Select allowClear value={selectedDecision} onChange={setSelectedDecision} options={(config?.decisions || []).map(item => ({ value: item.key, label: item.label }))}/>
                    </label>
                </div>
                {objectRequired && <>
                    <span className="simulator-field-label">模拟业务对象</span>
                    <div className="scene-form-grid">
                        <label className="scene-field">
                            <span>对象 ID</span>
                            <Input value={objectId} onChange={event => setObjectId(event.target.value)}/>
                        </label>
                        <label className="scene-field">
                            <span>对象状态</span>
                            <Input value={objectStatus} onChange={event => setObjectStatus(event.target.value)}/>
                        </label>
                    </div>
                    <label className="scene-field">
                        <span>对象事实 JSON</span>
                        <Input.TextArea autoSize={{ minRows: 3, maxRows: 7 }} value={factsText} onChange={event => setFactsText(event.target.value)}/>
                    </label>
                </>}
                <label className="scene-field">
                    <span>指定承接（可选）</span>
                    <Select allowClear value={selectedHandler} onChange={setSelectedHandler} options={(config?.handlers || []).map(item => ({ value: item.key, label: `${item.label} · ${handlerTypeLabel(item.type)}` }))}/>
                </label>
                <div className="simulator-input-footer">
                    <Button type="primary" size="large" icon={<PlayCircleOutlined aria-hidden/>} loading={running} onClick={() => void run()}>{demo('运行模拟')}</Button>
                    <Button icon={<ReloadOutlined aria-hidden/>} onClick={() => {
                        setMessage(config?.recommendations[0]?.message || `我想咨询${scenario.data?.name || ''}`);
                        setTrace(null);
                        setError('');
                    }}>{demo('重置')}</Button>
                </div>
                <p className="simulator-note"><InfoCircleOutlined/> {demo('模拟不会创建真实订单、工单或人工队列；结果来自后端确定性模拟器。')}</p>
            </section>

            <section className="simulator-panel simulator-runtime">
                <PanelHead eyebrow="02 · RUNTIME" title={demo('处理路径')} extra={trace?.result.status || '未运行'}/>
                {!trace && <div className="simulator-empty"><FileSearchOutlined/><p>运行后在这里展示服务端返回的逐步轨迹。</p></div>}
                {trace && <div className="simulator-timeline">
                    {trace.steps.map((step, index) => <RuntimeStep
                        key={`${step.step}-${index}`}
                        index={String(index + 1).padStart(2, '0')}
                        title={stepTitle(step)}
                        status={step.status}
                        icon={stepIcon(step)}
                        active={index === trace.steps.length - 1}
                        last={index === trace.steps.length - 1}
                    >
                        <strong>{stepDetail(step)}</strong>
                        {step.step === 'facts' && trace.facts.length > 0 && <div className="simulator-fact-list">
                            {trace.facts.map(fact => <span key={fact.key}>{fact.label}：{formatTraceValue(fact.value)}</span>)}
                        </div>}
                        {step.step === 'decision' && trace.decisions.length > 0 && <p>{trace.decisions.map(item => `${item.label}${item.selected ? '（已选）' : ''}`).join(' · ')}</p>}
                    </RuntimeStep>)}
                </div>}
            </section>

            <aside className="simulator-result-column">
                <section className="simulator-panel simulator-result">
                    <PanelHead eyebrow="03 · RESULT" title={demo('客户可见结果')} extra={trace ? 'SERVER' : 'WAITING'} live={!!trace}/>
                    <div className="simulator-phone">
                        <div className="simulator-phone-head"><span>‹</span><div><strong>{application.data?.name || appKey}</strong><small>{scenario.data.name}</small></div><b>AI</b></div>
                        <div className="simulator-phone-body">
                            <div className="simulator-user-bubble">{message}</div>
                            {trace ? <div className="simulator-agent-card">
                                <span><RobotOutlined/></span>
                                <div>
                                    <strong>{trace.handler?.label ? String(trace.handler.label) : trace.scenario_name}</strong>
                                    <p>{trace.result.content}</p>
                                    <div>
                                        <Button size="small" onClick={() => void run({ message: '转人工' })} icon={<CustomerServiceOutlined/>}>{demo('转人工')}</Button>
                                        <Button size="small" type="primary" onClick={() => void run()}>{demo('再次模拟')}</Button>
                                    </div>
                                </div>
                            </div> : <div className="simulator-agent-card muted"><span><RobotOutlined/></span><div><strong>等待服务端返回</strong><p>运行模拟后，此处直接展示后端结果，不再使用前端预置答案。</p></div></div>}
                        </div>
                        <div className="simulator-phone-input">{trace?.trace_id ? `trace ${trace.trace_id}` : '继续输入…'} <b>→</b></div>
                    </div>
                </section>

                <section className="simulator-panel simulator-why">
                    <PanelHead eyebrow="WHY" title={demo('为什么这样处理')} extra={trace?.explanation.length ? `${trace.explanation.length} 条依据` : '⋯'}/>
                    {trace?.explanation.map((item, index) => <WhyLine key={`${item}-${index}`} icon={index === 0 ? <MessageOutlined/> : index === 1 ? <ShoppingOutlined/> : <FileSearchOutlined/>} title={item} description="来自服务端模拟轨迹"/>)}
                    {!trace && <p className="simulator-empty-copy">运行后展示后端的路由、对象、事实、决策和承接解释。</p>}
                    <Button block type="text" icon={<HistoryOutlined/>} onClick={() => setHistoryOpen(true)}>{demo('查看发布与运行记录')} →</Button>
                </section>
            </aside>
        </div>

        <Drawer title="场景发布记录" open={historyOpen} onClose={() => setHistoryOpen(false)} width={560}>
            <Alert error={versions.error || traces.error}/>
            <h3>发布版本</h3>
            {!versions.data?.items.length && <p className="simulator-empty-copy">该场景尚未发布。</p>}
            {versions.data?.items.map(version => <div className="simulator-history-row" key={version.id}>
                <div><strong>v{version.version}</strong><small>{new Date(version.created_at).toLocaleString('zh-CN')} · {version.created_by}</small></div>
                {version.published && <span className="simulator-status-ok"><CheckOutlined/> 当前版本</span>}
                {!version.published && admin && <Button size="small" onClick={() => void rollback(version.version)}>切换到此版本</Button>}
            </div>)}
            <h3>最近运行轨迹</h3>
            {traces.data?.items.map(item => <TraceHistoryRow key={item.id} item={item} onOpen={() => {
                setTrace(item.trace);
                setHistoryOpen(false);
            }}/>)}
        </Drawer>
    </div>;
}

function TraceHistoryRow({ item, onOpen }: { item: ServiceTraceItem; onOpen: () => void }) {
    return <button type="button" className="simulator-history-row is-button" onClick={onOpen}>
        <div><strong>{item.scenario_key} · {item.outcome}</strong><small>{new Date(item.created_at).toLocaleString('zh-CN')} · {item.result_summary || '无结果摘要'}</small></div>
        <SendOutlined/>
    </button>;
}

function PanelHead({ eyebrow, title, extra, live = false }: { eyebrow: string; title: string; extra: string; live?: boolean }) {
    return <header className="simulator-panel-head">
        <div><span className="scenario-eyebrow">{eyebrow}</span><h2>{title}</h2></div>
        <span className={live ? 'is-live' : ''}>{extra}</span>
    </header>;
}

function RuntimeStep({ index, title, status, icon, active = false, last = false, children }: {
    index: string;
    title: string;
    status: string;
    icon: ReactNode;
    active?: boolean;
    last?: boolean;
    children: ReactNode;
}) {
    return <article className={`runtime-step${active ? ' is-active' : ''}${last ? ' is-last' : ''}`}>
        <span className="runtime-check"><CheckOutlined/></span>
        <div className="runtime-card">
            <header><span>{icon}</span><div><small>{index} · {title}</small><strong>{status}</strong></div></header>
            {children}
        </div>
    </article>;
}

function WhyLine({ icon, title, description }: { icon: ReactNode; title: string; description: string }) {
    return <div className="why-line">
        <span>{icon}</span>
        <div><strong>{title}</strong><small>{description}</small></div>
    </div>;
}
