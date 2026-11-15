import { useEffect, useState } from 'react';
import {
    ApiOutlined,
    CheckCircleFilled,
    CloudUploadOutlined,
    ExclamationCircleFilled,
    LinkOutlined,
    StopFilled,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Popconfirm,
    Space,
    Spin,
    Table,
    Tag,
    type TableColumnsType,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import {
    listApplicationChannels,
    setApplicationStatus,
} from '../api';
import {
    DEFAULT_PAGE_SIZE,
    type ApplicationChannelBinding,
    type ApplicationDetail,
    type ApplicationReadiness,
    type ReadinessCheck,
} from '../contracts';
import { say } from '../labels';
import { ReadinessTag } from '../components/StatusTag';

function checkIcon(status: ReadinessCheck['status']) {
    if (status === 'pass') return <CheckCircleFilled className="success"/>;
    if (status === 'warning') return <ExclamationCircleFilled className="warning"/>;
    return <StopFilled className="danger"/>;
}

export function ChannelsReleaseTab({
    application,
    readOnly,
    readiness,
    readinessLoading,
    readinessError,
    onSaved,
    onNavigate,
}: {
    application: ApplicationDetail;
    readOnly: boolean;
    readiness: ApplicationReadiness | null;
    readinessLoading: boolean;
    readinessError: string;
    onSaved: (application: ApplicationDetail) => void;
    onNavigate?: (path: string) => void;
}) {
    const [channels, setChannels] = useState<ApplicationChannelBinding[]>(application.channels);
    const [channelsLoading, setChannelsLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        let active = true;
        setChannelsLoading(true);
        listApplicationChannels(application.id)
            .then(items => {
                if (active) setChannels(items);
            })
            .catch(cause => {
                if (active) {
                    setError(cause instanceof Error ? cause.message : say('加载失败'));
                }
            })
            .finally(() => {
                if (active) setChannelsLoading(false);
            });
        return () => {
            active = false;
        };
    }, [application.id]);

    async function takeOffline() {
        setBusy(true);
        setError('');
        try {
            const summary = await setApplicationStatus(
                application.key,
                'offline',
                application.draft_revision,
            );
            onSaved({ ...application, ...summary });
            toast.success(say('应用已下线'));
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy(false);
        }
    }

    const channelColumns: TableColumnsType<ApplicationChannelBinding> = [
        {
            title: say('渠道'),
            dataIndex: 'name',
            render: (_, channel) => <div className="sa-table-primary">
                <strong>{channel.name}</strong>
                <span className="mono">{channel.provider}</span>
            </div>,
        },
        {
            title: say('启用状态'),
            dataIndex: 'enabled',
            width: 110,
            render: value => <Tag color={value ? 'green' : 'default'}>
                {value ? say('启用') : say('禁用')}
            </Tag>,
        },
        {
            title: say('钉定版本'),
            dataIndex: 'application_version',
            width: 120,
            render: value => <Tag color="blue">v{value}</Tag>,
        },
        {
            title: say('凭据'),
            dataIndex: 'credentials_configured',
            width: 120,
            render: value => <Tag color={value ? 'green' : 'gold'}>
                {value ? say('凭据已配置') : say('凭据未配置')}
            </Tag>,
        },
    ];

    return <div className="sa-release-tab">
        {error && <Alert type="error" showIcon message={error}/>}

        <div className="sa-release-top">
            <section className="sa-release-summary">
                <div className="sa-panel-title">
                    <CloudUploadOutlined/>
                    <div>
                        <h3>{say('发布')}</h3>
                        <p>{say('发布不会自动更新渠道；渠道版本在客服渠道中显式切换。')}</p>
                    </div>
                </div>
                <div className="sa-release-status">
                    <div>
                        <span>{say('当前发布')}</span>
                        <strong>
                            {application.published_version
                                ? `v${application.published_version}`
                                : '—'}
                        </strong>
                    </div>
                    <div>
                        <span>{say('草稿修订')}</span>
                        <strong>r{application.draft_revision}</strong>
                    </div>
                    <div>
                        <span>{say('渠道数量')}</span>
                        <strong>{channels.length}</strong>
                    </div>
                </div>
                {application.has_unpublished_changes && <Alert
                    type="warning"
                    showIcon
                    message={say('有未保存修改，渠道仍使用当前发布版本。')}
                />}
                {application.published_version !== null
                    && application.status !== 'offline'
                    && <Space>
                        <Popconfirm
                            title={say('确认下线当前应用？')}
                            description={say('下线后新会话将停止使用该应用，已有数据会保留。')}
                            disabled={readOnly}
                            okText={say('确认下线')}
                            cancelText={say('取消')}
                            onConfirm={() => void takeOffline()}
                        >
                            <Button
                                danger
                                icon={<StopFilled/>}
                                disabled={readOnly || busy}
                            >
                                {say('下线应用')}
                            </Button>
                        </Popconfirm>
                    </Space>}
            </section>

            <section className="sa-readiness-card">
                <div className="sa-section-head">
                    <div>
                        <h3>{say('发布检查')}</h3>
                    </div>
                    {readiness && <ReadinessTag status={readiness.status}/>}
                </div>
                {readinessError
                    ? <Alert type="error" showIcon message={readinessError}/>
                    : readinessLoading
                        ? <div className="sa-readiness-loading"><Spin size="small"/></div>
                        : readiness
                            ? <div className="sa-readiness-list">
                                {readiness.checks.map(check => <div
                                    className="sa-readiness-row"
                                    key={check.key}
                                >
                                    {checkIcon(check.status)}
                                    <div>
                                        <strong>{check.title}</strong>
                                        <span>{check.detail}</span>
                                    </div>
                                    <ReadinessTag status={check.status}/>
                                </div>)}
                            </div>
                            : <div className="sa-readiness-loading">
                                <span>{say('加载失败')}</span>
                            </div>}
            </section>
        </div>

        <section className="sa-channels-panel">
            <div className="sa-section-head">
                <div>
                    <span className="sa-eyebrow">{say('客服渠道')}</span>
                    <h3>{say('本应用渠道')}</h3>
                    <p>{say('渠道由客服渠道统一管理，此处只读展示钉定版本；切换版本请前往客服渠道。')}</p>
                </div>
                <Space wrap>
                    <Tag icon={<LinkOutlined/>}>{channels.length} {say('渠道')}</Tag>
                    {onNavigate && <Button
                        type="link"
                        onClick={() => onNavigate(
                            `/open-platform/channels?application_id=${encodeURIComponent(application.id)}`,
                        )}
                    >
                        {say('在客服渠道中管理')} →
                    </Button>}
                </Space>
            </div>
            <Table<ApplicationChannelBinding>
                className="sa-ant-table"
                rowKey="id"
                columns={channelColumns}
                dataSource={channels}
                loading={channelsLoading}
                size="middle"
                pagination={{
                    pageSize: DEFAULT_PAGE_SIZE,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50],
                    position: ['bottomRight'],
                    hideOnSinglePage: true,
                }}
                locale={{ emptyText: <div className="sa-table-empty">
                    <ApiOutlined/>
                    <span>{say('尚未接入客服渠道')}</span>
                </div> }}
            />
        </section>

    </div>;
}
