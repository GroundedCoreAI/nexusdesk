import { useEffect, useState } from 'react';
import {
    ApiOutlined,
    CheckCircleFilled,
    ClockCircleOutlined,
    CloseCircleFilled,
    DeploymentUnitOutlined,
    RobotOutlined,
    SafetyCertificateOutlined,
    ToolOutlined,
} from '@ant-design/icons';
import { Alert, Empty, Spin, Tag } from 'antd';
import { listTraces } from '../api';
import type {
    ApplicationDetail,
    ApplicationTrace,
} from '../contracts';
import { say } from '../labels';
import { CountTag } from '../components/StatusTag';

function traceOutcomeLabel(outcome: string) {
    if (outcome === 'completed') return say('已完成');
    if (outcome === 'failed' || outcome === 'error') return say('失败');
    if (outcome === 'cancelled' || outcome === 'canceled') return say('已取消');
    if (outcome === 'running' || outcome === 'pending') return say('运行中');
    return say('未知');
}

function traceOutcomeColor(outcome: string) {
    if (outcome === 'completed') return 'green';
    if (outcome === 'failed' || outcome === 'error') return 'red';
    if (outcome === 'cancelled' || outcome === 'canceled') return 'default';
    return 'gold';
}

export function ApplicationOverviewTab({ application }: { application: ApplicationDetail }) {
    const [traces, setTraces] = useState<ApplicationTrace[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        let active = true;
        setLoading(true);
        listTraces(application.key, 1, 5)
            .then(result => {
                if (active) setTraces(result.items);
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
    }, [application.key, application.published_version, application.draft_revision]);

    const enabledSkills = application.skills.filter(skill => skill.enabled).length;
    const healthyConnections = application.connections.filter(connection =>
        connection.auth_kind === 'none' || connection.credentials_configured,
    ).length;

    return <div className="sa-overview">
        {error && <Alert type="warning" showIcon message={error}/>}

        <section className="sa-overview-stats">
            <CountTag
                label={say('技能')}
                value={`${enabledSkills}/${application.skills.length}`}
                color="#5d5af0"
            />
            <CountTag
                label={say('连接')}
                value={`${healthyConnections}/${application.connections.length}`}
                color="#168a63"
            />
            <CountTag
                label={say('渠道')}
                value={application.channels.length}
                color="#1f74d6"
            />
            <CountTag
                label={say('当前发布')}
                value={application.published_version ? `v${application.published_version}` : '—'}
                color="#cf6b12"
            />
        </section>

        <div className="sa-overview-grid">
            <section className="sa-overview-card">
                <div className="sa-overview-card-head">
                    <div className="sa-overview-card-icon violet"><RobotOutlined/></div>
                    <div>
                        <h3>{say('智能体')}</h3>
                        <p>{say('推理与执行底座')}</p>
                    </div>
                </div>
                <dl>
                    <dt>{say('名称')}</dt>
                    <dd>{application.agent.name || application.agent.id || say('尚未配置')}</dd>
                    <dt>{say('绑定版本')}</dt>
                    <dd><Tag color="purple">v{application.agent.version || 1}</Tag></dd>
                </dl>
            </section>

            <section className="sa-overview-card">
                <div className="sa-overview-card-head">
                    <div className="sa-overview-card-icon green"><ToolOutlined/></div>
                    <div>
                        <h3>{say('技能')}</h3>
                        <p>{say('应用内唯一、按版本发布')}</p>
                    </div>
                </div>
                <dl>
                    <dt>{say('启用技能')}</dt>
                    <dd>{enabledSkills}</dd>
                    <dt>{say('待配置连接')}</dt>
                    <dd>{application.credential_health.missing}</dd>
                </dl>
            </section>

            <section className="sa-overview-card">
                <div className="sa-overview-card-head">
                    <div className="sa-overview-card-icon blue"><ApiOutlined/></div>
                    <div>
                        <h3>{say('应用连接')}</h3>
                        <p>{say('凭据只属于当前应用')}</p>
                    </div>
                </div>
                <dl>
                    <dt>{say('凭据已配置')}</dt>
                    <dd>{application.credential_health.configured}</dd>
                    <dt>{say('连接总数')}</dt>
                    <dd>{application.connections.length}</dd>
                </dl>
            </section>

            <section className="sa-overview-card">
                <div className="sa-overview-card-head">
                    <div className="sa-overview-card-icon amber"><SafetyCertificateOutlined/></div>
                    <div>
                        <h3>{say('发布状态')}</h3>
                        <p>{say('草稿修改不会影响线上')}</p>
                    </div>
                </div>
                <dl>
                    <dt>{say('当前发布')}</dt>
                    <dd>{application.published_version ? `v${application.published_version}` : say('尚无发布版本')}</dd>
                    <dt>{say('草稿修订')}</dt>
                    <dd>r{application.draft_revision}</dd>
                </dl>
            </section>
        </div>

        <section className="sa-overview-traces">
            <div className="sa-section-head">
                <div>
                    <span className="sa-eyebrow">{say('最近运行')}</span>
                    <h3>{say('最近运行')}</h3>
                </div>
                {application.has_unpublished_changes && <Tag color="gold">{say('有未保存修改')}</Tag>}
            </div>
            {loading
                ? <Spin/>
                : traces.length === 0
                    ? <Empty description={say('暂无记录')}/>
                    : <div className="sa-trace-list">
                        {traces.map(trace => <div className="sa-trace-row" key={trace.id}>
                            <div className="sa-trace-state">
                                {trace.outcome === 'completed'
                                    ? <CheckCircleFilled className="success"/>
                                    : trace.outcome === 'failed' || trace.outcome === 'error'
                                        ? <CloseCircleFilled className="danger"/>
                                        : <ClockCircleOutlined/>}
                                <div>
                                    <strong>{trace.skill_key || application.name}</strong>
                                    <span>{trace.connection_key || say('无连接')}</span>
                                </div>
                            </div>
                            <Tag color={traceOutcomeColor(trace.outcome)}>
                                {traceOutcomeLabel(trace.outcome)}
                            </Tag>
                            <div className="sa-trace-meta">
                                <span>{trace.duration_ms == null ? '—' : `${trace.duration_ms}ms`}</span>
                                <span>v{trace.application_version}</span>
                                <span className="mono sa-trace-id" title={trace.id}>
                                    #{trace.id.slice(0, 8)}
                                </span>
                            </div>
                        </div>)}
                    </div>}
        </section>

        <div className="sa-overview-footnote">
            <DeploymentUnitOutlined/>
            <span>{say('应用版本固定后，渠道入站和运行快照都会记录应用与版本。')}</span>
        </div>
    </div>;
}
