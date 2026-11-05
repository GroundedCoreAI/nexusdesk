import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, Input, Spin } from 'antd';
import {
    ArrowLeftOutlined,
    CheckOutlined,
    CustomerServiceOutlined,
    RobotOutlined,
    SendOutlined,
    ShoppingOutlined,
} from '@ant-design/icons';
import type { ServiceApplicationSummary, ServiceScenarioSummary, SimulationTrace } from '../../shared/api/client';
import { simulateServiceApplication } from '../../shared/api/client';
import { Alert, useResource, toast } from '../../shared/components/ui';
import { demoText as demo } from './data';
import { ScenarioTabs, ScenarioTopline } from './ScenarioChrome';
import { experienceBasePath, scenarioBasePath, scenarioKeyFromPath } from './routes';
import { formatTraceValue, objectTypeLabel, serviceResultLabel } from './scenarioConfig';
import { simulatedBusinessObjects, type SimulatedBusinessObject } from './simulationSamples';
import './service-scenarios.css';

interface Props {
    route: string;
    onNavigate: (path: string) => void;
    onMetaChange?: (meta: { path: string; title: string; description?: string }) => void;
}

type SimulatedOrder = SimulatedBusinessObject;

function appKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/([a-z0-9-]+)/)?.[1] || '';
}

export function CustomerExperiencePreview({ route, onNavigate, onMetaChange }: Props) {
    const appKey = appKeyFromRoute(route);
    const scenarioKey = scenarioKeyFromPath(route);
    const application = useResource<ServiceApplicationSummary>(`/service-apps/${appKey}`);
    const scenario = useResource<ServiceScenarioSummary>(`/service-scenarios/${scenarioKey}`);
    const [selectedOrder, setSelectedOrder] = useState<SimulatedOrder | null>(null);
    const [trace, setTrace] = useState<SimulationTrace | null>(null);
    const [question, setQuestion] = useState('');
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const base = scenarioBasePath(route);
    const config = scenario.data?.config;
    const objectLabel = config?.object?.type ? objectTypeLabel(config.object.type) : '业务对象';
    const objectContextLabel = config?.object ? objectLabel : '无需业务对象';
    const simulatedOrders = useMemo(() => simulatedBusinessObjects(scenario.data), [scenario.data]);

    useEffect(() => {
        if (!scenario.data) return;
        onMetaChange?.({
            path: route,
            title: '客户端交互预览',
            description: `预览「${scenario.data.name}」的客户对象选择、问题决策和处理结果。`,
        });
    }, [onMetaChange, route, scenario.data]);

    async function run(order: SimulatedOrder | null, text: string) {
        if (!text.trim()) return;
        setBusy(true);
        setError('');
        setQuestion(text);
        try {
            const result = await simulateServiceApplication(appKey, {
                message: text,
                entry: 'natural_language',
                scenario_key: scenarioKey,
                object: order && config?.object?.required
                    ? {
                        id: order.id,
                        type: config.object.type,
                        status: order.status,
                        facts: order.facts,
                    }
                    : null,
            });
            setTrace(result);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '预览运行失败');
        }
        finally {
            setBusy(false);
        }
    }

    function chooseOrder(order: SimulatedOrder) {
        setSelectedOrder(order);
        setTrace(null);
        void run(order, `我想咨询${scenario.data?.name || '这个服务'}`);
    }

    function send() {
        if (!input.trim()) return;
        const text = input.trim();
        setInput('');
        void run(selectedOrder, text);
    }

    if (scenario.loading && !scenario.data) return <div className="customer-experience"><Spin/></div>;
    if (!scenario.data) return <div className="customer-experience">
        <Alert error={scenario.error || '服务场景不存在'}/>
        <Button onClick={() => onNavigate(`/service-apps/${appKey}`)}>返回服务应用</Button>
    </div>;

    return <div className="customer-experience">
        <ScenarioTopline
            route={route}
            onNavigate={onNavigate}
            actions={<>
                <Button icon={<ArrowLeftOutlined aria-hidden/>} onClick={() => onNavigate(base)}>{demo('返回场景配置')}</Button>
                <Button type="primary" onClick={() => onNavigate(`${base}/simulator`)}>{demo('查看决策路径')}</Button>
            </>}
        />
        <ScenarioTabs route={route} onNavigate={onNavigate}/>
        <Alert error={error || application.error || scenario.error}/>

        <header className="customer-preview-intro">
            <div>
                <span className="scenario-eyebrow">CUSTOMER EXPERIENCE · SERVER SIMULATION</span>
                <h2>{demo(config?.object?.required ? `从“选择${objectLabel}”到“带上下文继续服务”` : '从发起咨询到获得明确处理结果')}</h2>
                <p>{demo('两个界面调用同一个后端模拟接口。业务对象为模拟数据，结果、事实、承接与解释均来自服务端轨迹。')}</p>
            </div>
            <div className="customer-step-legend">
                <span className={selectedOrder ? '' : 'is-active'}><i>1</i>{demo('选择业务对象')}</span>
                <b>→</b>
                <span className={selectedOrder ? 'is-active' : ''}><i>2</i>{demo('带上下文服务')}</span>
            </div>
        </header>

        <div className="customer-preview-grid">
            <section className="customer-stage">
                <header className="customer-stage-label"><span>01</span><div><strong>{demo(config?.object?.required ? `选择${objectLabel}` : '直接发起咨询')}</strong><small>{demo('模拟输入，不读取真实业务数据')}</small></div></header>
                <PhoneFrame>
                    <div className="customer-phone-status"><span>10:35</span><span>▮▮▮ ᯤ 85%</span></div>
                    <div className="customer-phone-head">
                        <span>‹</span>
                        <div><strong>{application.data?.name || appKey}</strong><small>{scenario.data.name}</small></div>
                        <b>AI</b>
                    </div>
                    <div className="customer-phone-body picker-body">
                        <div className="customer-agent-row">
                            <span><RobotOutlined/></span>
                            <div>{config?.object?.required ? demo(`您好，请选择要咨询的模拟${objectLabel}。`) : demo('该场景无需业务对象，可以直接开始咨询。')}
                                <small>{demo('选择后会携带对象上下文调用后端模拟器。')}</small></div>
                        </div>
                        <div className="customer-filter-pills"><span className="is-active">{demo('模拟数据')}</span><span>{demo('运输中')}</span><span>{demo('已完成')}</span></div>
                        {config?.object?.required && simulatedOrders.map((order, index) => <OrderOption
                            key={order.id}
                            id={order.id}
                            product={order.label}
                            amount={`¥${order.amount.toFixed(2)}`}
                            status={order.status}
                            date={order.orderedAt}
                            selected={selectedOrder?.id === order.id}
                            onSelect={() => chooseOrder(order)}
                            tone={index === 0 ? 'purple' : 'amber'}
                        />)}
                        <button type="button" className="customer-other-order" onClick={() => onNavigate(`${experienceBasePath(route)}/${scenarioKey}`)}>
                            {demo('切换其他服务场景')} ›
                        </button>
                        <div className="customer-agent-row compact"><span><RobotOutlined/></span><div>{demo('也可以直接告诉我你在找什么。')}</div></div>
                        <div className="customer-quick-pills">{(config?.recommendations || []).slice(0, 4).map(item => <button type="button" key={item.key} onClick={() => void run(selectedOrder, item.message)}>{item.label}</button>)}</div>
                    </div>
                    <PhoneComposer value={input} onChange={setInput} onSend={send} hint={demo('输入你想咨询的问题...')} note={demo('模拟输入不会写入真实业务系统。')}/>
                </PhoneFrame>
            </section>

            <section className="customer-stage">
                <header className="customer-stage-label"><span>02</span><div><strong>{demo('带上下文服务')}</strong><small>{demo('结果与轨迹来自后端')}</small></div></header>
                <PhoneFrame>
                    <div className="customer-phone-status"><span>10:35</span><span>▮▮▮ ᯤ 85%</span></div>
                    <div className="customer-phone-head">
                        <span>‹</span>
                        <div><strong>{application.data?.name || appKey}</strong><small>{selectedOrder ? `模拟对象 ${selectedOrder.id}` : '等待对象'}</small></div>
                        <b>AI</b>
                    </div>
                    <div className="customer-phone-body context-body">
                        <div className="customer-context-card">
                            <div><span>{demo('当前场景')}</span><b>{scenario.data.name}</b></div>
                            <strong>{selectedOrder?.label || objectContextLabel}</strong>
                            <p>{selectedOrder?.id || '模拟输入'} <b>{selectedOrder?.status || ''}</b></p>
                            <footer><span>{trace ? `trace ${trace.trace_id?.slice(0, 8) || '已运行'}` : '等待模拟'}</span>
                                <button type="button" onClick={() => {
                                    setSelectedOrder(null);
                                    setTrace(null);
                                }}>{demo(config?.object ? `不是这个${objectLabel}？` : '重新发起咨询')}</button></footer>
                        </div>
                        <div className="customer-agent-row compact">
                            <span><RobotOutlined/></span>
                            <div>{trace ? `${trace.scenario_name} · ${serviceResultLabel(trace.result.status)}` : demo(config?.object ? `关于这个${objectLabel}，你想咨询什么？` : '请描述你想咨询或办理的问题。')}
                                <small>{trace ? (config?.recommendations[0]?.label || '已根据当前对象执行服务') : demo('选择后由后端处理。')}</small></div>
                        </div>
                        <div className="customer-question-list">
                            {(config?.recommendations || []).map(item => <button type="button" key={item.key} onClick={() => void run(selectedOrder, item.message)}>{item.label}<span>›</span></button>)}
                        </div>
                        {question && <div className="customer-user-message">{question}</div>}
                        {trace ? <div className="customer-result-card">
                            <strong>{trace.handler?.label ? String(trace.handler.label) : trace.scenario_name}</strong>
                            <p>{trace.result.content}</p>
                            {trace.facts.some(fact => fact.value !== null && fact.value !== undefined && fact.value !== '') && <div className="customer-result-facts">
                                {trace.facts.filter(fact => fact.value !== null && fact.value !== undefined && fact.value !== '').slice(0, 4).map(fact => <span key={fact.key}>{fact.label}：{formatTraceValue(fact.value)}</span>)}
                            </div>}
                            <div>
                                <Button size="small" onClick={() => void run(selectedOrder, '转人工')} icon={<CustomerServiceOutlined/>}>{demo('转人工跟进')}</Button>
                                <Button size="small" type="primary" onClick={() => toast.success(`已生成轨迹 ${trace.trace_id || ''}`)} icon={<CheckOutlined/>}>{demo('轨迹已保存')}</Button>
                            </div>
                        </div> : <div className="customer-result-card is-empty">
                            <strong>{busy ? '正在调用后端模拟器…' : '尚未运行'}</strong>
                            <p>选择业务对象或问题后，这里展示后端返回的处理结果。</p>
                        </div>}
                        <p className="customer-switch-note">{demo('可随时切换场景')} <button type="button" onClick={() => onNavigate(`${experienceBasePath(route)}/${scenarioKey}`)}>{demo('切换')}</button></p>
                    </div>
                    <PhoneComposer value={input} onChange={setInput} onSend={send} hint={demo('继续输入...')} note={selectedOrder ? `当前已绑定模拟对象 ${selectedOrder.id}` : '当前未绑定业务对象'}/>
                </PhoneFrame>
            </section>
        </div>
    </div>;
}

function PhoneFrame({ children }: { children: ReactNode }) {
    return <div className="customer-phone">{children}</div>;
}

function PhoneComposer({ value, onChange, onSend, hint, note }: {
    value: string;
    onChange: (value: string) => void;
    onSend: () => void;
    hint: string;
    note: string;
}) {
    return <div className="customer-phone-footer">
        <div className="customer-composer">
            <Input variant="borderless" value={value} placeholder={hint} onChange={event => onChange(event.target.value)} onPressEnter={onSend}/>
            <button type="button" onClick={onSend} aria-label="发送"><SendOutlined/></button>
        </div>
        <small>{note}</small>
    </div>;
}

function OrderOption({ id, product, amount, status, date, selected, onSelect, tone }: {
    id: string;
    product: string;
    amount: string;
    status: string;
    date: string;
    selected: boolean;
    onSelect: () => void;
    tone: 'purple' | 'amber';
}) {
    return <button type="button" className={`customer-order-option${selected ? ' is-selected' : ''}`} onClick={onSelect} aria-pressed={selected}>
        <header><span>{status}</span><small>{date}</small></header>
        <div className="customer-order-product">
            <span className={`customer-product-thumb ${tone}`}/>
            <div><strong>{product}</strong><small>{demo('模拟对象')} {id}</small></div>
        </div>
        <footer><b>{amount}</b><span>{selected ? demo('已选择') : demo('选择')} ›</span></footer>
    </button>;
}
