import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, Form, Input, InputNumber, Modal, Select, Spin, Switch } from 'antd';
import {
    ArrowRightOutlined,
    BookOutlined,
    CheckOutlined,
    CustomerServiceOutlined,
    EyeOutlined,
    FileSearchOutlined,
    FileTextOutlined,
    GlobalOutlined,
    InboxOutlined,
    MessageOutlined,
    PlayCircleOutlined,
    PlusOutlined,
    RobotOutlined,
    SendOutlined,
    ShoppingOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import type {
    Agent,
    ScenarioConfig,
    ScenarioEntry,
    ScenarioFactField,
    ScenarioHandler,
    ScenarioHandlerType,
    ScenarioRecommendation,
    ServiceApplicationSummary,
    ServiceProviderPage,
    ServiceScenarioPage,
    ServiceScenarioSummary,
} from '../../shared/api/client';
import { publishServiceScenario, updateServiceScenario } from '../../shared/api/client';
import { Alert, useAccess, useResource, toast } from '../../shared/components/ui';
import { executorCount, ProviderSelect } from '../service-apps/toolSelect';
import { demoText as demo } from './data';
import { ScenarioTabs, ScenarioTopline } from './ScenarioChrome';
import { appBasePath, experienceBasePath, scenarioBasePath, scenarioKeyFromPath } from './routes';
import {
    applicationScenarioItems,
    effectiveServiceCategories,
    groupScenariosByCategory,
    handlerTypeLabel,
    objectModeLabel,
    scenarioStatusLabel,
    scenarioTone,
} from './scenarioConfig';
import './service-scenarios.css';

interface Props {
    route: string;
    onNavigate: (path: string) => void;
    onMetaChange?: (meta: { path: string; title: string; description?: string }) => void;
    onScenarioChanged?: () => void;
    embedded?: boolean;
}

type EditorKind = 'entry' | 'fact' | 'recommendation' | 'handler';

const handlerTypes: ScenarioHandlerType[] = ['direct', 'knowledge', 'query', 'action', 'agent', 'human', 'tracking'];

function appKeyFromRoute(route: string) {
    return route.match(/^\/service-apps\/([a-z0-9-]+)/)?.[1] || '';
}

export function SceneWorkbench({ route, onNavigate, onMetaChange, onScenarioChanged, embedded = false }: Props) {
    const { admin } = useAccess();
    const scenarioKey = scenarioKeyFromPath(route);
    const appKey = appKeyFromRoute(route);
    const scenarioResource = useResource<ServiceScenarioSummary>(`/service-scenarios/${scenarioKey}`);
    const application = useResource<ServiceApplicationSummary>(`/service-apps/${appKey}`);
    const scenarioList = useResource<ServiceScenarioPage>('/service-scenarios');
    const agents = useResource<Agent[]>('/agents');
    // Object facts and handler tools both point at registered providers; these
    // two lists are what readiness compares the scene against.
    const objectProviders = useResource<ServiceProviderPage>('/service-providers?kind=object');
    const toolProviders = useResource<ServiceProviderPage>('/service-providers?kind=tool');
    const [draft, setDraft] = useState<ScenarioConfig | null>(null);
    const [saved, setSaved] = useState('');
    const [revision, setRevision] = useState(1);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [editor, setEditor] = useState<EditorKind | null>(null);
    const [editingHandler, setEditingHandler] = useState<string | null>(null);
    const [form] = Form.useForm();

    useEffect(() => {
        if (!scenarioResource.data?.config) return;
        setDraft(structuredClone(scenarioResource.data.config));
        setSaved(JSON.stringify(scenarioResource.data.config));
        setRevision(scenarioResource.data.revision);
    }, [scenarioResource.data]);

    useEffect(() => {
        if (!scenarioResource.data) return;
        onMetaChange?.({
            path: route,
            title: scenarioResource.data.name,
            description: scenarioResource.data.description || undefined,
        });
    }, [onMetaChange, route, scenarioResource.data]);

    const dirty = !!draft && JSON.stringify(draft) !== saved;
    const base = scenarioBasePath(route);
    const scopedScenarios = useMemo(
        () => applicationScenarioItems(application.data, scenarioList.data?.items || []),
        [application.data, scenarioList.data],
    );
    const serviceCategories = useMemo(
        () => effectiveServiceCategories(application.data, scenarioList.data?.items || []),
        [application.data, scenarioList.data],
    );
    const groups = useMemo(() => {
        const items = scopedScenarios.map(scenario => ({
            scenario,
            category: scenario.config?.category || scenario.config?.domain || '其他服务',
        }));
        return groupScenariosByCategory(items, serviceCategories)
            .map(([category, grouped]) => [category, grouped.map(item => item.scenario)] as const);
    }, [scopedScenarios, serviceCategories]);

    const objectProviderItems = useMemo(
        () => objectProviders.data?.items || [],
        [objectProviders.data],
    );
    const toolProviderItems = useMemo(
        () => toolProviders.data?.items || [],
        [toolProviders.data],
    );
    /** The object provider currently wired to this scene, if it still exists. */
    const activeObjectProvider = useMemo(
        () => objectProviderItems.find(item => item.key === draft?.object?.provider),
        [objectProviderItems, draft?.object?.provider],
    );
    /** Prefer a provider that already declares executors over a bare placeholder. */
    const defaultObjectProvider = useMemo(() => {
        const items = objectProviderItems;
        return (items.find(item => item.enabled && executorCount(item) > 0)
            || items.find(item => item.enabled)
            || items[0])?.key || 'demo_provider';
    }, [objectProviderItems]);

    function update(patch: Partial<ScenarioConfig>) {
        setDraft(current => current ? { ...current, ...patch } : current);
    }

    async function saveDraft(showToast = true) {
        if (!draft) throw new Error('场景配置尚未加载');
        setBusy(true);
        setError('');
        try {
            const updated = await updateServiceScenario(scenarioKey, draft, revision);
            setDraft(structuredClone(updated.config));
            setSaved(JSON.stringify(updated.config));
            setRevision(updated.revision);
            scenarioResource.refresh();
            scenarioList.refresh();
            onScenarioChanged?.();
            if (showToast) toast.success('场景草稿已保存');
            return updated;
        }
        catch (cause) {
            const message = cause instanceof Error ? cause.message : '保存场景失败';
            setError(message);
            throw cause;
        }
        finally {
            setBusy(false);
        }
    }

    async function publish() {
        if (!draft) return;
        setBusy(true);
        setError('');
        try {
            const current = dirty ? await updateServiceScenario(scenarioKey, draft, revision) : null;
            const nextRevision = current?.revision || revision;
            const published = await publishServiceScenario(scenarioKey, nextRevision);
            setDraft(structuredClone(published.config));
            setSaved(JSON.stringify(published.config));
            setRevision(published.revision);
            scenarioResource.refresh();
            scenarioList.refresh();
            onScenarioChanged?.();
            toast.success(`场景已发布${published.published_version ? `为 v${published.published_version}` : ''}`);
        }
        catch (cause) {
            setError(cause instanceof Error ? cause.message : '发布场景失败');
        }
        finally {
            setBusy(false);
        }
    }

    function openEditor(kind: EditorKind, handler?: ScenarioHandler) {
        setEditor(kind);
        setEditingHandler(handler?.key || null);
        form.resetFields();
        if (handler) form.setFieldsValue(handler);
        if (kind === 'handler') form.setFieldsValue({ type: 'query', priority: 10, enabled: true });
    }

    function closeEditor() {
        setEditor(null);
        setEditingHandler(null);
        form.resetFields();
    }

    function saveEditor(values: Record<string, unknown>) {
        if (!draft) return;
        if (editor === 'entry') {
            const item: ScenarioEntry = {
                key: String(values.key),
                type: values.type as ScenarioEntry['type'],
                label: String(values.label),
                description: String(values.description || ''),
                enabled: true,
                config: {},
            };
            update({ entries: [...draft.entries, item] });
        }
        if (editor === 'fact') {
            const item: ScenarioFactField = {
                key: String(values.key),
                label: String(values.label),
                source: String(values.source),
                format: 'text',
                order: (draft.facts.length + 1) * 10,
                masked: !!values.masked,
                audiences: ['customer', 'agent', 'human'],
                refresh: 'on_open',
                config: {},
            };
            update({ facts: [...draft.facts, item] });
        }
        if (editor === 'recommendation') {
            const item: ScenarioRecommendation = {
                key: String(values.key),
                label: String(values.label),
                message: String(values.message),
                when: {},
            };
            update({ recommendations: [...draft.recommendations, item] });
        }
        if (editor === 'handler') {
            const type = values.type as ScenarioHandlerType;
            const key = String(values.key);
            const agent = (agents.data || []).find(item => item.id === values.agent_id);
            const item: ScenarioHandler = {
                key,
                type,
                label: String(values.label),
                priority: Number(values.priority || 10),
                enabled: values.enabled !== false,
                when: { requires_object: draft.object?.required || null },
                agent_id: type === 'agent' ? String(values.agent_id || '') || null : null,
                agent_version: type === 'agent' ? agent?.published_version ?? null : null,
                agent_name: type === 'agent' ? agent?.name ?? null : null,
                queue: type === 'human' ? String(values.queue || '') || null : null,
                tool: ['query', 'action', 'tracking'].includes(type) ? String(values.tool || '') || null : null,
                reply: type === 'direct' ? String(values.reply || '') : null,
                config: {},
            };
            let decisions = draft.decisions;
            if (type === 'action' && !decisions.some(decision => decision.kind === 'confirm_action')) {
                decisions = [...decisions, {
                    key: `confirm-${key}`,
                    kind: 'confirm_action',
                    label: '确认提交',
                    required: true,
                    options: [],
                    allow_free_text: false,
                    allow_skip: false,
                    confirm: true,
                    correctable: true,
                    when: {},
                }];
            }
            update({
                decisions,
                handlers: editingHandler
                    ? draft.handlers.map(handler => handler.key === editingHandler ? item : handler)
                    : [...draft.handlers, item],
                fallback_order: editingHandler
                    ? draft.fallback_order
                    : [...draft.fallback_order, key],
            });
        }
        closeEditor();
    }

    function removeHandler(key: string) {
        if (!draft) return;
        update({
            handlers: draft.handlers.filter(item => item.key !== key),
            fallback_order: draft.fallback_order.filter(item => item !== key),
        });
    }

    if (scenarioResource.loading && !draft) return <div className="scene-workbench"><Spin/></div>;
    if (!scenarioResource.data || !draft) return <div className="scene-workbench">
        <Alert error={scenarioResource.error || '服务场景不存在，或当前账号没有访问权限'}/>
        <Button onClick={() => onNavigate(appBasePath(route))}>返回服务应用</Button>
    </div>;

    const scenario = scenarioResource.data;
    const agentHandler = draft.handlers.find(handler => handler.type === 'agent');
    const appChannels = application.data?.config.channels || [];
    const scenarioSaveActions = <>
        <Button loading={busy} disabled={!admin || !dirty} onClick={() => void saveDraft().catch(() => undefined)}>{demo('保存草稿')}</Button>
        <Button type="primary" icon={<SendOutlined aria-hidden/>} loading={busy} disabled={!admin} onClick={() => void publish()}>{demo('发布')}</Button>
    </>;

    return <div className={`scene-workbench${embedded ? ' is-embedded' : ''}`}>
        {embedded
            ? <header className="scene-embedded-toolbar">
                <div className="scene-embedded-heading">
                    <span className="scenario-eyebrow">{demo('场景高级设置')}</span>
                    <div className="scene-embedded-title-line">
                        <h2>{scenario.name}</h2>
                        <span className={`scenario-pill ${scenarioTone(scenario.status)}`}>
                            <i/> {scenarioStatusLabel(scenario.status)}
                            {scenario.published_version ? ` · v${scenario.published_version}` : ' · 未发布'}
                        </span>
                        {agentHandler && <span className="scenario-agent-pill"><RobotOutlined/> Agent · {agentHandler.agent_name || '已引用'}
                            {agentHandler.agent_version ? ` v${agentHandler.agent_version}` : ''}
                        </span>}
                    </div>
                    <p>{scenario.description || '调整场景入口、业务对象、用户决策与处理承接。'}</p>
                </div>
                <div className="scenario-top-actions">
                    <Button icon={<PlayCircleOutlined aria-hidden/>} onClick={() => onNavigate(`${base}/simulator`)}>{demo('模拟与决策')}</Button>
                    <Button icon={<EyeOutlined aria-hidden/>} onClick={() => onNavigate(`${base}/customer`)}>{demo('客户端预览')}</Button>
                    {scenarioSaveActions}
                </div>
            </header>
            : <>
                <ScenarioTopline route={route} onNavigate={onNavigate} actions={<>
                    <Button icon={<PlayCircleOutlined aria-hidden/>} onClick={() => onNavigate(`${base}/simulator`)}>{demo('模拟')}</Button>
                    {scenarioSaveActions}
                </>}/>
                <ScenarioTabs route={route} onNavigate={onNavigate}/>
            </>}
        <Alert error={error || scenarioResource.error || application.error || scenarioList.error}/>
        {dirty && <p className="scenario-save-state" role="status"><i/> 有尚未保存的修改</p>}

        <div className="scene-workbench-grid">
            <aside className="scene-tree">
                <div className="scene-tree-head"><span className="scenario-eyebrow">SERVICE CATALOG</span><h2>{demo('服务目录')}</h2>
                    <Button type="text" icon={<PlusOutlined aria-hidden/>} onClick={() => onNavigate(appBasePath(route))} aria-label="返回应用创建场景"/>
                </div>
                {groups.map(([category, items]) => <div className="scene-tree-group" key={category}>
                    <strong><span>⌄</span> {category} <small>{items.length}</small></strong>
                    {items.map(item => <button
                        type="button"
                        className={item.key === scenarioKey ? 'is-active' : ''}
                        key={item.key}
                        onClick={() => onNavigate(`/service-apps/${appKey}/scenarios/${item.key}`)}
                    >
                        <i className={scenarioTone(item.status)}/>
                        {item.name}
                        <b className={`is-${scenarioTone(item.status)}`}>●</b>
                    </button>)}
                </div>)}
                <div className="scene-tree-help">
                    <InboxOutlined/>
                    <p>{demo('场景来自服务端配置。场景是配置单元，可被自然语言、服务目录和对象卡片共同进入。')}</p>
                </div>
            </aside>

            <main className="scene-config-column">
                <ConfigSection number="01" title={demo('基本信息')} description={demo('给客户和管理者看的业务语言')} configured>
                    <div className="scene-form-grid">
                        <label className="scene-field">
                            <span>{demo('场景名称')}</span>
                            <Input value={draft.name} disabled={!admin} onChange={event => update({ name: event.target.value })}/>
                        </label>
                        <label className="scene-field">
                            <span>{demo('适用渠道')}</span>
                            <Select
                                mode="tags"
                                value={draft.channels}
                                disabled={!admin}
                                options={appChannels.map(channel => ({ value: channel.key, label: channel.name }))}
                                onChange={value => update({ channels: value })}
                            />
                        </label>
                    </div>
                    <label className="scene-field scene-field-wide">
                        <span>{demo('客户任务')}</span>
                        <Input.TextArea autoSize={{ minRows: 2 }} value={draft.description} disabled={!admin} onChange={event => update({ description: event.target.value })}/>
                    </label>
                    <div className="scene-form-grid">
                        <div className="scene-field">
                            <div className="scene-field-label">
                                <span>服务目录</span>
                                <Button
                                    type="link"
                                    size="small"
                                    icon={<BookOutlined aria-hidden/>}
                                    disabled={!admin}
                                    onClick={() => onNavigate(appBasePath(route))}
                                >
                                    管理目录
                                </Button>
                            </div>
                            <Select
                                value={draft.category}
                                disabled={!admin}
                                showSearch
                                optionFilterProp="label"
                                options={serviceCategories.map(category => ({
                                    value: category.name,
                                    label: `${category.name}${category.scenarioCount ? ` · ${category.scenarioCount} 个场景` : ''}`,
                                }))}
                                onChange={value => update({ category: value })}
                            />
                        </div>
                        <label className="scene-field">
                            <span>场景模板</span>
                            <Select
                                value={draft.template}
                                disabled={!admin}
                                options={[
                                    { value: 'consult', label: '咨询' },
                                    { value: 'query', label: '查询' },
                                    { value: 'action', label: '办理' },
                                ]}
                                onChange={value => update({ template: value })}
                            />
                        </label>
                    </div>
                </ConfigSection>

                <ConfigSection number="02" title={demo('入口方式')} description={demo('入口是到达场景的方式，不是场景本身')} meta={`${draft.entries.length} 个入口`}>
                    <div className="scene-entry-grid">
                        {draft.entries.map((entry, index) => <EntryOption
                            key={entry.key}
                            icon={entry.type === 'natural_language' ? <MessageOutlined/> : entry.type === 'service_catalog' ? <InboxOutlined/> : entry.type === 'object_card' ? <FileTextOutlined/> : <GlobalOutlined/>}
                            title={entry.label}
                            description={entry.description || entry.type}
                            active={entry.enabled !== false}
                            onToggle={admin ? () => update({ entries: draft.entries.map((item, itemIndex) => itemIndex === index ? { ...item, enabled: item.enabled === false } : item) }) : undefined}
                        />)}
                        <Button type="dashed" disabled={!admin} icon={<PlusOutlined/>} onClick={() => openEditor('entry')}>添加入口</Button>
                    </div>
                </ConfigSection>

                <ConfigSection number="03" title={demo('业务对象与事实')} description={demo('对象解释“围绕哪一笔”，事实解释“它现在怎样”')} meta={draft.object ? objectModeLabel(draft.object.mode) : '无需对象'}>
                    {draft.object ? <>
                        <div className="scene-object-row">
                            <span className="scene-object-icon"><ShoppingOutlined/></span>
                            <div>
                                <span>{demo('业务对象')}</span>
                                <strong>{draft.object.type} <small>{draft.object.provider}</small></strong>
                            </div>
                            <ArrowRightOutlined/>
                            <div className="scene-object-rule">
                                <span>{demo('候选策略')}</span>
                                <b>最近 {draft.object.candidate_strategy.limit || 5} 笔 · {draft.object.candidate_strategy.sort || 'recent_desc'}</b>
                            </div>
                            <Switch checked={draft.object.required} disabled={!admin} onChange={checked => update({ object: { ...draft.object!, required: checked, mode: checked ? 'required' : 'optional' } })}/>
                        </div>
                        <div className="scene-object-provider">
                            <span>{demo('数据来源')}</span>
                            <ProviderSelect
                                items={objectProviderItems}
                                loading={objectProviders.loading}
                                value={draft.object.provider}
                                onChange={provider => update({ object: { ...draft.object!, provider: provider || '' } })}
                                placeholder="after_sale_ticket_provider"
                            />
                            <small className={activeObjectProvider && executorCount(activeObjectProvider) > 0 ? 'is-live' : ''}>
                                {!activeObjectProvider
                                    ? demo('该接入能力未在「行业能力」中登记，就绪检查会判为未接入。')
                                    : executorCount(activeObjectProvider) > 0
                                        ? demo('已声明 {{v0}} 个执行器，场景会通过工具网关读取真实数据。', { v0: executorCount(activeObjectProvider) })
                                        : demo('该接入能力还没有声明执行器，事实仍是模拟值。')}
                            </small>
                        </div>
                        <div className="scene-fact-row">
                            <span>{demo('展示事实')}</span>
                            {draft.facts.map(fact => <span className="scene-fact-tag" key={fact.key}>
                                {fact.label}
                                {admin && <button type="button" aria-label={`删除事实 ${fact.label}`} onClick={() => update({ facts: draft.facts.filter(item => item.key !== fact.key) })}>×</button>}
                            </span>)}
                            <Button type="dashed" size="small" disabled={!admin} icon={<PlusOutlined aria-hidden/>} onClick={() => openEditor('fact')}>{demo('添加字段')}</Button>
                        </div>
                    </> : <div className="scene-object-empty">
                        <p>当前场景不需要业务对象，可由知识、Direct 或人工直接承接。</p>
                        <Button disabled={!admin} onClick={() => update({
                            object: {
                                type: 'order',
                                provider: defaultObjectProvider,
                                required: true,
                                mode: 'required',
                                candidate_strategy: {
                                    sort: 'recent_desc',
                                    limit: 5,
                                    filters: [],
                                    empty_state: '没有找到可用的业务对象。',
                                    unavailable_state: '业务对象暂时不可用，请稍后重试或转人工。',
                                },
                                permission_policy: 'customer_scope',
                                config: {},
                            },
                        })}>设置业务对象</Button>
                    </div>}
                </ConfigSection>

                <ConfigSection number="04" title={demo('用户决策')} description={demo('让用户明确选择、确认和纠正')} configured={draft.decisions.length > 0}>
                    <div className="scene-decision-grid">
                        {draft.decisions.map((decision, index) => <Decision
                            key={decision.key}
                            title={decision.label}
                            description={`${decision.kind} · ${decision.correctable ? '可纠正' : '不可纠正'}`}
                            badge={decision.required ? '必选' : '可跳过'}
                            mutedBadge={!decision.required}
                            disabled={!admin}
                            onRemove={() => update({ decisions: draft.decisions.filter((_, itemIndex) => itemIndex !== index) })}
                        />)}
                        <Button type="dashed" disabled={!admin} icon={<PlusOutlined/>} onClick={() => update({ decisions: [...draft.decisions, {
                            key: `select-intent-${draft.decisions.length + 1}`,
                            kind: 'select_intent',
                            label: '选择问题',
                            required: false,
                            options: [],
                            allow_free_text: true,
                            allow_skip: true,
                            confirm: false,
                            correctable: true,
                            when: {},
                        }] })}>添加决策</Button>
                    </div>
                    <div className="scene-suggestion-row">
                        <span>{demo('对象相关推荐')}</span>
                        {draft.recommendations.map(item => <span key={item.key}>{item.label}{admin && <button type="button" aria-label={`删除推荐 ${item.label}`} onClick={() => update({ recommendations: draft.recommendations.filter(recommendation => recommendation.key !== item.key) })}>×</button>}</span>)}
                        <Button type="text" size="small" disabled={!admin} icon={<PlusOutlined aria-hidden/>} onClick={() => openEditor('recommendation')}>{demo('添加')}</Button>
                    </div>
                </ConfigSection>

                <ConfigSection number="05" title={demo('处理承接与兜底')} description={demo('选择之后，谁真正把这件事办完')} meta={`${draft.handlers.length} 条路径`} configured>
                    <div className="scene-handler-grid">
                        {draft.handlers.map(handler => <HandlerCard
                            key={handler.key}
                            icon={handler.type === 'human' ? <CustomerServiceOutlined/> : handler.type === 'agent' ? <RobotOutlined/> : handler.type === 'knowledge' ? <FileSearchOutlined/> : <ThunderboltOutlined/>}
                            title={handler.label}
                            description={`${handlerTypeLabel(handler.type)} · 优先级 ${handler.priority || 0}${handler.tool ? ` · ${handler.tool}` : ''}${handler.queue ? ` · ${handler.queue}` : ''}`}
                            active={handler.enabled !== false}
                            disabled={!admin}
                            onToggle={() => update({ handlers: draft.handlers.map(item => item.key === handler.key ? { ...item, enabled: item.enabled === false } : item) })}
                            onEdit={() => openEditor('handler', handler)}
                            onRemove={() => removeHandler(handler.key)}
                        />)}
                        <Button type="dashed" disabled={!admin} icon={<PlusOutlined/>} onClick={() => openEditor('handler')}>添加执行能力</Button>
                    </div>
                    {agentHandler && <div className="scene-agent-binding">
                        <span className="scene-agent-binding-icon"><RobotOutlined/></span>
                        <div>
                            <small>{demo('关联 Agent · 复杂问题与查询失败时启用')}</small>
                            <strong>{agentHandler.agent_name || '请选择 Agent'}</strong>
                        </div>
                        <span className="scene-agent-version">{agentHandler.agent_version ? `已发布 v${agentHandler.agent_version}` : '未固定版本'}</span>
                        <Button type="link" onClick={() => onNavigate(agentHandler.agent_id ? `/agents/${agentHandler.agent_id}/config` : '/agents')}>{demo('打开 Agent 管理')} ›</Button>
                    </div>}
                    <div className="scene-fallback-note">
                        <span>{demo('兜底顺序')}</span>
                        <b>{draft.fallback_order.map(key => draft.handlers.find(handler => handler.key === key)?.label || key).join(' → ') || '尚未配置'}</b>
                        <span>{demo('任一环节不可用时自动降级')}</span>
                    </div>
                </ConfigSection>
            </main>

            <aside className="scene-preview-column">
                <div className="scene-preview-head">
                    <div><span className="scenario-eyebrow">CONFIG SNAPSHOT</span><h2>{demo('实时配置摘要')}</h2></div>
                    <div className="scene-preview-links">
                        <Button type="link" onClick={() => onNavigate(`${experienceBasePath(route)}/${scenarioKey}`)}>{demo('统一体验')}</Button>
                        <Button type="link" onClick={() => onNavigate(`${base}/customer`)}>{demo('客户端预览')} ›</Button>
                    </div>
                </div>
                <div className="scene-device">
                    <div className="scene-device-status"><span>CONFIG</span><span>{scenarioStatusLabel(scenario.status)}</span></div>
                    <div className="scene-device-head">
                        <span>‹</span>
                        <div><strong>{application.data?.name || appKey}</strong><small>{scenario.name}</small></div>
                        <b>API</b>
                    </div>
                    <div className="scene-device-body">
                        <div className="scene-chat-row">
                            <span className="scene-chat-avatar"><RobotOutlined/></span>
                            <div className="scene-chat-bubble">{draft.description || '当前场景尚未填写客户任务。'}</div>
                        </div>
                        <div className="scene-filter-row">
                            {draft.channels.length ? draft.channels.map(channel => <span key={channel}>{channel}</span>) : <span>未配置渠道</span>}
                        </div>
                        <div className="scene-bound-card">
                            <span>{draft.object ? '业务对象' : '无需业务对象'}</span>
                            <strong>{draft.object ? `${draft.object.type} · ${draft.object.provider}` : '由能力直接处理'}</strong>
                            <small>{draft.facts.length} 项事实 · {draft.decisions.length} 个决策 · {draft.handlers.filter(handler => handler.enabled !== false).length} 个可用承接</small>
                        </div>
                        <div className="scene-preview-checks">
                            <span><CheckOutlined/> 配置已加载</span>
                            <span><CheckOutlined/> 入口 {draft.entries.length}</span>
                            <span><CheckOutlined/> 兜底 {draft.fallback_order.length}</span>
                        </div>
                    </div>
                    <div className="scene-device-composer"><span>{demo('模拟输入请在“模拟与决策”中执行')}</span><b>→</b></div>
                </div>
                <p className="scene-preview-note">{demo('此页直接读写服务端草稿。预览结果与决策轨迹在模拟器中生成并持久化。')}</p>
            </aside>
        </div>

        <Modal
            open={!!editor}
            title={editor === 'entry' ? '添加入口' : editor === 'fact' ? '添加业务事实' : editor === 'recommendation' ? '添加推荐问题' : editingHandler ? '编辑执行能力' : '添加执行能力'}
            okText="添加"
            cancelText="取消"
            destroyOnHidden
            onCancel={closeEditor}
            onOk={() => form.submit()}
        >
            <Form form={form} layout="vertical" onFinish={saveEditor}>
                {editor === 'entry' && <>
                    <Form.Item name="key" label="入口标识" rules={[{ required: true, pattern: /^[a-z][a-z0-9_-]{0,63}$/ }]}><Input placeholder="object-card"/></Form.Item>
                    <Form.Item name="type" label="入口类型" rules={[{ required: true }]}><Select options={[
                        { value: 'natural_language', label: '自然语言' },
                        { value: 'service_catalog', label: '服务目录' },
                        { value: 'object_card', label: '对象卡片' },
                        { value: 'external_link', label: '外部链接' },
                    ]}/></Form.Item>
                    <Form.Item name="label" label="展示名称" rules={[{ required: true }]}><Input placeholder="订单卡片"/></Form.Item>
                    <Form.Item name="description" label="说明"><Input/></Form.Item>
                </>}
                {editor === 'fact' && <>
                    <Form.Item name="key" label="事实标识" rules={[{ required: true, pattern: /^[a-z][a-z0-9_]{0,63}$/ }]}><Input placeholder="order_status"/></Form.Item>
                    <Form.Item name="label" label="展示名称" rules={[{ required: true }]}><Input placeholder="订单状态"/></Form.Item>
                    <Form.Item name="source" label="对象字段路径" rules={[{ required: true }]} extra="例如 status、facts.logistics_status"><Input placeholder="status"/></Form.Item>
                    <Form.Item name="masked" label="脱敏展示" valuePropName="checked"><Switch/></Form.Item>
                </>}
                {editor === 'recommendation' && <>
                    <Form.Item name="key" label="推荐标识" rules={[{ required: true, pattern: /^[a-z][a-z0-9_-]{0,63}$/ }]}><Input placeholder="latest-node"/></Form.Item>
                    <Form.Item name="label" label="用户看到的问题" rules={[{ required: true }]}><Input placeholder="最新物流节点"/></Form.Item>
                    <Form.Item name="message" label="模拟发送内容" rules={[{ required: true }]}><Input placeholder="我的包裹到哪了？"/></Form.Item>
                </>}
                {editor === 'handler' && <>
                    <Form.Item name="key" label="能力标识" rules={[{ required: true, pattern: /^[a-z][a-z0-9_-]{0,63}$/ }]}><Input placeholder="logistics-query"/></Form.Item>
                    <Form.Item name="label" label="展示名称" rules={[{ required: true }]}><Input placeholder="物流查询"/></Form.Item>
                    <Form.Item name="type" label="能力类型" rules={[{ required: true }]}><Select options={handlerTypes.map(value => ({ value, label: handlerTypeLabel(value) }))}/></Form.Item>
                    <Form.Item name="priority" label="优先级"><InputNumber min={0} style={{ width: '100%' }}/></Form.Item>
                    <Form.Item noStyle shouldUpdate={(prev, next) => prev.type !== next.type}>
                        {({ getFieldValue }) => {
                            const type = getFieldValue('type') as ScenarioHandlerType;
                            if (type === 'direct') return <Form.Item name="reply" label="固定回复" rules={[{ required: true }]}><Input.TextArea rows={3}/></Form.Item>;
                            if (type === 'agent') return <Form.Item name="agent_id" label="Agent" rules={[{ required: true }]}><Select options={(agents.data || []).map(agent => ({ value: agent.id, label: `${agent.name}${agent.published_version ? ` · v${agent.published_version}` : ''}` }))}/></Form.Item>;
                            if (type === 'human') return <Form.Item name="queue" label="人工队列"><Input placeholder="order-support"/></Form.Item>;
                            if (type === 'knowledge') return null;
                            return <Form.Item name="tool" label="工具标识" extra="承载这次办理的工具接入点，决定就绪检查里的「执行能力接入」。">
                                <ProviderSelect
                                    items={toolProviderItems}
                                    loading={toolProviders.loading}
                                    placeholder="creator.work.status"
                                />
                            </Form.Item>;
                        }}
                    </Form.Item>
                    <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch defaultChecked/></Form.Item>
                </>}
            </Form>
        </Modal>
    </div>;
}

function ConfigSection({ number, title, description, meta, configured = false, children }: {
    number: string;
    title: string;
    description: string;
    meta?: string;
    configured?: boolean;
    children: ReactNode;
}) {
    return <section className="scene-config-section">
        <header>
            <span className="scene-section-number">{number}</span>
            <div><h2>{title}</h2><p>{description}</p></div>
            <span className={configured ? 'scene-section-state is-ready' : 'scene-section-state'}>{configured ? <><CheckOutlined/> {demo('已配置')}</> : meta}</span>
        </header>
        {children}
    </section>;
}

function EntryOption({ icon, title, description, active = false, onToggle }: { icon: ReactNode; title: string; description: string; active?: boolean; onToggle?: () => void }) {
    return <button type="button" className={`scene-entry-option${active ? ' is-active' : ''}`} onClick={onToggle} disabled={!onToggle} aria-pressed={active}>
        <span>{icon}</span><strong>{title}</strong><small>{description}</small>
    </button>;
}

function Decision({ title, description, badge, mutedBadge = false, disabled, onRemove }: { title: string; description: string; badge: string; mutedBadge?: boolean; disabled?: boolean; onRemove: () => void }) {
    return <article className="scene-decision">
        <span className="scene-decision-icon"><CheckOutlined/></span>
        <div><strong>{title}</strong><small>{description}</small></div>
        <span className={mutedBadge ? 'muted' : ''}>{badge}</span>
        {!disabled && <button type="button" className="scene-inline-remove" aria-label={`删除决策 ${title}`} onClick={onRemove}>×</button>}
    </article>;
}

function HandlerCard({ icon, title, description, active = false, disabled, onToggle, onEdit, onRemove }: {
    icon: ReactNode;
    title: string;
    description: string;
    active?: boolean;
    disabled?: boolean;
    onToggle: () => void;
    onEdit: () => void;
    onRemove: () => void;
}) {
    return <article className={`scene-handler${active ? ' is-active' : ''}`}>
        <header><span>{icon}</span><Switch size="small" checked={active} disabled={disabled} onChange={onToggle} aria-label={title}/></header>
        <strong>{title}</strong>
        <small>{description}</small>
        {!disabled && <footer><Button type="link" size="small" onClick={onEdit}>编辑</Button><Button type="link" size="small" danger onClick={onRemove}>移除</Button></footer>}
    </article>;
}
