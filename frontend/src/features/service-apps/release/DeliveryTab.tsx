import { useEffect, useState } from 'react';
import {
    ApartmentOutlined,
    CheckCircleFilled,
    CodeOutlined,
    ExclamationCircleFilled,
    GlobalOutlined,
    LinkOutlined,
    StopFilled,
    SyncOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Empty,
    Pagination,
    Popconfirm,
    Space,
    Spin,
    Tag,
    Tooltip,
} from 'antd';
import { toast } from '../../../shared/components/ui';
import { dateTime } from '../../../i18n';
import {
    getApplicationDelivery,
    setApplicationStatus,
    switchChannelVersion,
} from '../api';
import type {
    ApplicationDelivery,
    ApplicationDetail,
    ApplicationReadiness,
    DeliveryVersion,
} from '../contracts';
import { say } from '../labels';
import { ReadinessTag } from '../components/StatusTag';

function checkIcon(status: 'pass' | 'warning' | 'blocked') {
    if (status === 'pass') return <CheckCircleFilled className="success"/>;
    if (status === 'warning') return <ExclamationCircleFilled className="warning"/>;
    return <StopFilled className="danger"/>;
}

function DeliveryDot({ on }: { on: boolean }) {
    return <span className={`sa-delivery-dot${on ? ' on' : ''}`}/>;
}

function referenceLabel(version: DeliveryVersion) {
    const parts: string[] = [];
    if (version.channel_references > 0) {
        parts.push(say('{{v0}} 个渠道', { v0: version.channel_references }));
    }
    if (version.open_application_references > 0) {
        parts.push(say('{{v0}} 个开放平台应用', { v0: version.open_application_references }));
    }
    if (version.follows_latest_references > 0) {
        parts.push(say('{{v0}} 个开放平台应用跟随最新', {
            v0: version.follows_latest_references,
        }));
    }
    return parts.length ? parts.join(' · ') : say('无出口引用');
}

const VERSION_PAGE_SIZE = 5;
const CHANNEL_PAGE_SIZE = 5;

export function DeliveryTab({
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
    const [delivery, setDelivery] = useState<ApplicationDelivery | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');
    const [tick, setTick] = useState(0);
    const [versionPage, setVersionPage] = useState(1);
    const [channelPage, setChannelPage] = useState(1);

    useEffect(() => {
        let active = true;
        setLoading(true);
        getApplicationDelivery(application.key, versionPage, VERSION_PAGE_SIZE)
            .then(value => {
                if (!active) return;
                setDelivery(value);
                setError('');
            })
            .catch(cause => {
                if (!active) return;
                setError(cause instanceof Error ? cause.message : say('加载失败'));
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [application.key, application.published_version, tick, versionPage]);

    const currentVersion = delivery?.published_version ?? application.published_version;
    const openApps = delivery?.open_applications ?? [];
    const channels = delivery?.channels ?? [];
    const primaryOpenApp = openApps[0] ?? null;
    const channelPages = Math.max(1, Math.ceil(channels.length / CHANNEL_PAGE_SIZE));
    const safeChannelPage = Math.min(channelPage, channelPages);
    const channelSlice = channels.slice(
        (safeChannelPage - 1) * CHANNEL_PAGE_SIZE,
        safeChannelPage * CHANNEL_PAGE_SIZE,
    );
    const offline = (delivery?.status ?? application.status) === 'offline'
        || currentVersion === null;
    const blockingChecks = readiness?.checks.filter(check => check.status !== 'pass') ?? [];

    async function takeOffline() {
        setBusy('offline');
        try {
            const summary = await setApplicationStatus(
                application.key,
                'offline',
                application.draft_revision,
            );
            onSaved({ ...application, ...summary });
            setTick(value => value + 1);
            toast.success(say('已取消发布'));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy('');
        }
    }

    async function upgradeChannel(channelId: string) {
        if (currentVersion === null) return;
        setBusy(channelId);
        try {
            await switchChannelVersion(channelId, currentVersion);
            setTick(value => value + 1);
            toast.success(say('渠道已切换到 v{{v0}}', { v0: currentVersion }));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setBusy('');
        }
    }

    const createHref = `/open-platform?create=1&service_application_id=${encodeURIComponent(application.id)}`
        + (currentVersion === null ? '' : `&application_version=${currentVersion}`);
    const manageHref = primaryOpenApp
        ? `/open-platform/${primaryOpenApp.id}/embed`
        : createHref;

    if (loading && !delivery) {
        return <div className="sa-delivery-loading"><Spin/></div>;
    }

    return <div className="sa-release-tab sa-delivery-tab">
        {error && <Alert
            type="error"
            showIcon
            message={error}
            action={<Button size="small" onClick={() => setTick(value => value + 1)}>
                {say('重试')}
            </Button>}
        />}

        <section className={`sa-delivery-status${offline ? ' offline' : ''}`}>
            <div className="sa-delivery-status-main">
                {offline
                    ? <>
                        <span className="sa-delivery-status-label">{say('已下线')}</span>
                        <strong>{say('无发布版本')}</strong>
                        <span className="sa-delivery-status-hint">
                            {say('新会话将停止使用该应用；恢复上线请使用页面右上角的发布。')}
                        </span>
                    </>
                    : <>
                        <span className="sa-delivery-status-label">{say('当前发布')}</span>
                        <strong>v{currentVersion}</strong>
                        {delivery?.published_at && <span className="sa-delivery-status-hint">
                            {dateTime(delivery.published_at)} {say('发布')}
                        </span>}
                        {application.has_unpublished_changes && <>
                            <span className="sa-delivery-status-sep"/>
                            <span className="sa-delivery-status-warn">
                                {say('草稿有未发布的修改')}
                            </span>
                        </>}
                    </>}
            </div>
            <div className="sa-delivery-status-actions">
                {!offline && <Popconfirm
                    title={say('确认取消发布 v{{v0}}？', { v0: currentVersion ?? '' })}
                    description={say('取消发布后立即停止接客：开放平台与客服渠道的新会话都会被拒绝，已发布版本仍保留可追溯。')}
                    okText={say('确认取消发布')}
                    cancelText={say('取消')}
                    okButtonProps={{ danger: true }}
                    disabled={readOnly || busy !== ''}
                    onConfirm={() => void takeOffline()}
                >
                    <Button
                        className="sa-delivery-offline"
                        disabled={readOnly || busy !== ''}
                        loading={busy === 'offline'}
                    >
                        {say('取消发布')}
                    </Button>
                </Popconfirm>}
            </div>
        </section>

        <div className="sa-delivery-grid">
            <section className="sa-delivery-card">
                <div className="sa-delivery-card-head">
                    <div>
                        <span className="sa-eyebrow">{say('对外交付')}</span>
                        <h3>{say('开放平台应用')}</h3>
                    </div>
                    {primaryOpenApp
                        ? <Tag color={primaryOpenApp.enabled ? 'green' : 'default'}>
                            {primaryOpenApp.enabled ? say('已启用') : say('已停用')}
                        </Tag>
                        : <Tag>{say('未开通')}</Tag>}
                </div>

                {primaryOpenApp
                    ? <div className="sa-delivery-app">
                        <div className="sa-delivery-app-name">
                            <ApartmentOutlined/>
                            <strong>{primaryOpenApp.name}</strong>
                            <span className="sa-delivery-app-pin">
                                {primaryOpenApp.version_pin === null
                                    ? say('跟随最新发布')
                                    : say('钉定 v{{v0}}', { v0: primaryOpenApp.version_pin })}
                            </span>
                        </div>
                        <div className="sa-delivery-modes">
                            <div className="sa-delivery-mode">
                                <DeliveryDot on={primaryOpenApp.active_keys > 0}/>
                                <span>{say('API / SDK')}</span>
                                <em>{primaryOpenApp.active_keys > 0
                                    ? say('{{v0}} 个有效密钥', { v0: primaryOpenApp.active_keys })
                                    : say('未开通')}</em>
                            </div>
                            <div className="sa-delivery-mode">
                                <DeliveryDot on={primaryOpenApp.embed_enabled}/>
                                <span>{say('网页嵌入 iframe')}</span>
                                <em>{primaryOpenApp.embed_enabled
                                    ? say('已开通')
                                    : say('未开通')}</em>
                            </div>
                            <div className="sa-delivery-mode">
                                <DeliveryDot on={primaryOpenApp.hosted}/>
                                <span>{say('公开链接')}</span>
                                {primaryOpenApp.hosted
                                    ? <a
                                        className="sa-delivery-hosted"
                                        href={`/h/${primaryOpenApp.hosted_key ?? ''}`}
                                        target="_blank"
                                        rel="noreferrer"
                                        title={`${window.location.origin}/h/${primaryOpenApp.hosted_key ?? ''}`}
                                    >{`${window.location.origin}/h/${primaryOpenApp.hosted_key ?? '…'}`}</a>
                                    : <em>{say('未开通')}</em>}
                            </div>
                        </div>
                        <div className="sa-delivery-card-foot">
                            {openApps.length > 1 && <span className="sa-delivery-muted">
                                {say('另有 {{v0}} 个应用绑定此服务应用', {
                                    v0: openApps.length - 1,
                                })}
                            </span>}
                            <Button
                                type="link"
                                size="small"
                                onClick={() => onNavigate?.(manageHref)}
                            >
                                {say('管理接入方式')} →
                            </Button>
                        </div>
                    </div>
                    : <div className="sa-delivery-empty">
                        <p className="sa-delivery-empty-title">
                            {say('开放平台应用是唯一的对外容器')}
                        </p>
                        <p className="sa-delivery-muted">
                            {say('API / SDK、网页嵌入、公开链接都挂在这个应用下，未创建时三者都不可用。')}
                        </p>
                        <div className="sa-delivery-modes">
                            <div className="sa-delivery-mode">
                                <DeliveryDot on={false}/><span>{say('API / SDK')}</span>
                                <em>{say('未开通')}</em>
                            </div>
                            <div className="sa-delivery-mode">
                                <DeliveryDot on={false}/><span>{say('网页嵌入 iframe')}</span>
                                <em>{say('未开通')}</em>
                            </div>
                            <div className="sa-delivery-mode">
                                <DeliveryDot on={false}/><span>{say('公开链接')}</span>
                                <em>{say('未开通')}</em>
                            </div>
                        </div>
                        <Alert
                            type="warning"
                            showIcon
                            message={say('创建时必须绑定当前服务应用，否则只授权基础 Agent，技能、知识库与业务规则不会生效。')}
                        />
                        <Button
                            type="primary"
                            icon={<LinkOutlined/>}
                            disabled={readOnly || offline}
                            onClick={() => onNavigate?.(createHref)}
                        >
                            {currentVersion === null
                                ? say('创建并绑定')
                                : say('创建并绑定 v{{v0}}', { v0: currentVersion })}
                        </Button>
                    </div>}
            </section>

            <section className="sa-delivery-card sa-delivery-checks">
                <div className="sa-delivery-card-head">
                    <div>
                        <span className="sa-eyebrow">{say('发布前')}</span>
                        <h3>{say('发布检查')}</h3>
                    </div>
                    {readiness
                        ? <ReadinessTag status={readiness.status}/>
                        : <Tag>{readinessLoading ? say('加载中') : say('不可用')}</Tag>}
                </div>
                <p className="sa-delivery-checks-meta">
                    {readinessError
                        ? readinessError
                        : !readiness
                            ? readinessLoading ? say('加载中') : say('不可用')
                            : blockingChecks.length
                                ? say('{{v0}} 项待处理', { v0: blockingChecks.length })
                                : say('全部通过')}
                </p>
                <div className="sa-readiness-list">
                    {(readiness?.checks ?? []).map(check => <div className="sa-readiness-row" key={check.key}>
                        {checkIcon(check.status)}
                        <div>
                            <strong>{check.title}</strong>
                            <span>{check.detail}</span>
                        </div>
                        <ReadinessTag status={check.status}/>
                    </div>)}
                </div>
            </section>
        </div>

        <div className="sa-delivery-grid">
            <section className="sa-delivery-card">
                <div className="sa-delivery-card-head">
                    <div>
                        <span className="sa-eyebrow">{say('版本')}</span>
                        <h3>{say('出口引用')}</h3>
                    </div>
                    <Tooltip title={say('版本不可变；出口只引用，不随发布自动升级。')}>
                        <SyncOutlined className="sa-delivery-card-icon"/>
                    </Tooltip>
                </div>
                {delivery?.versions.length
                    ? <>
                        <div className="sa-delivery-versions">
                            {delivery.versions.map(item => <div
                                className={`sa-delivery-version-row${item.version === currentVersion ? ' current' : ''}`}
                                key={item.version}
                            >
                                <Tag color={item.version === currentVersion ? 'blue' : 'default'}>
                                    v{item.version}
                                </Tag>
                                <div className="sa-delivery-version-meta">
                                    <span>{referenceLabel(item)}</span>
                                    <em>{dateTime(item.created_at)}</em>
                                </div>
                                {item.version === currentVersion && <span className="sa-delivery-current-tag">
                                    {say('当前发布')}
                                </span>}
                            </div>)}
                        </div>
                        {delivery.version_total > delivery.version_page_size && <div className="sa-delivery-pager">
                            <Pagination
                                size="small"
                                simple
                                current={delivery.version_page}
                                pageSize={delivery.version_page_size}
                                total={delivery.version_total}
                                showSizeChanger={false}
                                onChange={page => setVersionPage(page)}
                            />
                        </div>}
                    </>
                    : <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={say('尚无发布版本')}
                    />}
            </section>

            <section className="sa-delivery-card">
                <div className="sa-delivery-card-head">
                    <div>
                        <span className="sa-eyebrow">{say('客服渠道')}</span>
                        <h3>{say('渠道版本')}</h3>
                    </div>
                    <Tag icon={<LinkOutlined/>}>{channels.length}</Tag>
                </div>
                {channels.length
                    ? <>
                        <div className="sa-delivery-channels">
                            {channelSlice.map(channel => {
                                const stale = currentVersion !== null
                                    && channel.application_version !== currentVersion;
                                return <div className="sa-delivery-channel-row" key={channel.id}>
                                    <div className="sa-delivery-channel-avatar">
                                        {channel.provider.slice(0, 1).toUpperCase()}
                                    </div>
                                    <div className="sa-delivery-channel-main">
                                        <strong>{channel.name}</strong>
                                        <span>
                                            <Tag color="blue">v{channel.application_version}</Tag>
                                            {channel.enabled
                                                ? say('启用中')
                                                : say('已禁用')}
                                            {!channel.credentials_configured && say(' · 凭据未配置')}
                                        </span>
                                    </div>
                                    {stale && <Button
                                        size="small"
                                        loading={busy === channel.id}
                                        disabled={readOnly || currentVersion === null}
                                        onClick={() => void upgradeChannel(channel.id)}
                                    >
                                        {say('升级到 v{{v0}}', { v0: currentVersion })}
                                    </Button>}
                                </div>;
                            })}
                        </div>
                    </>
                    : <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={<Space direction="vertical" size={4}>
                            <span>{say('尚未接入客服渠道')}</span>
                            <span className="sa-delivery-muted">
                                {say('企业微信、飞书、钉钉等渠道直接绑定服务应用，不需要开放平台应用。')}
                            </span>
                        </Space>}
                    />}
                <div className="sa-delivery-pager">
                    {channels.length > CHANNEL_PAGE_SIZE && <Pagination
                        size="small"
                        simple
                        current={safeChannelPage}
                        pageSize={CHANNEL_PAGE_SIZE}
                        total={channels.length}
                        showSizeChanger={false}
                        onChange={page => setChannelPage(page)}
                    />}
                    <Button
                        type="link"
                        size="small"
                        onClick={() => onNavigate?.(
                            `/open-platform/channels?application_id=${encodeURIComponent(application.id)}`,
                        )}
                    >
                        {say('在客服渠道中管理')} →
                    </Button>
                </div>
            </section>
        </div>

        {!primaryOpenApp && !offline && <p className="sa-delivery-footnote">
            <CodeOutlined/> {say('发布只生成内部版本；要让外部用户可以访问，还需要创建开放平台应用或接入客服渠道。')}
            <GlobalOutlined/> {say('公开链接属于开放平台应用，不是独立对象。')}
        </p>}
    </div>;
}
