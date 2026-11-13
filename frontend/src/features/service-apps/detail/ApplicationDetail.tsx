import { useEffect, useMemo, useState } from 'react';
import {
    ApiOutlined,
    ArrowLeftOutlined,
    CheckOutlined,
    CloseOutlined,
    CloudUploadOutlined,
    DownOutlined,
    EditOutlined,
} from '@ant-design/icons';
import { Alert, Button, Input, Popconfirm, Popover, Spin, Tabs, Tag, Tooltip } from 'antd';
import { toast, useAccess } from '../../../shared/components/ui';
import {
    getApplication,
    getApplicationReadiness,
    publishApplication,
    updateApplication,
} from '../api';
import type {
    ApplicationDetail as ApplicationDetailType,
    ApplicationSummary,
    ApplicationTabKey,
    ApplicationReadiness,
} from '../contracts';
import { say } from '../labels';
import { StatusTag } from '../components/StatusTag';
import { ApplicationOverviewTab } from './ApplicationOverviewTab';
import { ApplicationAgentTab } from './ApplicationAgentTab';
import { ApplicationExperienceTab } from '../experience/ApplicationExperienceTab';
import { SkillsTab } from '../skills/SkillsTab';
import { ApplicationRulesTab } from '../rules/ApplicationRulesTab';
import { ConversationRecordsTab } from '../conversations/ConversationRecordsTab';
import { ChannelsReleaseTab } from '../release/ChannelsReleaseTab';
import { VersionHistoryPanel } from '../release/VersionHistoryPanel';

const tabs: Array<{ key: ApplicationTabKey; label: string }> = [
    { key: 'overview', label: '概览' },
    { key: 'agent', label: '智能体' },
    { key: 'experience', label: '客户交互' },
    { key: 'skills', label: '技能' },
    { key: 'rules', label: '业务规则' },
    { key: 'conversations', label: '对话记录' },
    { key: 'release', label: '客户渠道与发布' },
];

function routeParts(route: string) {
    const match = route.match(
        /^\/service-apps\/([a-z0-9-]+)(?:\/(overview|agent|experience|skills|rules|conversations|release))?$/,
    );
    if (!match) return null;
    return {
        key: match[1],
        tab: (match[2] || 'overview') as ApplicationTabKey,
    };
}

export function ApplicationDetail({
    route,
    onNavigate,
}: {
    route: string;
    onNavigate: (path: string) => void;
}) {
    const { admin } = useAccess();
    const parts = useMemo(() => routeParts(route), [route]);
    const [application, setApplication] = useState<ApplicationDetailType | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    const [refreshKey, setRefreshKey] = useState(0);
    const [releaseReadiness, setReleaseReadiness] = useState<ApplicationReadiness | null>(null);
    const [releaseReadinessLoading, setReleaseReadinessLoading] = useState(false);
    const [releaseReadinessError, setReleaseReadinessError] = useState('');
    const [releaseBusy, setReleaseBusy] = useState(false);
    const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
    const [historyOpen, setHistoryOpen] = useState(false);
    const [editingName, setEditingName] = useState(false);
    const [nameDraft, setNameDraft] = useState('');
    const [nameBusy, setNameBusy] = useState(false);

    useEffect(() => {
        setHasUnsavedChanges(false);
        setEditingName(false);
    }, [parts?.key, parts?.tab]);

    useEffect(() => {
        setHistoryOpen(false);
    }, [parts?.key]);

    useEffect(() => {
        if (!parts) return;
        let active = true;
        setLoading(true);
        setError('');
        getApplication(parts.key)
            .then(value => {
                if (active) setApplication(value);
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
    }, [parts, revision]);

    useEffect(() => {
        if (!application || application.immutable || !admin) {
            setReleaseReadiness(null);
            setReleaseReadinessError('');
            setReleaseReadinessLoading(false);
            return;
        }
        let active = true;
        setReleaseReadinessLoading(true);
        setReleaseReadinessError('');
        getApplicationReadiness(application.key)
            .then(value => {
                if (active) setReleaseReadiness(value);
            })
            .catch(cause => {
                if (!active) return;
                setReleaseReadiness(null);
                setReleaseReadinessError(
                    cause instanceof Error ? cause.message : say('加载失败'),
                );
            })
            .finally(() => {
                if (active) setReleaseReadinessLoading(false);
            });
        return () => {
            active = false;
        };
    }, [
        admin,
        application?.draft_revision,
        application?.immutable,
        application?.key,
        application?.published_version,
    ]);

    function reload() {
        setRevision(value => value + 1);
        setRefreshKey(value => value + 1);
    }

    function saved(summary: ApplicationSummary) {
        setApplication(current => current ? { ...current, ...summary } : current);
        setRefreshKey(value => value + 1);
    }

    async function publishCurrent() {
        if (!application || application.immutable || !admin) return;
        setReleaseBusy(true);
        try {
            const summary = await publishApplication(
                application.key,
                application.draft_revision,
            );
            saved(summary);
            toast.success(say('发布已保存草稿'));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setReleaseBusy(false);
        }
    }

    if (!parts) {
        return <Alert type="error" showIcon message={say('页面不存在')}/>;
    }
    if (loading && !application) {
        return <div className="sa-detail-loading"><Spin/></div>;
    }
    if (error || !application) {
        return <div className="sa-detail-error">
            <Alert type="error" showIcon message={error || say('加载失败')}/>
            <Button onClick={reload}>{say('重试')}</Button>
        </div>;
    }

    const readOnly = application.immutable || !admin;
    const canEditName = !readOnly;
    const publishDisabled = readOnly
        || releaseBusy
        || releaseReadinessLoading
        || !releaseReadiness?.can_publish;
    const firstBlockingCheck = releaseReadiness?.checks.find(
        check => check.status === 'blocked',
    );
    const publishBlockedReason = application.immutable
        ? say('标准案例需复制为我的应用后才能发布。')
        : !admin
            ? say('当前角色没有发布权限。')
            : releaseBusy
                ? say('正在发布，请稍候。')
                : releaseReadinessLoading
                    ? say('正在加载发布检查。')
                    : releaseReadinessError
                        || (firstBlockingCheck
                            ? say('发布检查未通过：{{reason}}', {
                                reason: firstBlockingCheck.detail || firstBlockingCheck.title,
                            })
                            : !releaseReadiness
                                ? say('发布检查不可用，请打开客户渠道与发布页重试。')
                                : !releaseReadiness.can_publish
                                    ? say('发布检查未通过，请打开客户渠道与发布页查看详情。')
                                    : '');
    const backPath = application.origin === 'example'
        ? '/service-apps/standards'
        : '/service-apps';
    const publishDescription = hasUnsavedChanges
        ? <div className="sa-publish-warning">
            <strong>{say('当前页面有未保存修改')}</strong>
            <span>{say('发布仅包含已保存草稿；未保存修改不会进入新版本。')}</span>
        </div>
        : say('发布后生成不可变版本，但不会自动更新已有渠道。');

    async function saveName() {
        if (!application || !canEditName || nameBusy) return;
        const nextName = nameDraft.trim();
        if (!nextName) {
            toast.error(say('请输入名称'));
            return;
        }
        if (nextName === application.name) {
            setEditingName(false);
            return;
        }
        setNameBusy(true);
        try {
            const summary = await updateApplication(application.key, {
                revision: application.draft_revision,
                name: nextName,
            });
            saved(summary);
            setEditingName(false);
            toast.success(say('草稿已保存'));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : say('操作失败'));
        } finally {
            setNameBusy(false);
        }
    }

    return <div className="sa-detail">
        <header className="sa-detail-header">
            <div className="sa-detail-heading">
                <Button
                    type="text"
                    icon={<ArrowLeftOutlined/>}
                    onClick={() => onNavigate(backPath)}
                >
                    {application.origin === 'example'
                        ? say('返回标准案例')
                        : say('返回应用列表')}
                </Button>
                <div className="sa-detail-title-row">
                    <div className="sa-detail-mark"><ApiOutlined/></div>
                    <div>
                        <div className="sa-detail-title-line">
                            {editingName
                                ? <div className="sa-detail-name-editor">
                                    <Input
                                        aria-label={say('应用名称')}
                                        autoFocus
                                        maxLength={100}
                                        value={nameDraft}
                                        onChange={event => setNameDraft(event.target.value)}
                                        onKeyDown={event => {
                                            if (event.key === 'Enter') void saveName();
                                            if (event.key === 'Escape') setEditingName(false);
                                        }}
                                    />
                                    <Button
                                        type="primary"
                                        size="small"
                                        aria-label={say('保存')}
                                        icon={<CheckOutlined/>}
                                        loading={nameBusy}
                                        onClick={() => void saveName()}
                                    />
                                    <Button
                                        type="text"
                                        size="small"
                                        aria-label={say('取消')}
                                        icon={<CloseOutlined/>}
                                        disabled={nameBusy}
                                        onClick={() => setEditingName(false)}
                                    />
                                </div>
                                : <>
                                    <h2>{application.name}</h2>
                                    {canEditName && <Tooltip title={say('编辑')}>
                                        <Button
                                            type="text"
                                            size="small"
                                            className="sa-detail-name-edit"
                                            aria-label={`${say('编辑')} ${application.name}`}
                                            icon={<EditOutlined/>}
                                            onClick={() => {
                                                setNameDraft(application.name);
                                                setEditingName(true);
                                            }}
                                        />
                                    </Tooltip>}
                                </>}
                            <StatusTag status={application.status}/>
                            <Tag color={application.immutable ? 'purple' : 'blue'}>
                                {application.immutable ? say('标准案例') : say('我的应用')}
                            </Tag>
                        </div>
                        <span className="mono">{application.key}</span>
                    </div>
                </div>
            </div>
            <div className="sa-detail-actions">
                <div className="sa-detail-meta">
                    <div className="sa-detail-meta-agent">
                        <span>{say('智能体')}</span>
                        <strong>
                            {application.agent.name || say('尚未配置')}-v{application.agent.version || 1}
                        </strong>
                    </div>
                    <Popover
                        arrow={false}
                        placement="bottomRight"
                        trigger="click"
                        open={historyOpen}
                        onOpenChange={setHistoryOpen}
                        classNames={{ root: 'sa-version-popover' }}
                        content={<VersionHistoryPanel
                            application={application}
                            readOnly={readOnly}
                            onSaved={saved}
                            onClose={() => setHistoryOpen(false)}
                        />}
                    >
                        <button
                            type="button"
                            className={`sa-detail-meta-current${historyOpen ? ' open' : ''}`}
                            aria-expanded={historyOpen}
                            aria-haspopup="dialog"
                        >
                        <span>{say('当前发布')}</span>
                        <strong>{application.published_version ? `v${application.published_version}` : '—'}</strong>
                            <DownOutlined className="sa-detail-meta-chevron"/>
                        </button>
                    </Popover>
                </div>
                <div className="sa-release-header-actions">
                    <Tooltip title={publishBlockedReason}>
                        <span>
                            <Popconfirm
                                title={say('确认发布当前草稿？')}
                                description={publishDescription}
                                disabled={publishDisabled}
                                okText={say('确认发布')}
                                cancelText={say('取消')}
                                onConfirm={() => void publishCurrent()}
                            >
                                <Button
                                    type="primary"
                                    icon={<CloudUploadOutlined/>}
                                    loading={releaseBusy || releaseReadinessLoading}
                                    disabled={publishDisabled}
                                >
                                    {say('发布')}
                                </Button>
                            </Popconfirm>
                        </span>
                    </Tooltip>
                </div>
            </div>
        </header>

        {error && <Alert type="error" showIcon message={error}/>}
        <Tabs
            className="sa-detail-tabs"
            activeKey={parts.tab}
            destroyOnHidden
            items={tabs.map(tab => ({
                key: tab.key,
                label: say(tab.label),
                children: tab.key === 'overview'
                    ? <ApplicationOverviewTab application={application}/>
                    : tab.key === 'agent'
                        ? <ApplicationAgentTab
                            application={application}
                            readOnly={readOnly}
                            onSaved={saved}
                            onDirtyChange={setHasUnsavedChanges}
                            onOpenAgent={agentId => onNavigate(`/agents/${agentId}/config`)}
                        />
                        : tab.key === 'experience'
                            ? <ApplicationExperienceTab
                                application={application}
                                readOnly={readOnly}
                                onChanged={reload}
                                onDirtyChange={setHasUnsavedChanges}
                            />
                        : tab.key === 'skills'
                            ? <SkillsTab
                                applicationKey={application.key}
                                readOnly={readOnly}
                                refreshKey={refreshKey}
                                onChanged={reload}
                            />
                            : tab.key === 'rules'
                                ? <ApplicationRulesTab
                                    application={application}
                                    readOnly={readOnly}
                                    onSaved={saved}
                                    onDirtyChange={setHasUnsavedChanges}
                                />
                                : tab.key === 'conversations'
                                    ? <ConversationRecordsTab application={application}/>
                                    : <ChannelsReleaseTab
                                        application={application}
                                        readOnly={readOnly}
                                        readiness={releaseReadiness}
                                        readinessLoading={releaseReadinessLoading}
                                        readinessError={releaseReadinessError}
                                        onSaved={saved}
                                    />,
            }))}
            onChange={key => onNavigate(
                key === 'overview'
                    ? `/service-apps/${application.key}`
                    : `/service-apps/${application.key}/${key}`,
            )}
        />
    </div>;
}
