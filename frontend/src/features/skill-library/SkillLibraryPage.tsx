import { useEffect, useMemo, useState } from 'react';
import {
    AppstoreOutlined,
    BarChartOutlined,
    BookOutlined,
    CheckCircleOutlined,
    CodeOutlined,
    CustomerServiceOutlined,
    FileSearchOutlined,
    FilterOutlined,
    PlusOutlined,
    SearchOutlined,
    SafetyCertificateOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import {
    Alert,
    Button,
    Card,
    Empty,
    Input,
    Select,
    Skeleton,
    Space,
    Tag,
    Tooltip,
    message,
} from 'antd';
import { getApplication, listApplications } from '../service-apps/api';
import type { ApplicationSkill, ApplicationSummary } from '../service-apps/contracts';
import { skillTypeLabel } from '../service-apps/labels';
import { t } from '../../i18n/index';
import './SkillLibraryPage.css';

type LibrarySkill = ApplicationSkill & {
    applicationKey: string;
    applicationName: string;
    applicationStatus: ApplicationSummary['status'];
};

const categoryOf = (skill: LibrarySkill): string => {
    const text = `${skill.name} ${skill.description} ${skill.type} ${skill.applicationName}`.toLowerCase();
    if (/财务|发票|报销|invoice|finance/.test(text)) return 'finance';
    if (/销售|客户|商机|sales|customer/.test(text)) return 'sales';
    if (/客服|会话|工单|handoff|support/.test(text)) return 'service';
    return 'general';
};

const typeIcon = (type: string) => {
    if (type === 'knowledge') return <BookOutlined />;
    if (type === 'query') return <FileSearchOutlined />;
    if (type === 'action') return <ThunderboltOutlined />;
    return <CustomerServiceOutlined />;
};

const categoryLabel = (category: string) => ({
    all: t('全部'),
    service: t('客服类'),
    finance: t('财务类'),
    sales: t('销售类'),
    general: t('通用类'),
}[category] || category);

export function SkillLibraryPage({ onNavigate }: { onNavigate: (path: string) => void }) {
    const [skills, setSkills] = useState<LibrarySkill[]>([]);
    const [applications, setApplications] = useState<ApplicationSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [query, setQuery] = useState('');
    const [category, setCategory] = useState('all');
    const [status, setStatus] = useState('all');
    const [layout, setLayout] = useState<'grid' | 'list'>('grid');

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        (async () => {
            try {
                const firstPage = await listApplications({ page: 1, pageSize: 100, archived: false });
                const summaries = firstPage.items;
                const details = await Promise.allSettled(summaries.map(item => getApplication(item.key)));
                const rows: LibrarySkill[] = [];
                details.forEach((result, index) => {
                    if (result.status !== 'fulfilled') return;
                    const app = summaries[index];
                    result.value.skills.forEach(skill => rows.push({
                        ...skill,
                        applicationKey: app.key,
                        applicationName: app.name,
                        applicationStatus: app.status,
                    }));
                });
                if (active) {
                    setApplications(summaries);
                    setSkills(rows);
                    const failed = details.filter(item => item.status === 'rejected').length;
                    if (failed) setError(t('部分服务应用读取失败，当前仅展示成功读取的 Skill。'));
                }
            } catch (cause) {
                if (active) setError(cause instanceof Error ? cause.message : t('Skill 能力库加载失败'));
            } finally {
                if (active) setLoading(false);
            }
        })();
        return () => { active = false; };
    }, []);

    const filtered = useMemo(() => skills.filter(skill => {
        const text = `${skill.name} ${skill.description} ${skill.key} ${skill.applicationName}`.toLowerCase();
        const matchesQuery = !query.trim() || text.includes(query.trim().toLowerCase());
        const matchesCategory = category === 'all' || categoryOf(skill) === category;
        const matchesStatus = status === 'all'
            || (status === 'enabled' ? skill.enabled : !skill.enabled);
        return matchesQuery && matchesCategory && matchesStatus;
    }), [skills, query, category, status]);

    const publishedCount = skills.filter(skill => skill.applicationStatus === 'published').length;
    const enabledCount = skills.filter(skill => skill.enabled).length;
    const testedCount = skills.filter(skill => skill.last_test?.status === 'passed').length;

    const openSkill = (skill: LibrarySkill) => onNavigate(`/service-apps/${encodeURIComponent(skill.applicationKey)}/skills`);
    const startCreate = () => {
        if (!applications.length) {
            message.info(t('请先创建一个服务应用，再在应用内配置 Skill。'));
            onNavigate('/service-apps');
            return;
        }
        onNavigate('/service-apps');
    };

    return <div className="skill-library">
        <section className="sl-hero">
            <div className="sl-hero-copy">
                <Tag color="blue"><AppstoreOutlined /> {t('资源中心 · Skill 能力库')}</Tag>
                <h2>{t('Skill 能力库')}</h2>
                <p>{t('统一浏览各业务应用中的可复用 AI 能力，查看状态并进入所属应用管理。')}</p>
            </div>
            <div className="sl-hero-art" aria-hidden="true">
                <div className="sl-orbit sl-orbit-one"/><div className="sl-orbit sl-orbit-two"/>
                <div className="sl-code-tile"><CodeOutlined /></div>
                <div className="sl-float sl-float-a"><ThunderboltOutlined /></div>
                <div className="sl-float sl-float-b"><BookOutlined /></div>
                <div className="sl-float sl-float-c"><SafetyCertificateOutlined /></div>
            </div>
        </section>

        {error && <Alert className="sl-alert" type="warning" showIcon message={error} />}
        <div className="sl-category-row">
            <div className="sl-categories">
                {['all', 'service', 'finance', 'sales', 'general'].map(item =>
                    <Button key={item} type={category === item ? 'primary' : 'default'} onClick={() => setCategory(item)}>
                        {categoryLabel(item)}
                        {item === 'all' && <span className="sl-tab-count">{skills.length}</span>}
                    </Button>,
                )}
            </div>
            <Button type="primary" icon={<PlusOutlined />} onClick={startCreate}>{t('创建 Skill')}</Button>
        </div>

        <div className="sl-overview">
            <Card className="sl-stat"><span className="sl-stat-icon blue"><AppstoreOutlined /></span><div><span>{t('Skill 总数')}</span><strong>{loading ? '—' : skills.length}</strong><small>{t('跨应用聚合')}</small></div></Card>
            <Card className="sl-stat"><span className="sl-stat-icon violet"><CheckCircleOutlined /></span><div><span>{t('所属应用已发布')}</span><strong>{loading ? '—' : publishedCount}</strong><small>{t('所在应用处于已发布状态')}</small></div></Card>
            <Card className="sl-stat"><span className="sl-stat-icon teal"><ThunderboltOutlined /></span><div><span>{t('已启用')}</span><strong>{loading ? '—' : enabledCount}</strong><small>{t('Skill 配置为启用')}</small></div></Card>
            <Card className="sl-stat"><span className="sl-stat-icon amber"><BarChartOutlined /></span><div><span>{t('测试通过')}</span><strong>{loading ? '—' : testedCount}</strong><small>{t('最近一次测试通过')}</small></div></Card>
        </div>

        <div className="sl-main-grid">
            <section className="sl-results">
                <div className="sl-toolbar">
                    <Input allowClear prefix={<SearchOutlined />} placeholder={t('搜索 Skill 名称、描述或所属应用…')} value={query} onChange={event => setQuery(event.target.value)} />
                    <Select value={status} onChange={setStatus} options={[
                        { value: 'all', label: t('所有状态') },
                        { value: 'enabled', label: t('已启用') },
                        { value: 'disabled', label: t('已停用') },
                    ]} />
                    <span className="sl-result-count">{t('共 {{count}} 项', { count: filtered.length })}</span>
                    <Space.Compact className="sl-layout-switch">
                        <Tooltip title={t('卡片视图')}><Button type={layout === 'grid' ? 'primary' : 'default'} icon={<AppstoreOutlined />} onClick={() => setLayout('grid')} /></Tooltip>
                        <Tooltip title={t('列表视图')}><Button type={layout === 'list' ? 'primary' : 'default'} icon={<FilterOutlined />} onClick={() => setLayout('list')} /></Tooltip>
                    </Space.Compact>
                </div>
                {loading ? <div className="sl-loading"><Skeleton active paragraph={{ rows: 5 }}/><Skeleton active paragraph={{ rows: 5 }}/></div>
                    : filtered.length === 0 ? <Empty description={t('没有找到符合条件的 Skill')} />
                    : <div className={`sl-skill-grid ${layout === 'list' ? 'is-list' : ''}`}>
                        {filtered.map(skill => <Card key={`${skill.applicationKey}:${skill.id}`} className="sl-skill-card" hoverable onClick={() => openSkill(skill)}>
                            <div className="sl-card-top">
                                <span className="sl-skill-icon">{typeIcon(skill.type)}</span>
                                <Tag color={skill.enabled ? 'success' : 'default'}>{skill.enabled ? t('已启用') : t('已停用')}</Tag>
                            </div>
                            <h3>{skill.name}</h3>
                            <p className="sl-description">{skill.description || t('暂无能力描述')}</p>
                            <div className="sl-tags"><Tag>{skillTypeLabel(skill.type)}</Tag><Tag>{skill.applicationName}</Tag><Tag>{t('修订 {{revision}}', { revision: skill.revision })}</Tag></div>
                            <div className="sl-card-footer">
                                <span>{skill.last_test?.status === 'passed' ? <><CheckCircleOutlined /> {t('测试通过')}</> : skill.last_test?.status === 'failed' ? <><span className="sl-failed-dot"/> {t('测试失败')}</> : t('尚未测试')}</span>
                                <Button type="link" onClick={event => { event.stopPropagation(); openSkill(skill); }}>{t('进入管理')} →</Button>
                            </div>
                        </Card>)}
                    </div>}
            </section>
            <aside className="sl-aside">
                <Card className="sl-aside-card">
                    <h3>{t('所属业务应用')}</h3>
                    <p>{t('Skill 仍归属于具体服务应用，本页面提供跨应用统一浏览。')}</p>
                    {applications.slice(0, 5).map(app => <button className="sl-app-row" key={app.id} onClick={() => onNavigate(`/service-apps/${encodeURIComponent(app.key)}`)}>
                        <span className="sl-app-icon"><AppstoreOutlined /></span><span><strong>{app.name}</strong><small>{app.skill_count} {t('个 Skill')}</small></span><span className="sl-app-status">{app.status === 'published' ? t('已发布') : t('配置中')}</span>
                    </button>)}
                    {applications.length === 0 && !loading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('暂无服务应用')} />}
                    <Button type="link" onClick={() => onNavigate('/service-apps')}>{t('查看全部应用')} →</Button>
                </Card>
                <Card className="sl-guide-card">
                    <div className="sl-guide-robot"><span>✦</span><span>✧</span><div className="sl-robot-face"><i/><i/></div></div>
                    <h3>{t('Skill 使用指南')}</h3>
                    <p>{t('了解 Skill 的创建、配置、测试和发布流程。')}</p>
                    <Button type="primary" onClick={() => onNavigate('/service-apps')}>{t('查看服务应用')} →</Button>
                </Card>
                <Card className="sl-links-card">
                    <h3>{t('相关资源')}</h3>
                    <button onClick={() => onNavigate('/tools')}>{t('工具目录')}</button>
                    <button onClick={() => onNavigate('/knowledge')}>{t('知识库')}</button>
                    <button onClick={() => onNavigate('/service-apps/standards')}>{t('服务应用模板')}</button>
                </Card>
            </aside>
        </div>
    </div>;
}
