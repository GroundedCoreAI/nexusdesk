import { dateTime, t } from '../../i18n/index';
import { useEffect, useState } from 'react';
import {
    patch,
    post,
    put,
    type ChannelDelivery,
    type ChannelField,
    type ChannelProvider,
} from '../../shared/api/client';
import {
    Alert,
    Empty,
    Field,
    Panel,
    useAccess,
    useAction,
    useResource,
} from '../../shared/components/ui';
import {
    Button,
    Modal,
    Select,
    Space,
    Table,
    Tag,
    type TableColumnsType,
} from 'antd';
import './channels.css';

interface ChannelV2 {
    id: string;
    name: string;
    application_id: string;
    application_key?: string | null;
    application_name?: string | null;
    application_version: number;
    enabled: boolean;
    provider: string;
    config: Record<string, unknown>;
    credentials_configured: boolean;
    last_error_code?: string | null;
    last_activity_at?: string | null;
    token?: string | null;
}

interface PublishedApplication {
    id: string;
    key: string;
    name: string;
    published_version: number | null;
}

interface PublishedApplicationPage {
    items: PublishedApplication[];
    total: number;
    page: number;
    page_size: number;
}

interface ApplicationVersion {
    version: number;
    current?: boolean;
    published?: boolean;
}

interface ApplicationVersionPage {
    items: ApplicationVersion[];
    published_version?: number | null;
    total: number;
    page: number;
    page_size: number;
}

function ProviderInput({
    field,
    value,
    onChange,
}: {
    field: ChannelField;
    value: string;
    onChange: (value: string) => void;
}) {
    if (field.type === 'select') {
        return (
            <select
                required={field.required}
                value={value}
                onChange={event => onChange(event.target.value)}
            >
                <option value="">{t('请选择')}</option>
                {field.options?.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                ))}
            </select>
        );
    }
    return (
        <input
            required={field.required}
            type={field.secret ? 'password' : 'text'}
            value={value}
            onChange={event => onChange(event.target.value)}
            autoComplete="off"
        />
    );
}

function ProviderFields({
    fields,
    values,
    onChange,
    credentials = false,
}: {
    fields: ChannelField[];
    values: Record<string, string>;
    onChange: (name: string, value: string) => void;
    credentials?: boolean;
}) {
    return <>{fields.map(field => {
        const effective = credentials && field.secret
            ? { ...field, required: false }
            : field;
        return (
            <Field
                key={field.name}
                label={`${field.label}${effective.required ? '' : t('（可选）')}`}
            >
                <ProviderInput
                    field={effective}
                    value={values[field.name] || ''}
                    onChange={value => onChange(field.name, value)}
                />
            </Field>
        );
    })}</>;
}

function DeliveryList({ channelId }: { channelId: string }) {
    const rows = useResource<{ items: ChannelDelivery[]; total: number }>(
        `/channels/${channelId}/deliveries`,
        5000,
    );
    return (
        <div className="channel-delivery-list">
            <Alert error={rows.error}/>
            {!rows.loading && !rows.data?.items.length && <Empty>{t('暂无投递记录')}</Empty>}
            {rows.data?.items.map(item => (
                <article className="tool-item" key={item.id}>
                    <div className="row">
                        <strong>{item.role}</strong>
                        <span className={`badge ${item.status}`}>{item.status}</span>
                    </div>
                    <p className="mono small">{item.message_id}</p>
                    <p className="hint">
                        {t('尝试次数')}: {item.attempts}
                        {item.http_status ? ` · HTTP ${item.http_status}` : ''}
                        {item.error_code ? ` · ${item.error_code}` : ''}
                    </p>
                </article>
            ))}
        </div>
    );
}

export function ChannelsPage() {
    const rows = useResource<ChannelV2[]>('/channels');
    const applications = useResource<PublishedApplicationPage>(
        '/service-apps?page=1&page_size=100&status=published',
    );
    const providers = useResource<ChannelProvider[]>('/channels/providers');
    const action = useAction();
    const { admin } = useAccess();
    const [provider, setProvider] = useState('generic_webhook');
    const [signing, setSigning] = useState('');
    const [name, setName] = useState('');
    const [applicationId, setApplicationId] = useState('');
    const [applicationVersion, setApplicationVersion] = useState<number | null>(null);
    const [config, setConfig] = useState<Record<string, string>>({});
    const [credentials, setCredentials] = useState<Record<string, string>>({});
    const [created, setCreated] = useState<ChannelV2 | null>(null);
    const [editing, setEditing] = useState<ChannelV2 | null>(null);
    const [editConfig, setEditConfig] = useState<Record<string, string>>({});
    const [editCredentials, setEditCredentials] = useState<Record<string, string>>({});
    const [deliveriesFor, setDeliveriesFor] = useState('');
    const [switching, setSwitching] = useState<ChannelV2 | null>(null);
    const [targetVersion, setTargetVersion] = useState<number | null>(null);

    const selectedProvider = providers.data?.find(item => item.id === provider);
    const publishedApplications = (applications.data?.items || [])
        .filter(item => item.published_version !== null);
    const selectedApplication = publishedApplications.find(item => item.id === applicationId);
    const createVersions = useResource<ApplicationVersionPage>(
        selectedApplication
            ? `/service-apps/${encodeURIComponent(selectedApplication.key)}/versions?page=1&page_size=100`
            : null,
    );
    const switchVersions = useResource<ApplicationVersionPage>(
        switching?.application_key
            ? `/service-apps/${encodeURIComponent(switching.application_key)}/versions?page=1&page_size=100`
            : null,
    );
    const native = provider !== 'generic_webhook';
    const providerName = (value: string) =>
        providers.data?.find(item => item.id === value)?.name || value;

    useEffect(() => {
        setApplicationVersion(selectedApplication?.published_version ?? null);
    }, [selectedApplication?.id, selectedApplication?.published_version]);

    function chooseProvider(value: string) {
        const definition = providers.data?.find(item => item.id === value);
        setProvider(value);
        setConfig(Object.fromEntries(
            (definition?.config_fields || []).map(field => [field.name, field.default || '']),
        ));
        setCredentials({});
        setSigning('');
    }

    function beginEdit(channel: ChannelV2) {
        setEditing(channel);
        setEditConfig(Object.fromEntries(
            Object.entries(channel.config || {}).map(([key, value]) => [key, String(value ?? '')]),
        ));
        setEditCredentials({});
    }

    function beginSwitch(channel: ChannelV2) {
        setSwitching(channel);
        setTargetVersion(channel.application_version);
    }

    function applicationName(channel: ChannelV2) {
        return channel.application_name
            || publishedApplications.find(item => item.id === channel.application_id)?.name
            || channel.application_key
            || channel.application_id;
    }

    const columns: TableColumnsType<ChannelV2> = [
        {
            title: t('渠道'),
            key: 'channel',
            width: 220,
            render: (_, channel) => (
                <div className="channel-primary-cell">
                    <strong>{channel.name}</strong>
                    <span>{providerName(channel.provider)}</span>
                    <code>{channel.id}</code>
                </div>
            ),
        },
        {
            title: t('服务应用'),
            key: 'application',
            width: 230,
            render: (_, channel) => (
                <div className="channel-application-cell">
                    <strong>{applicationName(channel)}</strong>
                    <Tag color="blue">v{channel.application_version}</Tag>
                </div>
            ),
        },
        {
            title: t('状态'),
            key: 'status',
            width: 170,
            render: (_, channel) => (
                <Space size={4} wrap>
                    <Tag color={channel.enabled ? 'green' : 'default'}>
                        {channel.enabled ? t('已启用') : t('已停用')}
                    </Tag>
                    <Tag color={channel.credentials_configured ? 'green' : 'gold'}>
                        {channel.credentials_configured ? t('凭据已配置') : t('凭据未配置')}
                    </Tag>
                </Space>
            ),
        },
        {
            title: t('最近活动'),
            dataIndex: 'last_activity_at',
            width: 180,
            render: value => value ? dateTime(String(value)) : '—',
        },
        {
            title: t('操作'),
            key: 'actions',
            width: 330,
            render: (_, channel) => (
                <Space size={2} wrap className="channel-actions">
                    <Button
                        type="link"
                        size="small"
                        disabled={!admin || action.busy}
                        onClick={() => void action.run(async () => {
                            await patch(`/channels/${channel.id}`, {
                                enabled: !channel.enabled,
                            });
                            rows.refresh();
                        })}
                    >
                        {channel.enabled ? t('停用') : t('启用')}
                    </Button>
                    {channel.provider === 'generic_webhook' && (
                        <Button
                            type="link"
                            size="small"
                            disabled={!admin || action.busy}
                            onClick={() => void action.run(async () => {
                                setCreated(await post<ChannelV2>(
                                    `/channels/${channel.id}/rotate-token`,
                                ));
                                rows.refresh();
                            }, t('已轮换，旧令牌立即失效'))}
                        >
                            {t('轮换渠道令牌')}
                        </Button>
                    )}
                    {channel.provider !== 'generic_webhook' && (
                        <Button
                            type="link"
                            size="small"
                            disabled={!admin || action.busy}
                            onClick={() => beginEdit(channel)}
                        >
                            {t('配置凭据')}
                        </Button>
                    )}
                    <Button
                        type="link"
                        size="small"
                        disabled={!admin || action.busy || !channel.application_key}
                        onClick={() => beginSwitch(channel)}
                    >
                        {t('切换应用版本')}
                    </Button>
                    <Button
                        type="link"
                        size="small"
                        onClick={() => setDeliveriesFor(
                            deliveriesFor === channel.id ? '' : channel.id,
                        )}
                    >
                        {deliveriesFor === channel.id ? t('收起投递记录') : t('查看投递记录')}
                    </Button>
                </Space>
            ),
        },
    ];

    return (
        <div className="channel-workspace channel-v2">
            <Alert
                error={rows.error
                    || applications.error
                    || createVersions.error
                    || providers.error
                    || action.error}
                notice={action.notice}
            />
            <div className="channel-v2-layout">
                <Panel
                    title={t('接入渠道')}
                    action={(
                        <Button onClick={rows.refresh} loading={rows.loading}>
                            {t('刷新')}
                        </Button>
                    )}
                >
                    <p className="hint channel-version-note">
                        {t('渠道固定使用一个已发布应用版本，切换后仅影响后续入站消息。')}
                    </p>
                    <Table<ChannelV2>
                        className="channel-table"
                        rowKey="id"
                        columns={columns}
                        dataSource={rows.data || []}
                        loading={rows.loading}
                        pagination={{
                            defaultPageSize: 10,
                            showSizeChanger: false,
                            position: ['bottomRight'],
                            hideOnSinglePage: false,
                            showTotal: total => t('共 {{v0}} 条', { v0: total }),
                        }}
                        scroll={{ x: 1130 }}
                        locale={{
                            emptyText: <Empty>{t('创建渠道接入业务系统')}</Empty>,
                        }}
                        expandable={{
                            expandedRowKeys: deliveriesFor ? [deliveriesFor] : [],
                            expandedRowRender: channel => (
                                deliveriesFor === channel.id
                                    ? <DeliveryList channelId={channel.id}/>
                                    : null
                            ),
                            showExpandColumn: false,
                        }}
                    />
                </Panel>

                <div className="channel-v2-side">
                    <Panel title={t('创建渠道')}>
                        <form onSubmit={event => {
                            event.preventDefault();
                            if (!applicationId || applicationVersion === null) return;
                            void action.run(async () => {
                                const body = native
                                    ? {
                                        name,
                                        application_id: applicationId,
                                        application_version: applicationVersion,
                                        provider,
                                        config,
                                        credentials,
                                    }
                                    : {
                                        name,
                                        application_id: applicationId,
                                        application_version: applicationVersion,
                                        provider,
                                        signing_secret_ref: signing || null,
                                    };
                                setCreated(await post<ChannelV2>('/channels', body));
                                rows.refresh();
                                setName('');
                            }, native
                                ? t('渠道已创建，请完成平台回调配置')
                                : t('渠道已创建，请保存本次显示的令牌'));
                        }}>
                            <fieldset disabled={!admin || action.busy}>
                                <Field label={t('渠道名称')}>
                                    <input
                                        required
                                        value={name}
                                        onChange={event => setName(event.target.value)}
                                    />
                                </Field>
                                <Field label={t('已发布服务应用')}>
                                    <Select
                                        aria-label={t('已发布服务应用')}
                                        showSearch
                                        optionFilterProp="label"
                                        value={applicationId || undefined}
                                        placeholder={t('请选择已发布服务应用')}
                                        loading={applications.loading}
                                        notFoundContent={t('暂无已发布服务应用')}
                                        disabled={!admin || action.busy}
                                        options={publishedApplications.map(item => ({
                                            value: item.id,
                                            label: item.name,
                                        }))}
                                        onChange={value => {
                                            setApplicationId(value);
                                            const app = publishedApplications.find(
                                                item => item.id === value,
                                            );
                                            setApplicationVersion(app?.published_version ?? null);
                                        }}
                                    />
                                </Field>
                                {!publishedApplications.length && !applications.loading && (
                                    <p className="hint channel-no-application">
                                        {t('请先发布服务应用后再创建渠道')}
                                    </p>
                                )}
                                <Field label={t('应用版本')}>
                                    <Select
                                        aria-label={t('应用版本')}
                                        value={applicationVersion ?? undefined}
                                        placeholder={t('选择应用版本')}
                                        loading={createVersions.loading}
                                        disabled={!admin
                                            || action.busy
                                            || !selectedApplication
                                            || createVersions.loading}
                                        options={(createVersions.data?.items || []).map(item => ({
                                            value: item.version,
                                            label: `v${item.version}${item.current ? ` · ${t('当前版本')}` : ''}`,
                                        }))}
                                        onChange={setApplicationVersion}
                                    />
                                </Field>
                                <Field label={t('渠道类型')}>
                                    <select
                                        required
                                        value={provider}
                                        onChange={event => chooseProvider(event.target.value)}
                                    >
                                        {providers.data?.map(item => (
                                            <option key={item.id} value={item.id}>{item.name}</option>
                                        ))}
                                    </select>
                                </Field>
                                {native && selectedProvider && (
                                    <>
                                        <ProviderFields
                                            fields={selectedProvider.config_fields}
                                            values={config}
                                            onChange={(key, value) => setConfig(
                                                old => ({ ...old, [key]: value }),
                                            )}
                                        />
                                        <ProviderFields
                                            fields={selectedProvider.credential_fields}
                                            values={credentials}
                                            onChange={(key, value) => setCredentials(
                                                old => ({ ...old, [key]: value }),
                                            )}
                                        />
                                    </>
                                )}
                                {!native && (
                                    <Field label={t('签名密钥环境变量引用（可选）')}>
                                        <input
                                            value={signing}
                                            onChange={event => setSigning(event.target.value)}
                                            placeholder="AGENT_CHANNEL_SECRET_WEBHOOK"
                                        />
                                    </Field>
                                )}
                                <Button
                                    type="primary"
                                    htmlType="submit"
                                    block
                                    disabled={!admin
                                        || action.busy
                                        || !name.trim()
                                        || !applicationId
                                        || applicationVersion === null}
                                >
                                    {t('创建渠道')}
                                </Button>
                            </fieldset>
                        </form>
                    </Panel>

                    {editing && (
                        <Panel title={`${providerName(editing.provider)} · ${t('配置')}`}>
                            <form onSubmit={event => {
                                event.preventDefault();
                                void action.run(async () => {
                                    await post(`/channels/${editing.id}/config`, {
                                        config: editConfig,
                                        credentials: editCredentials,
                                    });
                                    setEditing(null);
                                    rows.refresh();
                                }, t('渠道配置已保存'));
                            }}>
                                <fieldset disabled={!admin || action.busy}>
                                    <ProviderFields
                                        fields={providers.data?.find(item => item.id === editing.provider)
                                            ?.config_fields || []}
                                        values={editConfig}
                                        onChange={(key, value) => setEditConfig(
                                            old => ({ ...old, [key]: value }),
                                        )}
                                    />
                                    <ProviderFields
                                        fields={providers.data?.find(item => item.id === editing.provider)
                                            ?.credential_fields || []}
                                        values={editCredentials}
                                        credentials
                                        onChange={(key, value) => setEditCredentials(
                                            old => ({ ...old, [key]: value }),
                                        )}
                                    />
                                    <button>{t('保存配置')}</button>
                                    <button
                                        type="button"
                                        className="secondary"
                                        onClick={() => setEditing(null)}
                                    >
                                        {t('取消')}
                                    </button>
                                </fieldset>
                            </form>
                        </Panel>
                    )}

                    {created && (
                        <Panel title={created.token ? t('本次创建的访问令牌') : t('渠道配置信息')}>
                            {created.token ? (
                                <>
                                    <p className="hint">{t('令牌仅显示这一次。服务端只保存摘要。')}</p>
                                    <code className="secret">{created.token}</code>
                                    <p className="small mono">
                                        POST /api/v1/ingress/channels/{created.id}/messages
                                    </p>
                                </>
                            ) : (
                                <>
                                    <p>{t('请在对应聊天软件中配置以下回调地址：')}</p>
                                    <code className="secret">
                                        /api/v1/ingress/channels/{created.id}/webhook/{created.provider}
                                    </code>
                                </>
                            )}
                        </Panel>
                    )}

                    <Panel title={t('接入说明')}>
                        <p className="hint">
                            {native
                                ? t('服务应用和人工回复会通过出站投递 Worker 主动发送。')
                                : t('通用 Webhook 使用渠道 Token；回复通过 replies 接口按 seq 拉取。')}
                        </p>
                    </Panel>
                </div>
            </div>

            <Modal
                open={Boolean(switching)}
                title={`${t('切换应用版本')}${switching ? ` · ${switching.name}` : ''}`}
                okText={t('切换应用版本')}
                cancelText={t('取消')}
                confirmLoading={action.busy}
                okButtonProps={{
                    disabled: targetVersion === null
                        || targetVersion === switching?.application_version,
                }}
                onCancel={() => {
                    if (!action.busy) setSwitching(null);
                }}
                onOk={() => {
                    if (!switching || targetVersion === null) return;
                    void action.run(async () => {
                        await put(`/channels/${switching.id}/application-version`, {
                            application_version: targetVersion,
                        });
                        rows.refresh();
                        setSwitching(null);
                    }, t('应用版本已切换'));
                }}
            >
                <p className="hint">
                    {t('渠道固定使用一个已发布应用版本，切换后仅影响后续入站消息。')}
                </p>
                {switchVersions.error && <Alert error={switchVersions.error}/>}
                <Field label={t('应用版本')}>
                    <Select
                        aria-label={t('应用版本')}
                        value={targetVersion ?? undefined}
                        placeholder={t('选择应用版本')}
                        loading={switchVersions.loading}
                        disabled={switchVersions.loading || !switching?.application_key}
                        options={(switchVersions.data?.items || []).map(item => ({
                            value: item.version,
                            label: `v${item.version}${item.current ? ` · ${t('当前版本')}` : ''}`,
                        }))}
                        onChange={setTargetVersion}
                    />
                </Field>
                {!switchVersions.loading && !switchVersions.data?.items.length && (
                    <p className="hint">{t('无法加载应用版本')}</p>
                )}
            </Modal>
        </div>
    );
}
