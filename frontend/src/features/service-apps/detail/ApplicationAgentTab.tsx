import { useEffect, useMemo, useState } from 'react';
import {
    BookOutlined,
    ApiOutlined,
    RobotOutlined,
    SafetyOutlined,
} from '@ant-design/icons';
import { Alert, Button, Form, Select, Spin, Tag } from 'antd';
import type { Agent } from '../../../shared/api/client';
import { toast, useAccess, useResource } from '../../../shared/components/ui';
import { updateApplication } from '../api';
import type { ApplicationDetail } from '../contracts';
import { say } from '../labels';

interface Values {
    agent_id: string;
    agent_version: number;
}

export function ApplicationAgentTab({
    application,
    readOnly,
    onSaved,
    onDirtyChange,
    onOpenAgent,
}: {
    application: ApplicationDetail;
    readOnly: boolean;
    onSaved: (application: ApplicationDetail) => void;
    onDirtyChange: (dirty: boolean) => void;
    onOpenAgent: (agentId: string) => void;
}) {
    const { admin } = useAccess();
    const agents = useResource<Agent[]>('/agents');
    const [form] = Form.useForm<Values>();
    const [busy, setBusy] = useState(false);
    const [selectedAgentId, setSelectedAgentId] = useState(application.agent.id);

    const publishedAgents = useMemo(
        () => (agents.data || []).filter(agent => agent.published_version && !agent.archived),
        [agents.data],
    );
    const selected = publishedAgents.find(agent => agent.id === selectedAgentId);
    const selectedVersion = selected?.published_version
        ?? (selectedAgentId === application.agent.id ? application.agent.version : undefined);
    const current = (agents.data || []).find(agent => agent.id === application.agent.id);
    const editable = admin && !readOnly;

    useEffect(() => {
        form.setFieldsValue({
            agent_id: application.agent.id,
            agent_version: application.agent.version,
        });
        setSelectedAgentId(application.agent.id);
        onDirtyChange(false);
    }, [application.agent.id, application.agent.version, form, onDirtyChange]);

    async function save() {
        const values = await form.validateFields();
        setBusy(true);
        try {
            const summary = await updateApplication(application.key, {
                revision: application.draft_revision,
                agent_id: values.agent_id,
                agent_version: values.agent_version,
            });
            onSaved({ ...application, ...summary });
            toast.success(say('草稿已保存'));
            agents.refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    return <div className="sa-agent-tab">
        <Alert
            type="info"
            showIcon
            message={say('应用直接绑定一个已发布的 Agent 版本，运行时只使用该版本快照。')}
        />

        <div className="sa-agent-grid">
            <section className="sa-agent-editor">
                <div className="sa-panel-title">
                    <RobotOutlined/>
                    <div>
                        <h3>{say('智能体配置')}</h3>
                        <p>{say('选择推理与执行底座，不在这里配置技能权限。')}</p>
                    </div>
                </div>
                <Form<Values>
                    form={form}
                    layout="vertical"
                    requiredMark={false}
                    disabled={!editable}
                    onValuesChange={() => onDirtyChange(true)}
                >
                    <Form.Item
                        name="agent_id"
                        label={say('智能体')}
                        rules={[{ required: true, message: say('请选择智能体') }]}
                    >
                        <Select
                            showSearch
                            optionFilterProp="label"
                            options={publishedAgents.map(agent => ({
                                value: agent.id,
                                label: `${agent.name} · v${agent.published_version}`,
                            }))}
                            onChange={value => {
                                setSelectedAgentId(value);
                                const agent = publishedAgents.find(item => item.id === value);
                                form.setFieldValue('agent_version', agent?.published_version || 1);
                            }}
                        />
                    </Form.Item>
                    <Form.Item
                        name="agent_version"
                        label={say('应用绑定版本')}
                        rules={[{ required: true, message: say('请选择绑定版本') }]}
                    >
                        <Select
                            options={selectedVersion
                                ? [{ value: selectedVersion, label: `v${selectedVersion}` }]
                                : []}
                        />
                    </Form.Item>
                    {editable && <Button
                        type="primary"
                        loading={busy}
                        onClick={() => void save()}
                    >
                        {say('保存草稿')}
                    </Button>}
                </Form>
            </section>

            <section className="sa-agent-summary">
                <div className="sa-panel-title">
                    <SafetyOutlined/>
                    <div>
                        <h3>{say('版本摘要')}</h3>
                        <p>{say('只读展示当前绑定 Agent 的核心配置。')}</p>
                    </div>
                </div>
                {agents.loading
                    ? <Spin/>
                    : current
                        ? <>
                            <dl>
                                <dt>{say('系统提示词')}</dt>
                                <dd className="sa-prompt-preview">{current.draft.system_prompt || say('尚未配置')}</dd>
                                <dt>{say('模型配置')}</dt>
                                <dd>{current.draft.model_profile_id
                                    ? `${current.draft.model_profile_id} · v${current.draft.model_profile_version || 1}`
                                    : say('尚未配置')}</dd>
                                <dt>{say('知识')}</dt>
                                <dd>
                                    <Tag icon={<BookOutlined/>}>
                                        {current.draft.knowledge_base_ids.length} {say('知识库')}
                                    </Tag>
                                </dd>
                                <dt>{say('内置工具')}</dt>
                                <dd>
                                    <Tag icon={<ApiOutlined/>}>
                                        {current.draft.tool_names.length} {say('工具')}
                                    </Tag>
                                </dd>
                            </dl>
                            <Button
                                type="link"
                                onClick={() => onOpenAgent(current.id)}
                            >
                                {say('打开 Agent 管理')} →
                            </Button>
                        </>
                        : <Alert type="warning" showIcon message={say('当前智能体不可用，请重新选择。')}/>}
            </section>
        </div>
    </div>;
}
