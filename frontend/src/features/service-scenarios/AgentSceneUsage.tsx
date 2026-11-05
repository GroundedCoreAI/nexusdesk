import { useMemo, useState } from 'react';
import { Button, Select, Spin } from 'antd';
import {
    ArrowRightOutlined,
    BookOutlined,
    FileTextOutlined,
    FilterOutlined,
    RobotOutlined,
    SafetyCertificateOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import type {
    AgentConfig,
    AgentScenarioReferencePage,
    ServiceApplicationPage,
} from '../../shared/api/client';
import { Alert, useResource } from '../../shared/components/ui';
import { demoText as demo } from './data';
import { scenarioStatusLabel } from './scenarioConfig';
import './service-scenarios.css';

interface Props {
    agentId?: string;
    agentName: string;
    agentVersion: number | null;
    agentConfig?: AgentConfig | null;
    onOpenScene: (path: string) => void;
    onOpenAgentConfig?: () => void;
}

function sceneIcon(key: string) {
    if (key.includes('logistic') || key.includes('物流')) return <ThunderboltOutlined/>;
    if (key.includes('rule') || key.includes('知识')) return <BookOutlined/>;
    return <FileTextOutlined/>;
}

export function AgentSceneUsage({ agentId, agentName, agentVersion, agentConfig, onOpenScene, onOpenAgentConfig }: Props) {
    const references = useResource<AgentScenarioReferencePage>(agentId ? `/agents/${agentId}/service-scenarios` : null);
    const applications = useResource<ServiceApplicationPage>('/service-apps');
    const [applicationFilter, setApplicationFilter] = useState('all');

    const ownership = useMemo(() => {
        const result = new Map<string, Array<{ key: string; name: string }>>();
        for (const app of applications.data?.items || []) {
            for (const reference of app.config.scenarios) {
                const items = result.get(reference.key) || [];
                items.push({ key: app.key, name: app.name });
                result.set(reference.key, items);
            }
        }
        return result;
    }, [applications.data]);

    const rows = (references.data?.items || []).filter(item => {
        if (applicationFilter === 'all') return true;
        return (ownership.get(item.key) || []).some(app => app.key === applicationFilter);
    });

    return <div className="agent-scene-usage-view">
        <div className="agent-scene-usage-layout">
            <main className="agent-scene-usage-main">
                <Alert error={references.error || applications.error}/>
                <section className="agent-relation-banner">
                    <span><SafetyCertificateOutlined/></span>
                    <div>
                        <strong>{demo('服务场景与 Agent 是引用关系')}</strong>
                        <p>{demo('场景由“服务应用 → 服务场景”维护；这里只读展示 Agent 被哪些场景使用，不在此重复配置业务对象、用户决策或兜底策略。')}</p>
                    </div>
                </section>

                <section className="agent-usage-panel">
                    <header>
                        <div><span className="scenario-eyebrow">SCENE REFERENCES</span><h2>{demo('被以下服务场景使用')}</h2></div>
                        <Select
                            value={applicationFilter}
                            onChange={setApplicationFilter}
                            suffixIcon={<FilterOutlined/>}
                            style={{ minWidth: 180 }}
                            options={[
                                { value: 'all', label: '全部服务应用' },
                                ...(applications.data?.items || []).map(app => ({ value: app.key, label: app.name })),
                            ]}
                        />
                    </header>
                    <div className="agent-usage-table">
                        <div className="agent-usage-head">
                            <span>{demo('服务场景')}</span><span>{demo('所属服务应用')}</span><span>{demo('绑定条件')}</span><span>{demo('状态')}</span><span>{demo('近 7 日进入')}</span><span/>
                        </div>
                        {references.loading && <div className="agent-usage-loading"><Spin/></div>}
                        {!references.loading && !rows.length && <p className="agent-usage-hint">当前 Agent 尚未被任何服务应用场景引用。</p>}
                        {rows.map(scene => {
                            const owners = ownership.get(scene.key) || [];
                            const primaryOwner = owners[0];
                            return <button
                                type="button"
                                className="agent-usage-row"
                                key={scene.key}
                                disabled={!primaryOwner}
                                onClick={() => primaryOwner && onOpenScene(`/service-apps/${primaryOwner.key}/scenarios/${scene.key}`)}
                            >
                                <span className="agent-usage-scene">
                                    <i>{sceneIcon(scene.key)}</i>
                                    <span><b>{scene.name}</b><small>{scene.handler_label} · {scene.domain}</small></span>
                                </span>
                                <span>{owners.length ? owners.map(app => app.name).join('、') : '未归属应用'}</span>
                                <span><em>{scene.binding}</em></span>
                                <span><strong className={`agent-scene-${scene.status}`}><i/>{scenarioStatusLabel(scene.status)}</strong></span>
                                <span className="agent-usage-number">{scene.metrics.volume || scene.volume}</span>
                                <span className="agent-usage-link">{demo('查看场景')} <ArrowRightOutlined/></span>
                            </button>;
                        })}
                    </div>
                    <p className="agent-usage-hint">{demo('这里展示后端返回的引用关系与近 7 日运行指标。修改绑定条件、回退顺序或场景状态，请进入对应的服务场景。')}</p>
                </section>
            </main>

            <aside className="agent-scene-usage-side">
                <section className="agent-profile-panel">
                    <div className="agent-profile-top">
                        <span><RobotOutlined/></span>
                        <div><small>AGENT</small><h2>{agentName || demo('当前 Agent')}</h2><p>{demo('以下信息来自 Agent 当前配置')}</p></div>
                    </div>
                    <dl>
                        <div><dt>{demo('当前版本')}</dt><dd>{agentVersion ? `v${agentVersion}` : '未发布'}</dd></div>
                        <div><dt>{demo('模型方案')}</dt><dd>{agentConfig?.model_profile_id ? `${agentConfig.model_profile_id}${agentConfig.model_profile_version ? ` · v${agentConfig.model_profile_version}` : ''}` : '跟随默认模型'}</dd></div>
                        <div><dt>{demo('知识库')}</dt><dd>{agentConfig?.knowledge_base_ids.length || 0} 个引用</dd></div>
                        <div><dt>{demo('工具')}</dt><dd>{agentConfig?.tool_names.length || 0} 个工具</dd></div>
                    </dl>
                    <Button block disabled={!onOpenAgentConfig} onClick={onOpenAgentConfig}>{demo('打开 Agent 配置')}</Button>
                </section>

                <section className="agent-reference-policy">
                    <span className="scenario-eyebrow">REFERENCE POLICY</span>
                    <h2>{demo('版本引用规则')}</h2>
                    <PolicyLine title={demo('场景发布时固定 Agent 版本')} description={rows[0]?.agent_version ? `当前引用 v${rows[0].agent_version}` : '发布时会解析并固定引用版本'}/>
                    <PolicyLine title={demo('Agent 升级不自动影响场景')} description={demo('需重新发布场景或显式切换版本')}/>
                    <PolicyLine title={demo('不可用时执行场景兜底')} description={demo('由场景的 fallback_order 决定后续承接')}/>
                </section>
            </aside>
        </div>
    </div>;
}

function PolicyLine({ title, description }: { title: string; description: string }) {
    return <div className="agent-policy-line"><i/><div><strong>{title}</strong><small>{description}</small></div></div>;
}
