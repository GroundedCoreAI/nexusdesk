import { useEffect, useState } from 'react';
import {
    DeleteOutlined,
    EditOutlined,
    PlusOutlined,
    SafetyCertificateOutlined,
    ThunderboltOutlined,
    ToolOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Input,
    Popconfirm,
    Space,
    Switch,
    Table,
    Tag,
    Tooltip,
    type TableColumnsType,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import {
    deleteSkill,
    listConnections,
    listSkills,
    testSkill,
    toggleSkill,
} from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationConnection,
    type ApplicationSkill,
} from '../contracts';
import { say, skillTypeLabel } from '../labels';
import { ConnectionsSection } from '../connections/ConnectionsSection';
import { SkillDrawer } from './SkillDrawer';

function testTag(skill: ApplicationSkill) {
    if (!skill.last_test || skill.last_test.status === 'untested') {
        return <Tag>{say('尚未测试')}</Tag>;
    }
    return <Tag color={skill.last_test.status === 'passed' ? 'green' : 'red'}>
        {skill.last_test.status === 'passed' ? say('通过') : say('失败')}
    </Tag>;
}

/**
 * Whether a run can actually call this skill.
 *
 * The list used to show "已启用" for skills that could never run, so operators
 * only discovered the gap by debugging. Executability is derived from what the
 * runtime checks: retrieval is a platform capability that needs no connection,
 * query and action need an HTTP endpoint, and a handoff has no executor yet.
 */
export function executionState(
    skill: ApplicationSkill,
    connections: ApplicationConnection[],
): { executable: boolean; reason: string } {
    if (skill.type === 'knowledge') {
        return { executable: true, reason: say('由平台内置的知识检索提供，无需连接。') };
    }
    if (skill.type === 'handoff') {
        return { executable: false, reason: say('转人工技能尚未接入执行器，运行时会跳过。') };
    }
    const connection = connections.find(item => item.id === skill.connection_id);
    if (!connection) {
        return { executable: false, reason: say('技能没有绑定连接，运行时会跳过。') };
    }
    if (connection.executor_kind !== 'http') {
        return { executable: false, reason: say('该连接的执行方式不是 HTTP，运行时会跳过。') };
    }
    if (!connection.endpoint) {
        return { executable: false, reason: say('连接缺少服务地址，运行时会跳过。') };
    }
    return { executable: true, reason: connection.endpoint };
}

function executionTag(state: { executable: boolean; reason: string }) {
    return state.executable
        ? <Tooltip title={state.reason}><Tag color="green">{say('可执行')}</Tag></Tooltip>
        : <Tooltip title={state.reason}><Tag>{say('未接入')}</Tag></Tooltip>;
}

/**
 * Where a skill's behaviour comes from.
 *
 * Tool authorization is not inherited any more — the release's own skills decide
 * what a run may call. What can still be inherited is the retrieval scope: a
 * knowledge skill that names no bases searches whatever the Agent is bound to.
 * Once it names bases, the release has taken that decision away from the Agent,
 * and the tag says so — two applications on one Agent can then search differently.
 */
function originTag(skill: ApplicationSkill) {
    if (skill.type === 'knowledge') {
        const scoped = skill.knowledge_base_ids?.length || 0;
        return <Tooltip title={scoped
            ? say('已指定 {{v0}} 个知识库，只在这些库内检索。', { v0: scoped })
            : say('平台内置技能：标识固定、无需连接，检索范围继承 Agent 绑定的知识库。')}>
            <Tag color={scoped ? 'gold' : 'geekblue'}>
                {scoped ? say('本应用指定') : say('继承 Agent')}
            </Tag>
        </Tooltip>;
    }
    return <Tag>{say('应用自建')}</Tag>;
}

export function SkillsTab({
    applicationKey,
    readOnly,
    refreshKey,
    onChanged,
}: {
    applicationKey: string;
    readOnly: boolean;
    refreshKey: number;
    onChanged: () => void;
}) {
    const [items, setItems] = useState<ApplicationSkill[]>([]);
    const [connections, setConnections] = useState<ApplicationConnection[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    const [editing, setEditing] = useState<ApplicationSkill | null>(null);
    const [drawerOpen, setDrawerOpen] = useState(false);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        Promise.all([
            listSkills(applicationKey, page, pageSize, query.trim()),
            listConnections(applicationKey, 1, 100),
        ])
            .then(([skills, connectionPage]) => {
                if (!active) return;
                setItems(skills.items);
                setTotal(skills.total);
                setConnections(connectionPage.items);
            })
            .catch(cause => {
                if (active) setError(cause instanceof Error ? cause.message : say('加载失败'));
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [applicationKey, page, pageSize, query, refreshKey, revision]);

    function refresh() {
        setRevision(value => value + 1);
        onChanged();
    }

    async function toggle(skill: ApplicationSkill, enabled: boolean) {
        try {
            await toggleSkill(applicationKey, skill.key, enabled, skill.revision);
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        }
    }

    async function runTest(skill: ApplicationSkill) {
        try {
            const result = await testSkill(applicationKey, skill.key);
            toast.success(result.status === 'passed'
                ? say('连接检测完成')
                : (result.message || say('调用失败')));
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('调用失败'));
        }
    }

    async function remove(skill: ApplicationSkill) {
        try {
            await deleteSkill(applicationKey, skill.key, skill.revision);
            toast.success(say('删除'));
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('删除失败，请重试。'));
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
            title: say('来源'),
            key: 'origin',
            width: 120,
            render: (_, skill) => originTag(skill),
        },
        {
            title: say('运行'),
            key: 'executable',
            width: 100,
            render: (_, skill) => executionTag(executionState(skill, connections)),
        },
        {
            title: say('连接'),
            dataIndex: 'connection_id',
            width: 180,
            render: (_, skill) => skill.connection_name
                ? <div className="sa-table-primary compact">
                    <strong>{skill.connection_name}</strong>
                    <span className="mono">{skill.connection_key}</span>
                </div>
                : <span className="muted">{say('未连接')}</span>,
        },
        {
            title: say('启用状态'),
            dataIndex: 'enabled',
            width: 100,
            render: (_, skill) => <Switch
                size="small"
                checked={skill.enabled}
                disabled={readOnly}
                onChange={checked => void toggle(skill, checked)}
            />,
        },
        {
            title: say('最近测试'),
            key: 'test',
            width: 110,
            render: (_, skill) => testTag(skill),
        },
        {
            title: say('安全规则'),
            key: 'safety',
            width: 180,
            render: (_, skill) => <div className="sa-safety-tags">
                {skill.safety.requires_confirmation && <Tag icon={<SafetyCertificateOutlined/>} color="orange">
                    {say('人工确认')}
                </Tag>}
                <Tag>{skill.safety.on_error === 'handoff' ? say('转人工') : say('拒绝执行')}</Tag>
                <Tag>{skill.safety.timeout_seconds}s</Tag>
            </div>,
        },
        {
            title: say('操作'),
            key: 'actions',
            width: 130,
            fixed: 'right',
            render: (_, skill) => <Space size={2}>
                <Tooltip title={say('测试技能')}>
                    <Button
                        type="text"
                        size="small"
                        icon={<ThunderboltOutlined/>}
                        aria-label={`${say('测试技能')} ${skill.name}`}
                        disabled={readOnly}
                        onClick={() => void runTest(skill)}
                    />
                </Tooltip>
                <Tooltip title={say('编辑技能')}>
                    <Button
                        type="text"
                        size="small"
                        icon={<EditOutlined/>}
                        aria-label={`${say('编辑技能')} ${skill.name}`}
                        disabled={readOnly}
                        onClick={() => {
                            setEditing(skill);
                            setDrawerOpen(true);
                        }}
                    />
                </Tooltip>
                <Popconfirm
                    title={say('删除技能？')}
                    disabled={readOnly}
                    okText={say('删除')}
                    cancelText={say('取消')}
                    onConfirm={() => void remove(skill)}
                >
                    <Tooltip title={say('删除技能？')}>
                        <Button
                            type="text"
                            danger
                            size="small"
                            icon={<DeleteOutlined/>}
                            aria-label={`${say('删除技能？')} ${skill.name}`}
                            disabled={readOnly}
                        />
                    </Tooltip>
                </Popconfirm>
            </Space>,
        },
    ];

    const executableCount = items.filter(
        skill => executionState(skill, connections).executable,
    ).length;
    const inheritedCount = items.filter(
        skill => skill.type === 'knowledge' && !skill.knowledge_base_ids?.length,
    ).length;
    const scopedCount = items.filter(
        skill => skill.type === 'knowledge' && Boolean(skill.knowledge_base_ids?.length),
    ).length;

    return <div className="sa-skills-tab">
        <section className="sa-skills-panel">
            <div className="sa-section-head">
                <div>
                    <span className="sa-eyebrow">{say('技能')}</span>
                    <h3>{say('技能')}</h3>
                    <p>{say('技能直接属于应用，只能使用本应用连接；发布时固定当前配置。')}</p>
                    <p className="sa-skill-execution-summary">
                        {say('本页 {{v0}} 个可执行 · {{v1}} 个未接入', {
                            v0: executableCount,
                            v1: items.length - executableCount,
                        })}
                    </p>
                    {items.length > executableCount && <p className="sa-skill-execution-hint">
                        {say('未接入的技能可以保存和发布，但运行时不会调用；调整连接后即可执行。')}
                    </p>}
                    {inheritedCount > 0 && <p className="sa-skill-origin-hint">
                        {say('{{v0}} 个技能继承自 Agent：检索范围沿用 Agent 绑定的知识库，本页不单独设置。', {
                            v0: inheritedCount,
                        })}
                    </p>}
                    {scopedCount > 0 && <p className="sa-skill-origin-hint">
                        {say('{{v0}} 个技能已指定知识库：只在这些库内检索，不再跟随 Agent。', {
                            v0: scopedCount,
                        })}
                    </p>}
                </div>
                <Space>
                    <Input
                        allowClear
                        aria-label={say('搜索名称')}
                        value={query}
                        placeholder={say('搜索名称')}
                        onChange={event => {
                            setQuery(event.target.value);
                            setPage(1);
                        }}
                    />
                    <Button
                        type="primary"
                        icon={<PlusOutlined/>}
                        disabled={readOnly}
                        onClick={() => {
                            setEditing(null);
                            setDrawerOpen(true);
                        }}
                    >
                        {say('新建技能')}
                    </Button>
                </Space>
            </div>
            {error && <Alert type="error" showIcon message={error}/>}
            <Table<ApplicationSkill>
                className="sa-ant-table"
                rowKey="id"
                columns={columns}
                dataSource={items}
                loading={loading}
                size="middle"
                scroll={{ x: 1200 }}
                pagination={{
                    current: page,
                    pageSize,
                    total,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50],
                    position: ['bottomRight'],
                    hideOnSinglePage: true,
                    showTotal: count => `${count} ${say('技能')}`,
                    onChange: (nextPage, nextSize) => {
                        setPage(nextPage);
                        setPageSize(nextSize);
                    },
                }}
                locale={{ emptyText: <div className="sa-table-empty">
                    <ToolOutlined/>
                    <span>{say('还没有技能')}</span>
                </div> }}
            />
        </section>

        <ConnectionsSection
            applicationKey={applicationKey}
            readOnly={readOnly}
            refreshKey={refreshKey}
            onChanged={refresh}
        />

        <SkillDrawer
            open={drawerOpen}
            applicationKey={applicationKey}
            skill={editing}
            connections={connections}
            readOnly={readOnly}
            onClose={() => setDrawerOpen(false)}
            onSaved={() => refresh()}
        />
    </div>;
}
