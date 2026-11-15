import { useEffect, useState } from 'react';
import {
    ApiOutlined,
    DeleteOutlined,
    EditOutlined,
    PlusOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Popconfirm,
    Space,
    Table,
    Tag,
    Tooltip,
    type TableColumnsType,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import {
    deleteConnection,
    listConnections,
    testConnection,
} from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationConnection,
} from '../contracts';
import { authKindLabel, connectionKindLabel, say } from '../labels';
import { ConnectionDrawer } from './ConnectionDrawer';

export function ConnectionsSection({
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
    const [items, setItems] = useState<ApplicationConnection[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    const [editing, setEditing] = useState<ApplicationConnection | null>(null);
    const [drawerOpen, setDrawerOpen] = useState(false);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        listConnections(applicationKey, page, pageSize)
            .then(result => {
                if (!active) return;
                setItems(result.items);
                setTotal(result.total);
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
    }, [applicationKey, page, pageSize, refreshKey, revision]);

    function refresh() {
        setRevision(value => value + 1);
        onChanged();
    }

    async function runTest(connection: ApplicationConnection) {
        try {
            const result = await testConnection(applicationKey, connection.key);
            toast.success(result.status === 'passed'
                ? say('连接检测完成')
                : (result.message || say('调用失败')));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        }
    }

    async function remove(connection: ApplicationConnection) {
        try {
            await deleteConnection(applicationKey, connection.key, connection.revision);
            toast.success(say('删除'));
            refresh();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('删除失败，请重试。'));
        }
    }

    const columns: TableColumnsType<ApplicationConnection> = [
        {
            title: say('连接'),
            dataIndex: 'name',
            render: (_, connection) => <div className="sa-table-primary">
                <strong>{connection.name}</strong>
                <span className="mono">{connection.key}</span>
            </div>,
        },
        {
            title: say('类型'),
            dataIndex: 'executor_kind',
            width: 120,
            render: value => <Tag>{connectionKindLabel(value)}</Tag>,
        },
        {
            title: say('接口地址'),
            dataIndex: 'endpoint',
            ellipsis: true,
            render: value => <span className="mono muted">{value || '—'}</span>,
        },
        {
            title: say('认证方式'),
            dataIndex: 'auth_kind',
            width: 130,
            render: (value, connection) => <div className="sa-credential-cell">
                <span>{authKindLabel(value)}</span>
                <Tag color={connection.credentials_configured ? 'green' : value === 'none' ? 'default' : 'gold'}>
                    {value === 'none'
                        ? say('未认证')
                        : connection.credentials_configured
                            ? say('凭据已配置')
                            : say('凭据未配置')}
                </Tag>
            </div>,
        },
        {
            title: say('超时'),
            dataIndex: 'timeout_seconds',
            width: 90,
            render: value => `${value}s`,
        },
        {
            title: say('操作'),
            key: 'actions',
            width: 150,
            fixed: 'right',
            render: (_, connection) => <Space size={2}>
                <Tooltip title={say('测试连接')}>
                    <Button
                        type="text"
                        size="small"
                        icon={<ThunderboltOutlined/>}
                        aria-label={`${say('测试连接')} ${connection.name}`}
                        disabled={readOnly}
                        onClick={() => void runTest(connection)}
                    />
                </Tooltip>
                <Tooltip title={say('编辑连接')}>
                    <Button
                        type="text"
                        size="small"
                        icon={<EditOutlined/>}
                        aria-label={`${say('编辑连接')} ${connection.name}`}
                        disabled={readOnly}
                        onClick={() => {
                            setEditing(connection);
                            setDrawerOpen(true);
                        }}
                    />
                </Tooltip>
                <Popconfirm
                    title={say('删除连接？')}
                    description={say('被技能或发布版本引用时不能删除。')}
                    disabled={readOnly}
                    okText={say('删除')}
                    cancelText={say('取消')}
                    onConfirm={() => void remove(connection)}
                >
                    <Tooltip title={say('删除连接？')}>
                        <Button
                            type="text"
                            danger
                            size="small"
                            icon={<DeleteOutlined/>}
                            aria-label={`${say('删除连接？')} ${connection.name}`}
                            disabled={readOnly}
                        />
                    </Tooltip>
                </Popconfirm>
            </Space>,
        },
    ];

    return <section className="sa-connections">
        <div className="sa-section-head">
            <div>
                <span className="sa-eyebrow">{say('应用连接')}</span>
                <h3>{say('应用连接')}</h3>
                <p>{say('连接、凭据和修改权限都属于当前应用，同名连接可在不同应用使用不同地址。')}</p>
            </div>
            <Button
                type="primary"
                ghost
                icon={<PlusOutlined/>}
                disabled={readOnly}
                onClick={() => {
                    setEditing(null);
                    setDrawerOpen(true);
                }}
            >
                {say('新建连接')}
            </Button>
        </div>
        {error && <Alert type="error" showIcon message={error}/>}
        <Table<ApplicationConnection>
            className="sa-ant-table"
            rowKey="id"
            columns={columns}
            dataSource={items}
            loading={loading}
            size="middle"
            pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50],
                position: ['bottomRight'],
                hideOnSinglePage: true,
                showTotal: count => `${count} ${say('连接')}`,
                onChange: (nextPage, nextSize) => {
                    setPage(nextPage);
                    setPageSize(nextSize);
                },
            }}
            locale={{ emptyText: <div className="sa-table-empty">
                <ApiOutlined/>
                <span>{say('还没有应用连接')}</span>
            </div> }}
        />
        <ConnectionDrawer
            open={drawerOpen}
            applicationKey={applicationKey}
            connection={editing}
            readOnly={readOnly}
            onClose={() => setDrawerOpen(false)}
            onSaved={() => refresh()}
        />
    </section>;
}
