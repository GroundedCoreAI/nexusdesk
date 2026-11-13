import { useEffect, useState } from 'react';
import {
    AppstoreOutlined,
    CheckCircleFilled,
    CustomerServiceOutlined,
    DeleteOutlined,
    FormOutlined,
    InfoCircleOutlined,
    MessageOutlined,
    PlusOutlined,
    RightOutlined,
    SafetyCertificateOutlined,
    SettingOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import {
    Alert,
    App,
    Button,
    Divider,
    Drawer,
    Input,
    Select,
    Spin,
    Switch,
    Tag,
} from 'antd';
import { getApplicationExperience, updateApplicationExperience } from '../api';
import type {
    ApplicationDetail,
    ApplicationExperience,
    ExperienceCategory,
    ExperienceComponents,
    ExperienceEntryKind,
    ServiceExperienceConfig,
} from '../contracts';
import { say } from '../labels';
import { CustomerInteractionWorkspace } from './CustomerInteractionWorkspace';
import './experience.css';

const componentDefinitions: Array<{
    key: keyof ExperienceComponents;
    name: string;
    description: string;
}> = [
    {
        key: 'quick_menu',
        name: '快捷分类',
        description: '客户无需理解技能，直接选择业务分类',
    },
    {
        key: 'suggestions',
        name: '猜你想问',
        description: '推荐问题卡片，支持换一批',
    },
    {
        key: 'order_card',
        name: '订单信息卡',
        description: '结构化展示订单、金额和物流节点',
    },
    {
        key: 'form',
        name: '业务表单',
        description: '收集退款金额、原因和补充说明',
    },
    {
        key: 'confirmation',
        name: '人工确认卡',
        description: '确认后才提交高风险写操作',
    },
    {
        key: 'receipt',
        name: '业务结果回执',
        description: '展示外部售后单号和处理状态',
    },
    {
        key: 'handoff',
        name: '转人工卡',
        description: '显示排队人数、等待时间和问题摘要',
    },
];

function categoryIcon(category: ExperienceCategory) {
    if (category.icon === 'member') return <SafetyCertificateOutlined/>;
    if (category.icon === 'order') return <AppstoreOutlined/>;
    if (category.icon === 'account') return <SettingOutlined/>;
    return <MessageOutlined/>;
}

function entryKindColor(kind: ExperienceEntryKind) {
    if (kind === 'query') return 'blue';
    if (kind === 'action') return 'purple';
    if (kind === 'handoff') return 'orange';
    return 'green';
}

function entryKindLabel(kind: ExperienceEntryKind) {
    if (kind === 'query') return '查询';
    if (kind === 'action') return '办理';
    if (kind === 'handoff') return '人工';
    return '知识';
}

function cloneExperience(experience: ServiceExperienceConfig): ServiceExperienceConfig {
    return JSON.parse(JSON.stringify(experience)) as ServiceExperienceConfig;
}

function newKey(prefix: string) {
    return `${prefix}-${Date.now().toString(36)}`;
}

export function ApplicationExperienceTab({
    application,
    readOnly,
    onChanged,
    onDirtyChange,
}: {
    application: ApplicationDetail;
    readOnly: boolean;
    onChanged: () => void;
    onDirtyChange: (dirty: boolean) => void;
}) {
    const { message } = App.useApp();
    const [data, setData] = useState<ApplicationExperience | null>(null);
    const [draft, setDraft] = useState<ServiceExperienceConfig | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [saving, setSaving] = useState(false);
    const [dirty, setDirty] = useState(false);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        getApplicationExperience(application.key)
            .then(value => {
                if (active) setData(value);
            })
            .catch(cause => {
                if (active) {
                    setError(cause instanceof Error ? cause.message : '客户交互配置加载失败');
                }
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [application.key]);

    function openEditor() {
        if (!data) return;
        setDraft(cloneExperience(data.experience));
        setDrawerOpen(true);
        setDirty(false);
        onDirtyChange(false);
    }

    function updateDraft(updater: (value: ServiceExperienceConfig) => ServiceExperienceConfig) {
        setDraft(current => current ? updater(current) : current);
        setDirty(true);
        onDirtyChange(true);
    }

    function closeEditor() {
        setDrawerOpen(false);
        setDirty(false);
        onDirtyChange(false);
    }

    function updateCategory(index: number, patch: Partial<ExperienceCategory>) {
        updateDraft(current => ({
            ...current,
            categories: current.categories.map((category, categoryIndex) =>
                categoryIndex === index ? { ...category, ...patch } : category,
            ),
        }));
    }

    function addCategory() {
        updateDraft(current => ({
            ...current,
            categories: [
                ...current.categories,
                {
                    key: newKey('category'),
                    label: '新业务分类',
                    icon: 'support',
                    tone: 'blue',
                    entries: [],
                },
            ],
        }));
    }

    function addEntry(categoryIndex: number) {
        updateDraft(current => ({
            ...current,
            categories: current.categories.map((category, index) => index === categoryIndex
                ? {
                    ...category,
                    entries: [
                        ...category.entries,
                        {
                            key: newKey('entry'),
                            label: '新服务入口',
                            kind: 'knowledge',
                            description: '',
                            binding: 'knowledge_search',
                        },
                    ],
                }
                : category),
        }));
    }

    function updateSuggestionSet(index: number, value: string) {
        updateDraft(current => ({
            ...current,
            suggestion_sets: current.suggestion_sets.map((set, setIndex) =>
                setIndex === index
                    ? value.split('\n').map(item => item.trim()).filter(Boolean)
                    : set,
            ),
        }));
    }

    async function save() {
        if (!data || !draft || data.immutable || readOnly) return;
        setSaving(true);
        try {
            const response = await updateApplicationExperience(
                application.key,
                draft,
                data.revision,
            );
            setData(response);
            setDrawerOpen(false);
            setDirty(false);
            onDirtyChange(false);
            onChanged();
            message.success('客户交互配置已保存到应用草稿');
        } catch (cause) {
            message.error(cause instanceof Error ? cause.message : '客户交互配置保存失败');
        } finally {
            setSaving(false);
        }
    }

    if (loading && !data) {
        return <div className="sa-experience-loading"><Spin/></div>;
    }
    if (error || !data) {
        return <Alert
            type="error"
            showIcon
            message={error || '客户交互配置加载失败'}
            action={<Button onClick={() => window.location.reload()}>重试</Button>}
        />;
    }

    const experience = data.experience;
    const totalEntries = experience.categories.reduce(
        (total, category) => total + category.entries.length,
        0,
    );

    return <div className="sa-experience-tab">
        <section className="sa-experience-banner">
            <div className="sa-experience-banner-icon"><CustomerServiceOutlined/></div>
            <div>
                <span className="sa-eyebrow">CUSTOMER EXPERIENCE</span>
                <h3>客户交互</h3>
                <p>
                    欢迎语、推荐问题、业务目录和交互组件保存在应用草稿，发布后进入不可变版本快照。
                    右侧真实客户画布直接调用应用预览运行，诊断信息收进运营抽屉，不再维护第二套客户界面。
                </p>
            </div>
            <div className="sa-experience-banner-tags">
                <Tag color="green">已接入后端</Tag>
                <Tag color={data.immutable ? 'purple' : 'blue'}>
                    {data.immutable ? '标准案例只读' : '随版本发布'}
                </Tag>
            </div>
        </section>

        <div className="sa-experience-layout">
            <div className="sa-experience-controls">
                <section className="sa-experience-panel">
                    <div className="sa-panel-title">
                        <AppstoreOutlined/>
                        <div>
                            <h3>客户业务目录</h3>
                            <p>入口属于应用呈现层，绑定到应用技能或人工队列。</p>
                        </div>
                        <Button type="link" disabled={readOnly || data.immutable} onClick={openEditor}>
                            {say('编辑配置')}
                        </Button>
                    </div>
                    <div className="sa-experience-stats">
                        <div><strong>{experience.categories.length}</strong><span>业务分类</span></div>
                        <div><strong>{totalEntries}</strong><span>服务入口</span></div>
                        <div><strong>{componentDefinitions.length}</strong><span>交互组件</span></div>
                    </div>
                    {experience.categories.length === 0
                        ? <Alert
                            type="info"
                            showIcon
                            message="尚未配置业务目录"
                            description="复制标准案例后会继承完整目录；也可以直接编辑当前应用配置。"
                        />
                        : <div className="sa-directory-list">
                            {experience.categories.map(category => <article
                                className="sa-directory-category"
                                key={category.key}
                            >
                                <div className={`sa-directory-icon ${category.tone}`}>
                                    {categoryIcon(category)}
                                </div>
                                <div className="sa-directory-main">
                                    <div className="sa-directory-head">
                                        <strong>{category.label}</strong>
                                        <span>{category.entries.length} 个入口</span>
                                    </div>
                                    <div className="sa-directory-entries">
                                        {category.entries.map(entry => <span key={entry.key}>
                                            {entry.label}
                                            <Tag color={entryKindColor(entry.kind)}>
                                                {entryKindLabel(entry.kind)}
                                            </Tag>
                                        </span>)}
                                    </div>
                                </div>
                                <RightOutlined className="sa-directory-arrow"/>
                            </article>)}
                        </div>}
                </section>

                <section className="sa-experience-panel">
                    <div className="sa-panel-title">
                        <ThunderboltOutlined/>
                        <div>
                            <h3>交互组件</h3>
                            <p>白名单组件由应用配置控制，并随发布快照版本化。</p>
                        </div>
                    </div>
                    <div className="sa-component-list">
                        {componentDefinitions.map(item => {
                            const enabled = experience.components[item.key];
                            return <div className="sa-component-row" key={item.key}>
                                <span className={`sa-component-check${enabled ? '' : ' muted'}`}>
                                    {enabled ? <CheckCircleFilled/> : <InfoCircleOutlined/>}
                                </span>
                                <div>
                                    <strong>{item.name}</strong>
                                    <small>{item.description}</small>
                                </div>
                                {!enabled && <Tag>{say('未启用')}</Tag>}
                                <Switch size="small" checked={enabled} disabled/>
                            </div>;
                        })}
                    </div>
                </section>

                <section className="sa-experience-panel sa-experience-guide">
                    <div className="sa-panel-title">
                        <InfoCircleOutlined/>
                        <div>
                            <h3>配置边界</h3>
                            <p>客户交互是服务应用内部能力，不新增顶层场景或能力包。</p>
                        </div>
                    </div>
                    <ol>
                        <li>标准案例的初始化数据包含四套差异化目录，用户只能复制后编辑。</li>
                        <li>草稿保存会递增修订号，发布时与技能、连接、规则一起生成版本快照。</li>
                        <li>目录入口通过 `binding` 指向技能 key 或人工队列，不复制技能实现。</li>
                        <li>客户交互与客户界面调试已合并，真实对话、版本切换和诊断共用同一套画布。</li>
                    </ol>
                </section>
            </div>

            <aside className="sa-experience-preview">
                <div className="sa-preview-heading">
                    <FormOutlined/>
                    <div>
                        <h3>{say('客户视角与实时运行')}</h3>
                        <p>{say('草稿与发布版本都使用真实应用运行；诊断信息仅通过运行记录抽屉查看。')}</p>
                    </div>
                </div>
                <CustomerInteractionWorkspace
                    application={application}
                    draftExperience={experience}
                    readOnly={readOnly || data.immutable}
                    dirty={dirty}
                    onEdit={openEditor}
                />
            </aside>
        </div>

        <Drawer
            title="编辑客户交互配置"
            width={760}
            open={drawerOpen}
            onClose={closeEditor}
            destroyOnHidden
            footer={<div className="sa-experience-drawer-footer">
                <Button onClick={closeEditor}>取消</Button>
                <Button type="primary" loading={saving} onClick={() => void save()}>
                    保存配置
                </Button>
            </div>}
        >
            {draft && <div className="sa-experience-editor">
                <section className="sa-editor-section">
                    <h3>基础信息</h3>
                    <label>
                        <span>欢迎语</span>
                        <Input.TextArea
                            rows={3}
                            maxLength={1000}
                            showCount
                            value={draft.welcome_text}
                            onChange={event => updateDraft(current => ({
                                ...current,
                                welcome_text: event.target.value,
                            }))}
                        />
                    </label>
                    <label>
                        <span>人工客服服务时间</span>
                        <Input
                            maxLength={100}
                            value={draft.service_hours}
                            onChange={event => updateDraft(current => ({
                                ...current,
                                service_hours: event.target.value,
                            }))}
                        />
                    </label>
                </section>

                <section className="sa-editor-section">
                    <h3>猜你想问</h3>
                    <p>每组最多 10 个问题，每行一个问题。</p>
                    {draft.suggestion_sets.map((set, index) => <div
                        className="sa-editor-suggestion"
                        key={`suggestion-${index}`}
                    >
                        <Input.TextArea
                            rows={3}
                            value={set.join('\n')}
                            onChange={event => updateSuggestionSet(index, event.target.value)}
                        />
                        <Button
                            danger
                            type="text"
                            icon={<DeleteOutlined/>}
                            onClick={() => updateDraft(current => ({
                                ...current,
                                suggestion_sets: current.suggestion_sets.filter(
                                    (_, setIndex) => setIndex !== index,
                                ),
                            }))}
                        />
                    </div>)}
                    <Button
                        type="dashed"
                        icon={<PlusOutlined/>}
                        onClick={() => updateDraft(current => ({
                            ...current,
                            suggestion_sets: [...current.suggestion_sets, ['新推荐问题']],
                        }))}
                    >
                        添加一组推荐问题
                    </Button>
                </section>

                <Divider/>

                <section className="sa-editor-section">
                    <div className="sa-editor-section-head">
                        <div>
                            <h3>业务目录</h3>
                            <p>分类和入口的 key 必须唯一，binding 指向技能 key 或 handoff_queue。</p>
                        </div>
                        <Button
                            type="dashed"
                            icon={<PlusOutlined/>}
                            onClick={addCategory}
                            disabled={draft.categories.length >= 8}
                        >
                            添加分类
                        </Button>
                    </div>
                    {draft.categories.map((category, categoryIndex) => <article
                        className="sa-editor-category"
                        key={`${category.key}-${categoryIndex}`}
                    >
                        <div className="sa-editor-category-head">
                            <strong>分类 {categoryIndex + 1}</strong>
                            <Button
                                danger
                                type="text"
                                icon={<DeleteOutlined/>}
                                onClick={() => updateDraft(current => ({
                                    ...current,
                                    categories: current.categories.filter(
                                        (_, index) => index !== categoryIndex,
                                    ),
                                }))}
                            />
                        </div>
                        <div className="sa-editor-grid">
                            <label>
                                <span>分类标识</span>
                                <Input
                                    className="mono"
                                    value={category.key}
                                    onChange={event => updateCategory(categoryIndex, {
                                        key: event.target.value,
                                    })}
                                />
                            </label>
                            <label>
                                <span>分类名称</span>
                                <Input
                                    value={category.label}
                                    maxLength={40}
                                    onChange={event => updateCategory(categoryIndex, {
                                        label: event.target.value,
                                    })}
                                />
                            </label>
                            <label>
                                <span>图标</span>
                                <Select
                                    value={category.icon}
                                    options={[
                                        { value: 'member', label: '会员' },
                                        { value: 'order', label: '订单' },
                                        { value: 'account', label: '账号' },
                                        { value: 'support', label: '客服' },
                                    ]}
                                    onChange={icon => updateCategory(categoryIndex, { icon })}
                                />
                            </label>
                            <label>
                                <span>色调</span>
                                <Select
                                    value={category.tone}
                                    options={[
                                        { value: 'violet', label: '紫色' },
                                        { value: 'blue', label: '蓝色' },
                                        { value: 'green', label: '绿色' },
                                        { value: 'amber', label: '琥珀色' },
                                    ]}
                                    onChange={tone => updateCategory(categoryIndex, { tone })}
                                />
                            </label>
                        </div>

                        <div className="sa-editor-entries">
                            {category.entries.map((entry, entryIndex) => <div
                                className="sa-editor-entry"
                                key={`${entry.key}-${entryIndex}`}
                            >
                                <div className="sa-editor-entry-head">
                                    <strong>入口 {entryIndex + 1}</strong>
                                    <Button
                                        danger
                                        type="text"
                                        icon={<DeleteOutlined/>}
                                        onClick={() => updateCategory(categoryIndex, {
                                            entries: category.entries.filter(
                                                (_, index) => index !== entryIndex,
                                            ),
                                        })}
                                    />
                                </div>
                                <div className="sa-editor-grid">
                                    <label>
                                        <span>入口标识</span>
                                        <Input
                                            className="mono"
                                            value={entry.key}
                                            onChange={event => updateCategory(categoryIndex, {
                                                entries: category.entries.map((item, index) =>
                                                    index === entryIndex
                                                        ? { ...item, key: event.target.value }
                                                        : item,
                                                ),
                                            })}
                                        />
                                    </label>
                                    <label>
                                        <span>服务名称</span>
                                        <Input
                                            value={entry.label}
                                            maxLength={40}
                                            onChange={event => updateCategory(categoryIndex, {
                                                entries: category.entries.map((item, index) =>
                                                    index === entryIndex
                                                        ? { ...item, label: event.target.value }
                                                        : item,
                                                ),
                                            })}
                                        />
                                    </label>
                                    <label>
                                        <span>入口类型</span>
                                        <Select
                                            value={entry.kind}
                                            options={[
                                                { value: 'query', label: '查询' },
                                                { value: 'action', label: '办理' },
                                                { value: 'knowledge', label: '知识' },
                                                { value: 'handoff', label: '人工' },
                                            ]}
                                            onChange={kind => updateCategory(categoryIndex, {
                                                entries: category.entries.map((item, index) =>
                                                    index === entryIndex
                                                        ? { ...item, kind }
                                                        : item,
                                                ),
                                            })}
                                        />
                                    </label>
                                    <label>
                                        <span>绑定目标</span>
                                        <Input
                                            className="mono"
                                            value={entry.binding}
                                            onChange={event => updateCategory(categoryIndex, {
                                                entries: category.entries.map((item, index) =>
                                                    index === entryIndex
                                                        ? { ...item, binding: event.target.value }
                                                        : item,
                                                ),
                                            })}
                                        />
                                    </label>
                                </div>
                                <label>
                                    <span>入口说明</span>
                                    <Input
                                        maxLength={200}
                                        value={entry.description}
                                        onChange={event => updateCategory(categoryIndex, {
                                            entries: category.entries.map((item, index) =>
                                                index === entryIndex
                                                    ? { ...item, description: event.target.value }
                                                    : item,
                                            ),
                                        })}
                                    />
                                </label>
                            </div>)}
                            <Button
                                type="dashed"
                                icon={<PlusOutlined/>}
                                onClick={() => addEntry(categoryIndex)}
                                disabled={category.entries.length >= 20}
                            >
                                添加服务入口
                            </Button>
                        </div>
                    </article>)}
                </section>

                <section className="sa-editor-section">
                    <h3>交互组件</h3>
                    <div className="sa-editor-components">
                        {componentDefinitions.map(item => <div key={item.key}>
                            <div>
                                <strong>{item.name}</strong>
                                <small>{item.description}</small>
                            </div>
                            <Switch
                                checked={draft.components[item.key]}
                                onChange={checked => updateDraft(current => ({
                                    ...current,
                                    components: {
                                        ...current.components,
                                        [item.key]: checked,
                                    },
                                }))}
                            />
                        </div>)}
                    </div>
                </section>
            </div>}
        </Drawer>
    </div>;
}
