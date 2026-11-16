import { useEffect, useState } from 'react';
import {
    CheckCircleOutlined,
    SafetyCertificateOutlined,
    SaveOutlined,
    StopOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Form,
    Input,
    Select,
    Switch,
    Table,
    Tag,
    type TableColumnsType,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import { updateApplication } from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationDetail,
    type ApplicationRules,
    type ApplicationSkill,
} from '../contracts';
import { say, skillTypeLabel } from '../labels';

interface Values {
    fallback: ApplicationRules['fallback'];
    handoff_queue: string;
    handoff_message: string;
    require_confirmation: boolean;
    preview_write_enabled: boolean;
    validate_results: boolean;
}

export function ApplicationRulesTab({
    application,
    readOnly,
    onSaved,
    onDirtyChange,
}: {
    application: ApplicationDetail;
    readOnly: boolean;
    onSaved: (application: ApplicationDetail) => void;
    onDirtyChange: (dirty: boolean) => void;
}) {
    const [form] = Form.useForm<Values>();
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        form.setFieldsValue(application.rules);
        onDirtyChange(false);
    }, [application.rules, form, onDirtyChange]);

    async function save() {
        const values = await form.validateFields();
        setBusy(true);
        try {
            const summary = await updateApplication(application.key, {
                revision: application.draft_revision,
                rules: {
                    ...application.rules,
                    ...values,
                },
            });
            onSaved({
                ...application,
                ...summary,
                rules: { ...application.rules, ...values },
            });
            toast.success(say('草稿已保存'));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    const columns: TableColumnsType<ApplicationSkill> = [
        {
            title: say('技能'),
            dataIndex: 'name',
            render: (_, skill) => <div className="sa-table-primary">
                <strong>{skill.name}</strong>
                <span className="mono">{skill.key}</span>
            </div>,
        },
        {
            title: say('类型'),
            dataIndex: 'type',
            width: 110,
            render: value => <Tag color="purple">{skillTypeLabel(value)}</Tag>,
        },
        {
            title: say('人工确认'),
            dataIndex: ['safety', 'requires_confirmation'],
            width: 120,
            render: value => value
                ? <Tag color="orange" icon={<SafetyCertificateOutlined/>}>{say('必须')}</Tag>
                : <Tag>{say('不要求')}</Tag>,
        },
        {
            title: say('最高金额'),
            dataIndex: ['safety', 'max_amount'],
            width: 120,
            render: value => value == null
                ? <span className="muted">—</span>
                : value.toLocaleString(),
        },
        {
            title: say('权限'),
            dataIndex: ['safety', 'allowed_roles'],
            render: roles => roles.length
                ? <div className="sa-safety-tags">{roles.map((role: string) => <Tag key={role}>{role}</Tag>)}</div>
                : <span className="muted">{say('不限')}</span>,
        },
        {
            title: say('幂等'),
            dataIndex: ['safety', 'idempotency'],
            width: 100,
            render: value => <Tag>{value}</Tag>,
        },
        {
            title: say('失败策略'),
            dataIndex: ['safety', 'on_error'],
            width: 120,
            render: value => <Tag color={value === 'handoff' ? 'blue' : 'red'}>
                {value === 'handoff' ? say('转人工') : say('拒绝执行')}
            </Tag>,
        },
    ];

    return <div className="sa-rules-tab">
        <Alert
            type="info"
            showIcon
            message={say('人工确认、金额、权限、幂等、超时和降级由确定性规则执行，模型只能提出调用。')}
        />
        <div className="sa-rules-layout">
            <section className="sa-rules-card">
                <div className="sa-panel-title">
                    <SafetyCertificateOutlined/>
                    <div>
                        <h3>{say('应用级规则')}</h3>
                        <p>{say('兜底和人工承接属于当前应用，发布时进入版本快照。')}</p>
                    </div>
                </div>
                <Form<Values>
                    form={form}
                    layout="vertical"
                    requiredMark={false}
                    disabled={readOnly}
                    onValuesChange={() => onDirtyChange(true)}
                >
                    <Form.Item name="fallback" label={say('兜底策略')}>
                        <Select options={[
                            { value: 'handoff', label: say('转人工') },
                            { value: 'fallback', label: say('兜底回复') },
                            { value: 'fail', label: say('直接失败') },
                        ]}/>
                    </Form.Item>
                    <Form.Item
                        noStyle
                        shouldUpdate={(previous, current) => previous.fallback !== current.fallback}
                    >
                        {({ getFieldValue }) => <Form.Item
                            name="handoff_queue"
                            label={say('人工队列')}
                            rules={getFieldValue('fallback') === 'handoff'
                                ? [{ required: true, message: say('请输入人工队列') }]
                                : []}
                        >
                            <Input className="mono" placeholder="customer-service"/>
                        </Form.Item>}
                    </Form.Item>
                    <Form.Item name="handoff_message" label={say('转人工说明')}>
                        <Input.TextArea rows={3} maxLength={1000} showCount/>
                    </Form.Item>
                    <Form.Item
                        name="require_confirmation"
                        label={say('高风险办理默认要求人工确认')}
                        valuePropName="checked"
                    >
                        <Switch/>
                    </Form.Item>
                    <Form.Item
                        name="preview_write_enabled"
                        label={say('允许草稿预览执行写操作')}
                        valuePropName="checked"
                    >
                        <Switch/>
                    </Form.Item>
                    <Form.Item
                        name="validate_results"
                        label={say('校验技能结果结构')}
                        valuePropName="checked"
                    >
                        <Switch/>
                    </Form.Item>
                    {!readOnly && <Button
                        type="primary"
                        icon={<SaveOutlined/>}
                        loading={busy}
                        onClick={() => void save()}
                    >
                        {say('保存草稿')}
                    </Button>}
                </Form>
            </section>

            <section className="sa-rules-card sa-rule-checks">
                <div className="sa-panel-title">
                    <CheckCircleOutlined/>
                    <div>
                        <h3>{say('规则检查')}</h3>
                        <p>{say('发布前检查配置完整性。')}</p>
                    </div>
                </div>
                <div className="sa-rule-check-row">
                    <Tag color="green" icon={<CheckCircleOutlined/>}>{say('人工确认')}</Tag>
                    <span>{application.rules.require_confirmation ? say('已启用') : say('未启用')}</span>
                </div>
                <div className="sa-rule-check-row">
                    <Tag color={application.rules.handoff_queue ? 'green' : 'red'} icon={<CheckCircleOutlined/>}>
                        {say('人工队列')}
                    </Tag>
                    <span>{application.rules.handoff_queue || say('尚未配置')}</span>
                </div>
                <div className="sa-rule-check-row">
                    <Tag color={application.rules.preview_write_enabled ? 'gold' : 'green'} icon={<StopOutlined/>}>
                        {say('预览写操作')}
                    </Tag>
                    <span>{application.rules.preview_write_enabled ? say('已启用') : say('默认禁用')}</span>
                </div>
                <div className="sa-rule-check-row">
                    <Tag color={application.rules.validate_results ? 'green' : 'gold'} icon={<CheckCircleOutlined/>}>
                        {say('结果校验')}
                    </Tag>
                    <span>{application.rules.validate_results ? say('已启用') : say('未启用')}</span>
                </div>
            </section>
        </div>

        <section className="sa-rules-skills">
            <div className="sa-section-head">
                <div>
                    <span className="sa-eyebrow">{say('技能级规则')}</span>
                    <h3>{say('技能级规则')}</h3>
                </div>
                <Tag>{application.skills.length} {say('技能')}</Tag>
            </div>
            <Table<ApplicationSkill>
                className="sa-ant-table"
                rowKey="id"
                columns={columns}
                dataSource={application.skills}
                size="middle"
                scroll={{ x: 900 }}
                pagination={{
                    pageSize: DEFAULT_PAGE_SIZE,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50],
                    position: ['bottomRight'],
                    hideOnSinglePage: true,
                }}
            />
        </section>
    </div>;
}
