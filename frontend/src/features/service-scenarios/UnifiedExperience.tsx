import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button, Drawer, Input, Spin } from 'antd';
import {
    ArrowLeftOutlined,
    BookOutlined,
    CheckCircleFilled,
    CheckOutlined,
    ClockCircleOutlined,
    CustomerServiceOutlined,
    FileSearchOutlined,
    FileTextOutlined,
    InboxOutlined,
    LoadingOutlined,
    MessageOutlined,
    ReloadOutlined,
    RobotOutlined,
    SafetyCertificateOutlined,
    SendOutlined,
    ShoppingOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import type {
    ServiceApplicationSummary,
    ServiceScenarioPage,
    ServiceScenarioSummary,
    SimulationTrace,
} from '../../shared/api/client';
import { simulateServiceApplication } from '../../shared/api/client';
import { Alert, useResource, toast } from '../../shared/components/ui';
import { demoText as demo } from './data';
import { appBasePath, experienceBasePath } from './routes';
import { formatTraceValue, scenarioStatusLabel } from './scenarioConfig';
import './unified-experience.css';

interface Props {
    route: string;
    onNavigate: (path: string) => void;
    onMetaChange?: (meta: { path: string; title: string; description?: string }) => void;
}

type Phase = 'welcome' | 'object' | 'decision' | 'result' | 'fallback' | 'handoff';
type EntryMode = 'natural' | 'catalog';

interface ChatMessage {
    id: number;
    role: 'user' | 'assistant' | 'system';
    text: string;
}

interface SimulatedOrder {
    id: string;
    label: string;
    status: string;
    tone: 'purple' | 'amber';
}

interface ExperienceScenario {
    key: string;
    name: string;
    description: string;
    category: string;
    status: ServiceScenarioSummary['status'];
    version: number | null;
    objectRequired: boolean;
    objectType: string;
    intro: string;
    recommendations: Array<{ key: string; label: string; message: string }>;
    handler: string;
    source: ServiceScenarioSummary;
}

function appKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/([a-z0-9-]+)/)?.[1] || '';
}

function experienceKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/[a-z0-9-]+\/experience\/([a-z][a-z0-9_-]{0,63})$/)?.[1] || null;
}

function toExperienceScenario(scenario: ServiceScenarioSummary): ExperienceScenario {
    const config = scenario.config;
    const handler = config.handlers.find(item => item.enabled !== false);
    return {
        key: scenario.key,
        name: scenario.name,
        description: scenario.description,
        category: config.category || config.domain || '客户服务',
        status: scenario.status,
        version: scenario.published_version,
        objectRequired: !!config.object?.required,
        objectType: config.object?.type || 'object',
        intro: scenario.description,
        recommendations: config.recommendations.map(item => ({ key: item.key, label: item.label, message: item.message })),
        handler: handler?.label || '等待服务端选择承接',
        source: scenario,
    };
}

function scenarioIcon(item: ExperienceScenario): ReactNode {
    const key = `${item.key} ${item.name}`.toLocaleLowerCase();
    if (key.includes('logistic') || key.includes('物流') || key.includes('快递')) return <ThunderboltOutlined/>;
    if (key.includes('rule') || key.includes('规则') || key.includes('知识')) return <BookOutlined/>;
    if (key.includes('invoice') || key.includes('发票')) return <FileTextOutlined/>;
    if (key.includes('complaint') || key.includes('投诉') || key.includes('反馈')) return <InboxOutlined/>;
    if (item.source.config.template === 'action') return <ShoppingOutlined/>;
    return <FileSearchOutlined/>;
}

function scenarioTone(index: number): 'purple' | 'blue' | 'green' | 'amber' | 'rose' | 'slate' {
    return (['purple', 'blue', 'green', 'amber', 'rose', 'slate'] as const)[index % 6];
}

function traceStepDetail(step: Record<string, unknown>): string {
    if (step.step === 'scene') return String(step.scenario_name || step.reason || step.status);
    if (step.step === 'object') return step.status === 'needs_input' ? '等待用户选择业务对象' : `对象 ${String((step.object as Record<string, unknown> | undefined)?.id || '已绑定')}`;
    if (step.step === 'facts') return `${String(step.count || 0)} 项事实 · ${String(step.status)}`;
    if (step.step === 'decision') return step.selected_decision ? `已选择 ${String(step.selected_decision)}` : `${(step.available_keys as string[] | undefined)?.length || 0} 个可选决策`;
    if (step.step === 'handler') return `${String(step.handler_type || '未选择')} · ${String(step.handler_key || '—')}`;
    return String(step.content || step.status);
}

export function UnifiedExperience({ route, onNavigate, onMetaChange }: Props) {
    const appKey = appKeyFromRoute(route);
    const routeKey = experienceKeyFromRoute(route);
    const application = useResource<ServiceApplicationSummary>(`/service-apps/${appKey}`);
    const scenarioList = useResource<ServiceScenarioPage>('/service-scenarios');
    const [activeKey, setActiveKey] = useState<string | null>(routeKey);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [phase, setPhase] = useState<Phase>('welcome');
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [selectedOrder, setSelectedOrder] = useState<SimulatedOrder | null>(null);
    const [lastQuestion, setLastQuestion] = useState('');
    const [matchReason, setMatchReason] = useState('');
    const [entryMode, setEntryMode] = useState<EntryMode>('natural');
    const [traceOpen, setTraceOpen] = useState(false);
    const [trace, setTrace] = useState<SimulationTrace | null>(null);
    const [error, setError] = useState('');
    const idRef = useRef(0);
    const scrollRef = useRef<HTMLDivElement | null>(null);
    const initialisedRoute = useRef<string | null>(null);

    useEffect(() => {
        if (!application.data) return;
        onMetaChange?.({
            path: route,
            title: '客户统一体验',
            description: `在「${application.data.name}」中体验服务识别、对象选择、用户决策与后端模拟承接。`,
        });
    }, [application.data, onMetaChange, route]);

    useEffect(() => {
        setActiveKey(routeKey);
    }, [routeKey]);

    const scenarioItems = useMemo(() => {
        if (!application.data || !scenarioList.data) return [];
        const byKey = new Map(scenarioList.data.items.map(item => [item.key, item]));
        return application.data.config.scenarios
            .filter(reference => reference.enabled !== false)
            .map(reference => byKey.get(reference.key))
            .filter((item): item is ServiceScenarioSummary => !!item)
            .map(toExperienceScenario);
    }, [application.data, scenarioList.data]);

    const activeScenario = scenarioItems.find(item => item.key === activeKey);
    const groupedScenarios = useMemo(() => {
        const groups = new Map<string, ExperienceScenario[]>();
        for (const item of scenarioItems) {
            const items = groups.get(item.category) || [];
            items.push(item);
            groups.set(item.category, items);
        }
        return Array.from(groups.entries());
    }, [scenarioItems]);
    const quickPrompts = useMemo(() => {
        const messages = scenarioItems.flatMap(item => item.recommendations.map(recommendation => recommendation.message));
        return Array.from(new Set(messages)).slice(0, 4);
    }, [scenarioItems]);
    const simulatedOrders = useMemo<SimulatedOrder[]>(() => [
        {
            id: 'SIM-ORDER-20261031',
            label: `模拟${activeScenario?.objectType || '业务对象'} A`,
            status: '运输中',
            tone: 'purple',
        },
        {
            id: 'SIM-ORDER-20261012',
            label: `模拟${activeScenario?.objectType || '业务对象'} B`,
            status: '已完成',
            tone: 'amber',
        },
    ], [activeScenario?.objectType]);

    useEffect(() => {
        if (initialisedRoute.current === routeKey || !routeKey || !activeScenario) return;
        initialisedRoute.current = routeKey;
        setEntryMode('catalog');
        setMatchReason(`用户从服务目录选择「${activeScenario.name}」`);
        append('assistant', `已进入「${activeScenario.name}」。${activeScenario.intro}`);
        if (activeScenario.objectRequired) {
            setPhase('object');
        }
        else {
            void run(activeScenario, '我想咨询这个服务');
        }
    }, [activeScenario, routeKey]);

    useEffect(() => {
        const element = scrollRef.current;
        element?.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
    }, [messages, phase, busy]);

    function append(role: ChatMessage['role'], text: string) {
        setMessages(prev => [...prev, { id: ++idRef.current, role, text }]);
    }

    async function run(
        scenario: ExperienceScenario | null,
        text: string,
        options: { order?: SimulatedOrder | null; selectedDecision?: string | null; entry?: EntryMode } = {},
    ) {
        const message = text.trim();
        if (!message) return;
        const order = options.order === undefined ? selectedOrder : options.order;
        setBusy(true);
        setError('');
        setLastQuestion(message);
        try {
            const result = await simulateServiceApplication(appKey, {
                message,
                entry: options.entry === 'catalog' ? 'service_catalog' : 'natural_language',
                scenario_key: scenario?.key || null,
                object: scenario?.objectRequired && order
                    ? {
                        id: order.id,
                        type: scenario.objectType,
                        status: order.status,
                        facts: {
                            status: order.status,
                            order_status: order.status,
                            product_name: order.label,
                        },
                    }
                    : null,
                selected_decision: options.selectedDecision || null,
            });
            setTrace(result);
            setActiveKey(result.scenario_key);
            const matched = scenarioItems.find(item => item.key === result.scenario_key);
            setMatchReason(result.explanation[0] || (result.resolved_by === 'keyword' ? '消息命中服务场景关键词' : '服务端完成场景路由'));
            const objectStep = result.steps.find(step => step.step === 'object');
            const handlerType = String(result.handler?.type || '');
            if (objectStep?.status === 'needs_input') {
                setPhase('object');
            }
            else if (handlerType === 'human') {
                setPhase('handoff');
            }
            else {
                setPhase('result');
            }
            append('assistant', result.result.content || matched?.intro || '服务端已完成本次模拟。');
            return result;
        }
        catch (cause) {
            const messageText = cause instanceof Error ? cause.message : '模拟运行失败';
            setError(messageText);
            append('assistant', `模拟运行失败：${messageText}`);
            return null;
        }
        finally {
            setBusy(false);
        }
    }

    function enterScenario(item: ExperienceScenario) {
        onNavigate(`${experienceBasePath(route)}/${item.key}`);
        setActiveKey(item.key);
        setSelectedOrder(null);
        setTrace(null);
        setLastQuestion('');
        setEntryMode('catalog');
        setMatchReason(`用户从服务目录选择「${item.name}」`);
    }

    function send(raw?: string) {
        const text = (raw || input).trim();
        if (!text || busy) return;
        setInput('');
        append('user', text);
        void run(activeScenario || null, text, { entry: activeScenario ? 'catalog' : 'natural' });
    }

    function chooseOrder(order: SimulatedOrder) {
        if (!activeScenario) return;
        append('user', `选择模拟对象 ${order.id}`);
        setSelectedOrder(order);
        setPhase('decision');
        void run(activeScenario, lastQuestion || `我想咨询${activeScenario.name}`, { order });
    }

    function chooseQuestion(question: string) {
        if (!activeScenario) return;
        append('user', question);
        void run(activeScenario, question);
    }

    function confirmAction() {
        if (!activeScenario || !trace) return;
        const confirmation = activeScenario.source.config.decisions.find(item => item.kind === 'confirm_action');
        append('user', confirmation?.label || '确认提交');
        void run(activeScenario, lastQuestion || '确认提交', { selectedDecision: confirmation?.key || null });
    }

    function requestHandoff(reason = '用户请求人工跟进') {
        append('user', reason);
        void run(activeScenario || null, '转人工');
    }

    function reset() {
        initialisedRoute.current = null;
        idRef.current = 0;
        setMessages([]);
        setActiveKey(null);
        setPhase('welcome');
        setInput('');
        setBusy(false);
        setSelectedOrder(null);
        setLastQuestion('');
        setMatchReason('');
        setEntryMode('natural');
        setTrace(null);
        setError('');
        onNavigate(experienceBasePath(route));
    }

    if ((application.loading && !application.data) || (scenarioList.loading && !scenarioList.data)) {
        return <div className="cx-shell"><Spin/></div>;
    }
    if (!application.data) return <div className="cx-shell"><Alert error={application.error || '服务应用不存在'}/><Button onClick={() => onNavigate('/service-apps')}>返回服务应用</Button></div>;

    const traceSteps = trace?.steps.map(step => ({
        title: stepTitle(step.step),
        detail: traceStepDetail(step),
        state: step.status === 'pending' || step.status === 'skipped' ? 'idle' : step.status === 'needs_input' ? 'active' : 'done',
    })) || [];

    return <div className="cx-shell">
        <aside className="cx-sidebar" aria-label="服务场景目录">
            <div className="cx-sidebar-brand">
                <span className="cx-brand-mark"><RobotOutlined/></span>
                <div><strong>{application.data.name}</strong><small>统一体验入口</small></div>
            </div>
            <div className="cx-scenario-groups">
                {groupedScenarios.map(([category, scenarios]) => <div className="cx-scenario-group" key={category}>
                    <span className="cx-sidebar-label">{category}</span>
                    <div className="cx-scenario-list">
                        {scenarios.map(item => <button
                            type="button"
                            key={item.key}
                            className={`cx-scenario-link${activeKey === item.key ? ' is-active' : ''}`}
                            onClick={() => enterScenario(item)}
                            aria-pressed={activeKey === item.key}
                        >
                            <span className={`cx-scenario-link-icon ${scenarioTone(scenarioItems.indexOf(item))}`}>{scenarioIcon(item)}</span>
                            <span><strong>{item.name}</strong><small>{item.objectRequired ? `需要${item.objectType}` : '无需对象'}</small></span>
                            <i className={`cx-status-dot ${item.status}`}/>
                        </button>)}
                    </div>
                </div>)}
                {!groupedScenarios.length && <p className="cx-sidebar-empty">该应用尚未关联服务场景。</p>}
            </div>
            <div className="cx-sidebar-foot">
                <Button block icon={<FileSearchOutlined/>} onClick={() => setTraceOpen(true)}>{demo('查看决策解释')}</Button>
                <p><SafetyCertificateOutlined/> 页面只展示后端模拟轨迹，不读取真实订单</p>
            </div>
        </aside>

        <section className="cx-main">
            <header className="cx-topbar">
                <div className="cx-topbar-title">
                    <Button type="text" icon={<ArrowLeftOutlined/>} onClick={() => onNavigate(appBasePath(route))}>返回服务应用</Button>
                    <div><strong>客户对话</strong><small>一个入口完成识别、选择与处理</small></div>
                </div>
                <div className="cx-context">
                    {activeScenario && <span className="cx-context-chip scenario"><i className={activeScenario.status}/>{activeScenario.name}</span>}
                    {selectedOrder && <span className="cx-context-chip order"><ShoppingOutlined/>模拟对象 {selectedOrder.id}</span>}
                    <span className="cx-context-chip sandbox">后端模拟</span>
                </div>
                <div className="cx-topbar-actions">
                    <Button icon={<ReloadOutlined/>} onClick={reset}>新对话</Button>
                    <Button icon={<FileSearchOutlined/>} onClick={() => setTraceOpen(true)}>决策解释</Button>
                </div>
            </header>

            <Alert error={error || scenarioList.error}/>

            <div className="cx-conversation" ref={scrollRef} aria-live="polite">
                {messages.length === 0 && !busy && <Welcome
                    applicationName={application.data.name}
                    scenarios={scenarioItems}
                    prompts={quickPrompts}
                    onScenario={enterScenario}
                    onPrompt={send}
                    onHandoff={() => requestHandoff('用户从欢迎页请求人工客服')}
                />}

                {messages.map(message => <div className={`cx-message ${message.role}`} key={message.id}>
                    {message.role !== 'user' && <span className="cx-message-avatar"><RobotOutlined/></span>}
                    <div className="cx-message-body">
                        <span className="cx-message-meta">{message.role === 'user' ? '你' : '智能助手'}</span>
                        <div className="cx-message-bubble">{message.text}</div>
                    </div>
                </div>)}

                {busy && <div className="cx-message assistant">
                    <span className="cx-message-avatar"><RobotOutlined/></span>
                    <div className="cx-message-body"><span className="cx-message-meta">智能助手</span><div className="cx-thinking"><span/><span/><span/></div></div>
                </div>}

                {!busy && phase === 'object' && activeScenario && <ObjectPicker scenario={activeScenario} orders={simulatedOrders} onSelect={chooseOrder} onMissing={() => {
                    setPhase('fallback');
                    setMatchReason('模拟客户没有可用的业务对象');
                }}/>}
                {!busy && phase === 'decision' && activeScenario && <DecisionPanel scenario={activeScenario} order={selectedOrder} onQuestion={chooseQuestion} onCorrect={() => {
                    setSelectedOrder(null);
                    setPhase('object');
                }}/>}
                {!busy && phase === 'result' && trace && <ScenarioResult trace={trace} onConfirm={confirmAction} onHandoff={() => requestHandoff('处理结果页请求人工跟进')}/>}
                {!busy && phase === 'fallback' && <FallbackPanel scenarios={scenarioItems.slice(0, 4)} onScenario={enterScenario} onHandoff={() => requestHandoff('未命中场景后请求人工')}/>}
                {!busy && phase === 'handoff' && trace && <HandoffPanel trace={trace} order={selectedOrder} onReset={reset}/>}
            </div>

            <div className="cx-composer-wrap">
                {phase === 'welcome' && quickPrompts.length > 0 && <div className="cx-prompt-row">{quickPrompts.map(prompt => <button type="button" key={prompt} onClick={() => send(prompt)}>{prompt}</button>)}</div>}
                <div className="cx-composer">
                    <Input.TextArea
                        autoSize={{ minRows: 1, maxRows: 4 }}
                        value={input}
                        placeholder="描述你的问题，例如：我的物流到哪了"
                        onChange={event => setInput(event.target.value)}
                        onKeyDown={event => {
                            if (event.key === 'Enter' && !event.shiftKey) {
                                event.preventDefault();
                                send();
                            }
                        }}
                        aria-label="描述你的问题"
                    />
                    <Button type="primary" shape="circle" icon={busy ? <LoadingOutlined/> : <SendOutlined/>} disabled={!input.trim() || busy} onClick={() => send()} aria-label="发送"/>
                </div>
                <p className="cx-composer-note"><span>Enter 发送 · Shift + Enter 换行</span><span><SafetyCertificateOutlined/> 模拟数据不会写入真实订单或人工队列</span></p>
            </div>
        </section>

        <Drawer
            title={<span className="cx-drawer-title"><FileSearchOutlined/> 这次服务如何被处理</span>}
            open={traceOpen}
            onClose={() => setTraceOpen(false)}
            width={430}
            className="cx-trace-drawer"
        >
            <div className="cx-trace-banner">
                <SafetyCertificateOutlined/>
                <div><strong>服务端模拟运行</strong><p>解释来自后端持久化 trace，不写入真实订单、工单或人工队列。</p></div>
            </div>
            <div className="cx-trace-summary">
                <span>当前场景</span>
                <strong>{trace?.scenario_name || activeScenario?.name || '尚未命中场景'}</strong>
                <small>{trace ? `v${trace.scenario_version || '草稿'} · ${trace.scenario_status}` : '等待用户描述问题'}</small>
            </div>
            <div className="cx-trace-timeline">
                {traceSteps.map((step, index) => <div className={`cx-trace-step ${step.state}`} key={`${step.title}-${index}`}>
                    <span className="cx-trace-index">{step.state === 'done' ? <CheckOutlined/> : String(index + 1).padStart(2, '0')}</span>
                    <div><strong>{step.title}</strong><p>{step.detail}</p></div>
                </div>)}
                {!traceSteps.length && <p className="cx-trace-empty">运行一次模拟后展示后端返回的决策步骤。</p>}
            </div>
            <div className="cx-trace-reasons">
                <span className="cx-sidebar-label">判断依据</span>
                {trace?.explanation.map((item, index) => <p key={`${item}-${index}`}><MessageOutlined/>{item}</p>)}
                {!trace && <p><MessageOutlined/>{matchReason || '等待用户输入后展示场景路由依据'}</p>}
            </div>
            <div className="cx-trace-caption">{trace?.trace_id ? `trace ${trace.trace_id}` : '该面板仅向管理员解释处理路径，客户端默认不展示。'}</div>
        </Drawer>
    </div>;
}

function stepTitle(step: string) {
    return {
        scene: '入口识别与场景路由',
        object: '业务对象',
        facts: '业务事实',
        decision: '用户决策',
        handler: '处理承接',
        result: '处理结果',
    }[step] || step;
}

function Welcome({ applicationName, scenarios, prompts, onScenario, onPrompt, onHandoff }: {
    applicationName: string;
    scenarios: ExperienceScenario[];
    prompts: string[];
    onScenario: (scenario: ExperienceScenario) => void;
    onPrompt: (prompt: string) => void;
    onHandoff: () => void;
}) {
    return <section className="cx-welcome">
        <div className="cx-welcome-hero">
            <span className="cx-welcome-avatar"><RobotOutlined/></span>
            <div>
                <span className="cx-eyebrow">UNIFIED CUSTOMER EXPERIENCE</span>
                <h2>你好，我是{applicationName}服务助手</h2>
                <p>直接描述问题，我会自动识别服务场景；也可以从服务目录进入，先选业务对象再开始咨询。所有结果由后端模拟器生成。</p>
            </div>
        </div>
        {prompts.length > 0 && <div className="cx-welcome-prompts">
            {prompts.map(prompt => <button type="button" key={prompt} onClick={() => onPrompt(prompt)}>{prompt}<span>›</span></button>)}
        </div>}
        <div className="cx-welcome-section-head">
            <div><span className="cx-eyebrow">SERVICE CATALOG</span><h3>从服务目录进入</h3></div>
            <span>{scenarios.length} 个服务场景</span>
        </div>
        <div className="cx-welcome-grid">
            {scenarios.map((scenario, index) => <button type="button" className="cx-welcome-card" key={scenario.key} onClick={() => onScenario(scenario)}>
                <span className={`cx-welcome-card-icon ${scenarioTone(index)}`}>{scenarioIcon(scenario)}</span>
                <div><strong>{scenario.name}</strong><p>{scenario.description}</p></div>
                <small>{scenario.objectRequired ? `需要选择${scenario.objectType}` : '无需业务对象'} <i>›</i></small>
            </button>)}
        </div>
        <div className="cx-welcome-foot">
            <span><SafetyCertificateOutlined/> 当前为后端模拟体验，使用模拟对象和后端轨迹</span>
            <Button type="link" icon={<CustomerServiceOutlined/>} onClick={onHandoff}>请求人工（模拟）</Button>
        </div>
    </section>;
}

function ObjectPicker({ scenario, orders, onSelect, onMissing }: {
    scenario: ExperienceScenario;
    orders: SimulatedOrder[];
    onSelect: (order: SimulatedOrder) => void;
    onMissing: () => void;
}) {
    return <section className="cx-object-picker">
        <header>
            <span className="cx-card-icon"><ShoppingOutlined/></span>
            <div><strong>选择要咨询的{scenario.objectType}</strong><p>{scenario.intro}</p></div>
            <span className="cx-card-step">模拟对象</span>
        </header>
        <div className="cx-order-list">
            {orders.map(order => <article className="cx-order-card" key={order.id}>
                <div className={`cx-order-thumb ${order.tone}`}><ShoppingOutlined/></div>
                <div className="cx-order-main">
                    <div><span className={`cx-order-status ${order.status === '运输中' ? 'shipping' : ''}`}>{order.status}</span><small>模拟数据</small></div>
                    <strong>{order.label}</strong>
                    <p>对象 {order.id}</p>
                    <footer><b>仅用于模拟</b><Button size="small" type="primary" onClick={() => onSelect(order)} aria-label={`选择订单 ${order.id}`}>选择</Button></footer>
                </div>
            </article>)}
        </div>
        <div className="cx-object-footer">
            <span>只展示识别业务对象所需的最少事实</span>
            <Button type="link" onClick={onMissing}>没有对应对象？</Button>
        </div>
    </section>;
}

function DecisionPanel({ scenario, order, onQuestion, onCorrect }: {
    scenario: ExperienceScenario;
    order: SimulatedOrder | null;
    onQuestion: (question: string) => void;
    onCorrect: () => void;
}) {
    return <section className="cx-decision">
        {order && <div className="cx-bound-order">
            <span className="cx-bound-icon"><ShoppingOutlined/></span>
            <div><small>正在咨询此模拟对象</small><strong>{order.label}</strong><p>{scenario.objectType} {order.id} · {order.status}</p></div>
            <Button type="link" onClick={onCorrect}>不是这个对象？</Button>
        </div>}
        <header>
            <span className="cx-card-icon"><CheckCircleFilled/></span>
            <div><strong>{order ? '关于这个对象，你想咨询什么？' : '请选择你想处理的问题'}</strong><p>选择后，系统会继续调用后端模拟器。</p></div>
        </header>
        <div className="cx-question-list">
            {scenario.recommendations.map(item => <button type="button" key={item.key} aria-label={item.label} onClick={() => onQuestion(item.message)}>{item.label}<span aria-hidden="true">›</span></button>)}
        </div>
        {!scenario.recommendations.length && <p className="cx-decision-note">该场景尚未配置推荐问题，可以直接在下方输入。</p>}
    </section>;
}

function ScenarioResult({ trace, onConfirm, onHandoff }: { trace: SimulationTrace; onConfirm: () => void; onHandoff: () => void }) {
    const needConfirmation = trace.decisions.some(item => item.kind === 'confirm_action' && item.required);
    return <section className="cx-result">
        <ResultHead icon={<CheckCircleFilled/>} label={trace.result.status === 'needs_input' ? '等待确认' : '处理完成'} title={String(trace.handler?.label || trace.scenario_name)} tone="green"/>
        <p className="cx-result-lead">{trace.result.content}</p>
        {trace.facts.length > 0 && <div className="cx-fact-grid">
            {trace.facts.slice(0, 6).map(fact => <div key={fact.key}><span>{fact.label}</span><strong>{formatTraceValue(fact.value)}</strong></div>)}
        </div>}
        <div className="cx-result-actions">
            {needConfirmation && <Button type="primary" onClick={onConfirm} icon={<CheckOutlined/>}>确认提交</Button>}
            <Button icon={<CustomerServiceOutlined/>} onClick={onHandoff}>转人工跟进</Button>
            <Button onClick={() => toast.success(`轨迹已持久化：${trace.trace_id || '—'}`)} icon={<FileSearchOutlined/>}>轨迹已保存</Button>
        </div>
        <p className="cx-result-note"><SafetyCertificateOutlined/> 结果来自后端模拟轨迹，未写入真实业务系统。</p>
    </section>;
}

function ResultHead({ icon, label, title, tone }: { icon: ReactNode; label: string; title: string; tone: string }) {
    return <header className="cx-result-head">
        <span className={`cx-result-icon ${tone}`}>{icon}</span>
        <div><span>{label}</span><strong>{title}</strong></div>
        <span className="cx-result-check"><CheckOutlined/> 后端返回</span>
    </header>;
}

function FallbackPanel({ scenarios, onScenario, onHandoff }: {
    scenarios: ExperienceScenario[];
    onScenario: (scenario: ExperienceScenario) => void;
    onHandoff: () => void;
}) {
    return <section className="cx-fallback">
        <span className="cx-fallback-icon"><InboxOutlined/></span>
        <div><span className="cx-eyebrow">NO OBJECT AVAILABLE</span><h3>当前没有可用的模拟业务对象</h3><p>可以从服务目录切换场景，或请求人工继续处理。</p></div>
        <div className="cx-fallback-grid">{scenarios.map((scenario, index) => <button type="button" key={scenario.key} onClick={() => onScenario(scenario)}><span className={scenarioTone(index)}>{scenarioIcon(scenario)}</span><strong>{scenario.name}</strong><small>›</small></button>)}</div>
        <div className="cx-fallback-actions"><Button onClick={onHandoff} icon={<CustomerServiceOutlined/>}>请求人工（模拟）</Button><span>后端会记录本次模拟轨迹</span></div>
    </section>;
}

function HandoffPanel({ trace, order, onReset }: { trace: SimulationTrace; order: SimulatedOrder | null; onReset: () => void }) {
    return <section className="cx-handoff">
        <span className="cx-handoff-icon"><CustomerServiceOutlined/></span>
        <div>
            <span className="cx-eyebrow">SIMULATED HUMAN HANDOFF</span>
            <h3>后端已选择人工承接</h3>
            <p>这是一次模拟转接，不会写入真实人工队列。轨迹记录了当前场景、对象和问题。</p>
        </div>
        <div className="cx-handoff-summary">
            <div><span>承接队列</span><strong>{String(trace.handler?.queue || trace.handler?.label || '人工队列')}</strong></div>
            <div><span>当前场景</span><strong>{trace.scenario_name}</strong></div>
            <div><span>业务对象</span><strong>{order?.id || '无（仅会话上下文）'}</strong></div>
            <div><span>轨迹编号</span><strong>{trace.trace_id || '已保存'}</strong></div>
        </div>
        <div className="cx-handoff-actions"><Button onClick={() => toast.success('模拟轨迹已保存')} icon={<ClockCircleOutlined/>}>查看轨迹</Button><Button type="primary" onClick={onReset}>开始新对话</Button></div>
    </section>;
}
