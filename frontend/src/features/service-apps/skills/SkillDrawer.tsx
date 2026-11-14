import { useEffect, useState } from 'react';
import { SaveOutlined, ThunderboltOutlined } from '@ant-design/icons';
import {
    Alert,
    Button,
    Drawer,
    Form,
    Input,
    InputNumber,
    Select,
    Space,
    Switch,
    Tabs,
    Tag,
} from 'antd';
import { toast, useResource } from '../../../shared/components/ui';
import type { KnowledgeBase } from '../../../shared/api/client';
import {
    createSkill,
    testSkill,
    updateSkill,
} from '../api';
import type {
    ApplicationConnection,
    ApplicationSkill,
    SkillInput,
    SkillSafety,
} from '../contracts';
import { skillTypeLabel, say } from '../labels';

interface Values {
    key: string;
    name: string;
    description: string;
    type: SkillInput['type'];
    enabled: boolean;
    connection_id?: string | null;
    knowledge_base_ids: string[];
    parameters_json: string;
    argument_mapping_json: string;
    result_mapping_json: string;
    result_schema_json: string;
    requires_confirmation: boolean;
    max_amount?: number | null;
    allowed_roles: string;
    idempotency: SkillSafety['idempotency'];
    timeout_seconds: number;
    on_error: SkillSafety['on_error'];
}

const emptySafety: SkillSafety = {
    requires_confirmation: false,
    max_amount: null,
    allowed_roles: [],
    idempotency: 'none',
    timeout_seconds: 10,
    on_error: 'fail',
};

function pretty(value: Record<string, unknown>) {
    return Object.keys(value).length ? JSON.stringify(value, null, 2) : '{}';
}

function parseObject(text: string, field: string) {
    try {
        const value = JSON.parse(text || '{}') as unknown;
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new Error(field);
        }
        return value as Record<string, unknown>;
    } catch {
        throw new Error(field);
    }
}

export function SkillDrawer({
    open,
    applicationKey,
    skill,
    connections,
    readOnly,
    onClose,
    onSaved,
}: {
    open: boolean;
    applicationKey: string;
    skill: ApplicationSkill | null;
    connections: ApplicationConnection[];
    readOnly: boolean;
    onClose: () => void;
    onSaved: (skill: ApplicationSkill) => void;
}) {
    const [form] = Form.useForm<Values>();
    const [activeTab, setActiveTab] = useState('basic');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const skillType = Form.useWatch('type', form) ?? skill?.type ?? 'query';
    // Retrieval is a platform capability: it has no endpoint, no argument mapping
    // and no per-call safety rule, so the drawer only asks what the runtime reads.
    const knowledgeOnly = skillType === 'knowledge';
    // Only retrieval needs the list, and only while the drawer is open.
    const bases = useResource<KnowledgeBase[]>(open && knowledgeOnly ? '/knowledge-bases' : null);
    const scopedBases = Form.useWatch('knowledge_base_ids', form) as string[] | undefined;

    useEffect(() => {
        if (!open) return;
        setActiveTab('basic');
        setError('');
        form.resetFields();
        const safety = skill?.safety || emptySafety;
        form.setFieldsValue({
            key: skill?.key || '',
            name: skill?.name || '',
            description: skill?.description || '',
            type: skill?.type || 'query',
            enabled: skill?.enabled ?? true,
            connection_id: skill?.connection_id || undefined,
            knowledge_base_ids: skill?.knowledge_base_ids || [],
            parameters_json: pretty(skill?.parameters || {}),
            argument_mapping_json: pretty(skill?.argument_mapping || {}),
            result_mapping_json: pretty(skill?.result_mapping || {}),
            result_schema_json: pretty(skill?.result_schema || {}),
            requires_confirmation: safety.requires_confirmation,
            max_amount: safety.max_amount,
            allowed_roles: safety.allowed_roles.join(', '),
            idempotency: safety.idempotency,
            timeout_seconds: safety.timeout_seconds,
            on_error: safety.on_error,
        });
    }, [form, open, skill]);

    useEffect(() => {
        if (!open || !knowledgeOnly) return;
        // One retrieval skill per application, and the backend derives the tool
        // from the type: the identifier is a label, not a configuration knob.
        if (!skill) form.setFieldValue('key', 'knowledge_search');
        setActiveTab('basic');
    }, [form, knowledgeOnly, open, skill]);

    function validateJson(values: Values) {
        const errors: Array<{ name: keyof Values; errors: string[] }> = [];
        for (const [field, label] of [
            ['parameters_json', say('参数 JSON')],
            ['argument_mapping_json', say('参数映射')],
            ['result_mapping_json', say('结果映射')],
            ['result_schema_json', say('结果')],
        ] as Array<[keyof Values, string]>) {
            try {
                parseObject(String(values[field] || '{}'), label);
            } catch {
                errors.push({ name: field, errors: [`${label}: ${say('配置必须是 JSON 对象')}`] });
            }
        }
        if (errors.length) {
            form.setFields(errors);
            throw new Error(errors[0].errors[0]);
        }
        return {
            parameters: parseObject(values.parameters_json, say('参数 JSON')),
            argument_mapping: parseObject(values.argument_mapping_json, say('参数映射')),
            result_mapping: parseObject(values.result_mapping_json, say('结果映射')),
            result_schema: parseObject(values.result_schema_json, say('结果')),
        };
    }

    async function persist(): Promise<ApplicationSkill> {
        const values = await form.validateFields();
        const knowledge = values.type === 'knowledge';
        // The platform owns retrieval's contract: the drawer must not ask an
        // operator to hand-write a schema for a tool the runtime already has.
        const objects = knowledge
            ? {
                parameters: { type: 'object', properties: {}, additionalProperties: false },
                argument_mapping: {},
                result_mapping: {},
                result_schema: { type: 'object', additionalProperties: true },
            }
            : validateJson(values);
        const safety: SkillSafety = {
            requires_confirmation: values.requires_confirmation,
            max_amount: values.max_amount ?? null,
            allowed_roles: values.allowed_roles
                .split(',')
                .map(role => role.trim())
                .filter(Boolean),
            idempotency: values.idempotency,
            timeout_seconds: values.timeout_seconds,
            on_error: values.on_error,
        };
        const input: SkillInput = {
            key: values.key.trim(),
            name: values.name.trim(),
            description: (values.description || '').trim(),
            type: values.type,
            enabled: values.enabled,
            connection_id: values.connection_id || null,
            ...objects,
            safety,
        };
        // Only retrieval searches. Sending the field on any other type would be
        // rejected by the contract, so the drawer simply leaves it off.
        if (knowledge) {
            input.knowledge_base_ids = values.knowledge_base_ids || [];
        }
        return skill
            ? updateSkill(applicationKey, skill.key, input, skill.revision)
            : createSkill(applicationKey, input);
    }

    async function save() {
        setBusy(true);
        setError('');
        try {
            const saved = await persist();
            onSaved(saved);
            toast.success(say('草稿已保存'));
            onClose();
        } catch (cause) {
            if (cause instanceof Error && cause.message) setError(cause.message);
        } finally {
            setBusy(false);
        }
    }

    async function saveAndTest() {
        setBusy(true);
        setError('');
        try {
            const saved = await persist();
            const result = await testSkill(applicationKey, saved.key);
            onSaved(saved);
            toast.success(result.status === 'passed'
                ? say('连接检测完成')
                : (result.message || say('调用失败')));
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    const basic = <div className="sa-drawer-form-grid">
        <Form.Item
            name="key"
            label={say('技能标识')}
            rules={[
                { required: true, message: say('请输入技能标识') },
                { pattern: /^[a-z][a-z0-9_]{1,63}$/, message: say('技能标识只能使用小写字母、数字和下划线') },
            ]}
        >
            <Input className="mono" disabled={Boolean(skill) || knowledgeOnly} maxLength={64}/>
        </Form.Item>
        <Form.Item
            name="name"
            label={say('名称')}
            rules={[{ required: true, message: say('请输入名称') }]}
        >
            <Input maxLength={100}/>
        </Form.Item>
        <Form.Item
            name="type"
            label={say('类型')}
            rules={[{ required: true }]}
        >
            <Select
                options={(['knowledge', 'query', 'action', 'handoff'] as const).map(type => ({
                    value: type,
                    label: skillTypeLabel(type),
                }))}
            />
        </Form.Item>
        {knowledgeOnly && <Form.Item
            className="sa-form-span-2"
            name="knowledge_base_ids"
            label={say('知识库范围')}
            extra={say('留空则继承 Agent 绑定的知识库；选中后只在这些库内检索。')}
        >
            <Select
                mode="multiple"
                allowClear
                loading={bases.loading}
                placeholder={say('继承 Agent 绑定的知识库')}
                options={(bases.data || [])
                    .filter(base => base.enabled)
                    .map(base => ({
                        value: base.id,
                        label: `${base.name} · ${base.document_count}`,
                    }))}
            />
        </Form.Item>}
        {!knowledgeOnly && <Form.Item name="connection_id" label={say('连接')}>
            <Select
                allowClear
                options={connections.map(connection => ({
                    value: connection.id,
                    label: `${connection.name} · ${connection.key}`,
                }))}
            />
        </Form.Item>}
        <Form.Item
            className="sa-form-span-2"
            name="description"
            label={say('描述')}
        >
            <Input.TextArea rows={2} maxLength={500} showCount/>
        </Form.Item>
        <Form.Item
            name="enabled"
            label={say('启用状态')}
            valuePropName="checked"
        >
            <Switch checkedChildren={say('启用')} unCheckedChildren={say('禁用')}/>
        </Form.Item>
        {skill && <Form.Item label={say('版本')}>
            <span className="mono">r{skill.revision}</span>
        </Form.Item>}
        {knowledgeOnly && <div className="sa-form-span-2">
            <Alert
                type="info"
                showIcon
                message={<Space size={6} align="start">
                    <Tag
                        color={scopedBases?.length ? 'gold' : 'geekblue'}
                        className="sa-origin-tag"
                    >
                        {scopedBases?.length ? say('本应用指定') : say('继承 Agent')}
                    </Tag>
                    <span>{say('知识检索由平台提供：标识固定、连接自动、参数由平台生成。知识库范围默认继承 Agent，也可在这里收窄。')}</span>
                </Space>}
            />
        </div>}
    </div>;

    const mapping = <div className="sa-drawer-json-grid">
        <Form.Item name="parameters_json" label={say('参数 JSON Schema')}>
            <Input.TextArea className="mono" rows={8} spellCheck={false}/>
        </Form.Item>
        <Form.Item name="argument_mapping_json" label={say('参数映射')}>
            <Input.TextArea className="mono" rows={8} spellCheck={false}/>
        </Form.Item>
        <Form.Item name="result_mapping_json" label={say('结果映射')}>
            <Input.TextArea className="mono" rows={8} spellCheck={false}/>
        </Form.Item>
        <Form.Item name="result_schema_json" label={say('结果 JSON Schema')}>
            <Input.TextArea className="mono" rows={8} spellCheck={false}/>
        </Form.Item>
    </div>;

    const safety = <div className="sa-drawer-form-grid">
        <Form.Item
            name="requires_confirmation"
            label={say('办理前会要求客户确认影响和操作内容。')}
            valuePropName="checked"
        >
            <Switch/>
        </Form.Item>
        <Form.Item name="max_amount" label={say('最高金额')}>
            <InputNumber min={0} precision={2} className="sa-full-width"/>
        </Form.Item>
        <Form.Item name="allowed_roles" label={say('允许角色（逗号分隔）')}>
            <Input placeholder="admin, operator"/>
        </Form.Item>
        <Form.Item name="idempotency" label={say('幂等')}>
            <Select options={[
                { value: 'none', label: say('不要求') },
                { value: 'optional', label: say('可选') },
                { value: 'required', label: say('必须') },
            ]}/>
        </Form.Item>
        <Form.Item name="timeout_seconds" label={say('超时（秒）')}>
            <InputNumber min={1} max={60} className="sa-full-width"/>
        </Form.Item>
        <Form.Item name="on_error" label={say('失败策略')}>
            <Select options={[
                { value: 'fail', label: say('拒绝执行') },
                { value: 'handoff', label: say('转人工') },
            ]}/>
        </Form.Item>
        <div className="sa-form-span-2">
            <Alert
                type="warning"
                showIcon
                message={say('高风险写操作必须启用人工确认，模型不能绕过这些确定性规则。')}
            />
        </div>
    </div>;

    return <Drawer
        open={open}
        width={760}
        title={skill ? `${say('编辑技能')} · ${skill.name}` : say('新建技能')}
        destroyOnHidden
        onClose={onClose}
        extra={<Space>
            <Button onClick={onClose}>{say('取消')}</Button>
            {!readOnly && skill && <Button
                icon={<ThunderboltOutlined/>}
                loading={busy}
                onClick={() => void saveAndTest()}
            >
                {say('测试连接')}
            </Button>}
            {!readOnly && <Button
                type="primary"
                icon={<SaveOutlined/>}
                loading={busy}
                onClick={() => void save()}
            >
                {say('保存')}
            </Button>}
        </Space>}
    >
        {error && <Alert type="error" showIcon message={error}/>}
        {skill?.last_test && <Alert
            className="sa-drawer-alert"
            type={skill.last_test.status === 'failed' ? 'error' : 'success'}
            showIcon
            message={skill.last_test.message || say('连接检测完成')}
        />}
        <Form<Values>
            form={form}
            layout="vertical"
            requiredMark={false}
            disabled={readOnly}
        >
            <Tabs
                activeKey={activeTab}
                onChange={setActiveTab}
                items={knowledgeOnly
                    ? [{ key: 'basic', label: say('基本信息'), children: basic }]
                    : [
                        { key: 'basic', label: say('基本信息'), children: basic },
                        { key: 'mapping', label: say('参数映射'), children: mapping },
                        { key: 'safety', label: say('安全规则'), children: safety },
                    ]}
            />
        </Form>
    </Drawer>;
}
