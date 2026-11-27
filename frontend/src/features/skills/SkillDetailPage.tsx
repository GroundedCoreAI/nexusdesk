import { useRef, useState, type KeyboardEvent } from 'react';
import { Alert, Avatar, Button, Empty, Skeleton, Tag } from 'antd';
import {
  ApiOutlined,
  ArrowRightOutlined,
  BookOutlined,
  CheckCircleFilled,
  ClockCircleFilled,
  CodeOutlined,
  DatabaseOutlined,
  EditOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { dateTime, errorText } from '../../i18n';
import { SkillBreadcrumb } from './SkillBreadcrumb';
import { SkillPackageCard } from './SkillPackageCard';
import { TestWorkbench } from './TestWorkbench';
import { ReleasePanel } from './ReleasePanel';
import { skillErrorStatus } from './api';
import {
  type SkillCategory,
  type SkillDefinition,
  type SkillParameter,
  type SkillRecord,
  type SkillStatus,
} from './contracts';
import { useSkillDetail, useSkillDependencyOptions, useSkillPermissions } from './useSkills';
import './skill-workflows.css';

export type SkillDetailTab = 'overview' | 'capability' | 'resources' | 'tests' | 'versions' | 'analytics';

interface SkillDetailPageProps {
  skillKey: string;
  onNavigate: (path: string) => void;
  initialTab?: SkillDetailTab;
}

const tabIds: SkillDetailTab[] = ['overview', 'capability', 'resources', 'tests', 'versions', 'analytics'];

function detailIcon(category: SkillCategory): string {
  if (category === 'service') return 'service';
  if (category === 'finance') return 'invoice';
  if (category === 'sales') return 'sales';
  return 'flow';
}

function statusTone(status: SkillStatus): string {
  if (status === 'published') return 'success';
  if (status === 'archived') return 'default';
  return 'gold';
}

function typeLabel(type: SkillDefinition['type']): string {
  return `skill.type.${type}`;
}

function triggerLabel(trigger: SkillDefinition['trigger']): string {
  return `skill.trigger.${trigger}`;
}

function outputLabel(format: SkillDefinition['output']['format']): string {
  return `skill.output.${format}`;
}

function DefinitionFacts({ definition }: { definition: SkillDefinition }) {
  const { t } = useTranslation();
  return (
    <div className="detail-definition-list">
      <div><span>{t('skill.field.type')}</span><strong>{t(typeLabel(definition.type))}</strong></div>
      <div><span>{t('skill.field.trigger')}</span><strong>{t(triggerLabel(definition.trigger))}</strong></div>
      <div><span>{t('skill.field.outputFormat')}</span><strong>{t(outputLabel(definition.output.format))}</strong></div>
      <div><span>{t('skill.field.timeout')}</span><strong>{t('skill.detail.seconds {{v0}}', { v0: definition.runtime.timeout_seconds })}</strong></div>
      <div><span>{t('skill.field.confirmation')}</span><strong>{definition.runtime.confirmation_required ? t('skill.common.required') : t('skill.common.notRequired')}</strong></div>
      <div><span>{t('skill.field.permissionScope')}</span><strong>{t('skill.visibility.workspace')}</strong></div>
    </div>
  );
}

function ParameterList({ parameters }: { parameters: SkillParameter[] }) {
  const { t } = useTranslation();
  if (!parameters.length) {
    return <div className="skill-editor-empty">{t('skill.detail.noParameters')}</div>;
  }
  return (
    <div className="detail-parameter-list">
      {parameters.map(parameter => (
        <div key={parameter.name}>
          <code>{parameter.name}</code>
          <span>{parameter.type}</span>
          <small>{parameter.required ? t('skill.common.required') : t('skill.common.optional')}</small>
          <p>{parameter.description || '—'}</p>
        </div>
      ))}
    </div>
  );
}

function OverviewContent({
  skill,
  onOpenTab,
}: {
  skill: SkillRecord;
  onOpenTab: (tab: SkillDetailTab) => void;
}) {
  const { t } = useTranslation();
  const dependencies = skill.definition.dependencies;
  const dependencyCount = dependencies.knowledge_base_ids.length
    + dependencies.tool_names.length
    + (dependencies.model_profile_id ? 1 : 0)
    + (dependencies.handoff_queue ? 1 : 0);
  return (
    <>
      <section className="detail-facts" aria-label={t('skill.detail.factsLabel')}>
        <article className="detail-fact-card">
          <span>{t('skill.detail.fact.draftRevision')}</span>
          <strong>r{skill.draft_revision}</strong>
          <small>{t('skill.detail.fact.draftRevisionHelp')}</small>
        </article>
        <article className="detail-fact-card">
          <span>{t('skill.detail.fact.publishedVersion')}</span>
          <strong>{skill.current_semver ? `v${skill.current_semver}` : '—'}</strong>
          <small>{skill.published_at ? dateTime(skill.published_at) : t('skill.catalog.notPublished')}</small>
        </article>
        <article className="detail-fact-card">
          <span>{t('skill.detail.fact.status')}</span>
          <strong>{t(`skill.status.${skill.status}`)}</strong>
          <small>{skill.has_unpublished_changes ? t('skill.catalog.unpublishedChanges') : t('skill.detail.fact.inSync')}</small>
        </article>
        <article className="detail-fact-card">
          <span>{t('skill.detail.fact.updatedAt')}</span>
          <strong>{skill.updated_at ? dateTime(skill.updated_at) : '—'}</strong>
          <small>{skill.updated_by || skill.created_by || '—'}</small>
        </article>
      </section>

      <section className="detail-overview-grid">
        <article className="skill-flow-panel detail-basic-card">
          <div className="detail-section-heading">
            <h2>{t('skill.detail.basicInfo')}</h2>
            <Tag color={statusTone(skill.status)}>{t(`skill.status.${skill.status}`)}</Tag>
          </div>
          <dl className="detail-info-list">
            <div><dt>{t('skill.field.key')}</dt><dd><code>{skill.key}</code></dd></div>
            <div><dt>{t('skill.detail.description')}</dt><dd>{skill.description || t('skill.detail.noDescription')}</dd></div>
            <div><dt>{t('skill.field.category')}</dt><dd><Tag>{t(`skill.category.${skill.category}`)}</Tag></dd></div>
            <div><dt>{t('skill.field.tags')}</dt><dd className="detail-tags">{skill.tags.length ? skill.tags.map(tag => <Tag key={tag}>{tag}</Tag>) : '—'}</dd></div>
            <div><dt>{t('skill.detail.createdBy')}</dt><dd className="detail-person"><Avatar size={28}>{skill.created_by?.[0] || '—'}</Avatar>{skill.created_by || '—'}</dd></div>
            <div><dt>{t('skill.detail.updatedBy')}</dt><dd>{skill.updated_by || '—'}</dd></div>
            <div><dt>{t('skill.detail.createdAt')}</dt><dd>{skill.created_at ? dateTime(skill.created_at) : '—'}</dd></div>
            <div><dt>{t('skill.detail.updatedAt')}</dt><dd>{skill.updated_at ? dateTime(skill.updated_at) : '—'}</dd></div>
          </dl>
        </article>

        <article className="skill-flow-panel detail-version-card">
          <div className="detail-section-heading">
            <h2>{t('skill.detail.versionInfo')}</h2>
            <Button type="link" onClick={() => onOpenTab('versions')}>
              {t('skill.detail.viewVersions')}<ArrowRightOutlined />
            </Button>
          </div>
          <div className="detail-current-version">
            <span>{t('skill.detail.currentVersion')}</span>
            <strong>{skill.current_semver ? `v${skill.current_semver}` : t('skill.catalog.notPublished')}</strong>
            <Tag color={skill.published_version ? 'success' : 'gold'}>
              {skill.published_version ? t('skill.status.published') : t('skill.status.draft')}
            </Tag>
            <small>{skill.published_at ? dateTime(skill.published_at) : '—'}</small>
          </div>
          <dl className="detail-info-list skill-detail-version-list">
            <div><dt>{t('skill.detail.publishedRevision')}</dt><dd>{skill.published_revision ?? '—'}</dd></div>
            <div><dt>{t('skill.detail.draftRevision')}</dt><dd>{skill.draft_revision}</dd></div>
            <div><dt>{t('skill.detail.publishState')}</dt><dd>{skill.has_unpublished_changes ? t('skill.detail.hasUnpublished') : t('skill.detail.inSync')}</dd></div>
          </dl>
        </article>
      </section>

      <section className="detail-overview-grid detail-overview-bottom">
        <article className="skill-flow-panel">
          <div className="detail-section-heading">
            <h2>{t('skill.detail.resourcesTitle')}</h2>
            <Button type="link" onClick={() => onOpenTab('resources')}>
              {t('skill.detail.viewResources')}<ArrowRightOutlined />
            </Button>
          </div>
          <div className="detail-resource-grid">
            <div><span className="detail-resource-icon resource-blue"><ToolOutlined /></span><strong>{t('skill.detail.tools')}</strong><small>{t('skill.detail.resourceCount {{v0}}', { v0: dependencies.tool_names.length })}</small></div>
            <div><span className="detail-resource-icon resource-purple"><DatabaseOutlined /></span><strong>{t('skill.detail.knowledgeBases')}</strong><small>{t('skill.detail.resourceCount {{v0}}', { v0: dependencies.knowledge_base_ids.length })}</small></div>
            <div><span className="detail-resource-icon resource-green"><LinkOutlined /></span><strong>{t('skill.detail.totalDependencies')}</strong><small>{t('skill.detail.resourceCount {{v0}}', { v0: dependencyCount })}</small></div>
          </div>
        </article>
        <article className="skill-flow-panel">
          <div className="detail-section-heading">
            <h2>{t('skill.detail.definitionTitle')}</h2>
            <Button type="link" onClick={() => onOpenTab('capability')}>
              {t('skill.detail.viewDefinition')}<ArrowRightOutlined />
            </Button>
          </div>
          <div className="detail-definition-summary">
            <div><CodeOutlined /><span>{t('skill.detail.parameterCount {{v0}}', { v0: skill.definition.parameters.length })}</span></div>
            <div><SafetyCertificateOutlined /><span>{t('skill.detail.runtimePolicy {{v0}}', { v0: skill.definition.runtime.timeout_seconds })}</span></div>
            <div><ApiOutlined /><span>{t(outputLabel(skill.definition.output.format))}</span></div>
          </div>
          <pre className="skill-detail-instruction-preview">{skill.definition.instructions || t('skill.detail.noInstructions')}</pre>
        </article>
      </section>
    </>
  );
}

function CapabilityContent({ skill }: { skill: SkillRecord }) {
  const { t } = useTranslation();
  return (
    <div className="detail-tab-layout">
      <section className="skill-flow-panel">
        <div className="detail-section-heading">
          <h2>{t('skill.detail.capabilityDefinition')}</h2>
          <Tag color="blue">{t(typeLabel(skill.definition.type))}</Tag>
        </div>
        <p className="detail-tab-description">{skill.description || t('skill.detail.noDescription')}</p>
        <DefinitionFacts definition={skill.definition} />
        <div className="detail-code-block">
          <div className="detail-code-title"><CodeOutlined /><span>{t('skill.detail.instructions')}</span></div>
          <pre>{skill.definition.instructions || t('skill.detail.noInstructions')}</pre>
        </div>
        {skill.definition.output.format === 'json' && (
          <div className="detail-code-block">
            <div className="detail-code-title"><ApiOutlined /><span>{t('skill.detail.outputSchema')}</span></div>
            <pre>{skill.definition.output.schema
              ? JSON.stringify(skill.definition.output.schema, null, 2)
              : t('skill.detail.noSchema')}</pre>
          </div>
        )}
      </section>
      <section className="skill-flow-panel">
        <div className="detail-section-heading"><h2>{t('skill.detail.parameters')}</h2></div>
        <ParameterList parameters={skill.definition.parameters} />
      </section>
    </div>
  );
}

function ResourcesContent({
  skill,
  onEdit,
}: {
  skill: SkillRecord;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const options = useSkillDependencyOptions();
  const dependencies = skill.definition.dependencies;
  const models = dependencies.model_profile_id
    ? options.data?.models.filter(item => item.id === dependencies.model_profile_id) ?? []
    : [];
  const knowledgeBases = dependencies.knowledge_base_ids.map(id => {
    const item = options.data?.knowledgeBases.find(candidate => candidate.id === id) ?? null;
    return { id, enabled: item?.enabled ?? null, name: item?.name ?? id };
  });
  const tools = dependencies.tool_names.map(id => {
    const item = options.data?.tools.find(candidate => candidate.id === id) ?? null;
    return { id, enabled: item?.enabled ?? null, name: item?.name ?? id, effect: item?.effect ?? 'unknown' };
  });
  return (
    <div className="detail-tab-layout">
      <section className="skill-flow-panel">
        <div className="detail-section-heading">
          <h2>{t('skill.detail.selectedDependencies')}</h2>
          <Button type="link" onClick={onEdit}>{t('skill.detail.manageDependencies')}</Button>
        </div>
        {options.loading && <Skeleton active paragraph={{ rows: 4 }} title={false} />}
        {options.data?.errors.models && (
          <Alert type="error" showIcon title={t('skill.dependencies.modelLoadError')} description={errorText(options.data.errors.models)} action={<Button size="small" onClick={options.refresh}>{t('common.retry')}</Button>} />
        )}
        {options.data?.errors.knowledgeBases && (
          <Alert type="error" showIcon title={t('skill.dependencies.knowledgeLoadError')} description={errorText(options.data.errors.knowledgeBases)} action={<Button size="small" onClick={options.refresh}>{t('common.retry')}</Button>} />
        )}
        {options.data?.errors.tools && (
          <Alert type="error" showIcon title={t('skill.dependencies.toolLoadError')} description={errorText(options.data.errors.tools)} action={<Button size="small" onClick={options.refresh}>{t('common.retry')}</Button>} />
        )}
        {!options.loading && !dependencies.model_profile_id && !knowledgeBases.length && !tools.length && !dependencies.handoff_queue && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('skill.detail.noDependencies')} />
        )}
        <div className="detail-resource-list">
          {dependencies.model_profile_id && (
            <div className="detail-resource-list-row">
              <span><CodeOutlined /></span>
              <strong>{models[0]?.name || dependencies.model_profile_id}</strong>
              <small>{t('skill.detail.modelProfile')}</small>
              <Tag color={models[0]?.enabled === false ? 'error' : 'success'}>
                {models[0]?.enabled === false ? t('skill.detail.resourceDisabled') : t('skill.detail.resourceAvailable')}
              </Tag>
              <Button type="link" icon={<ArrowRightOutlined />} onClick={options.refresh}>{t('common.refresh')}</Button>
            </div>
          )}
          {knowledgeBases.map(item => (
            <div className="detail-resource-list-row" key={`kb-${item.id}`}>
              <span><DatabaseOutlined /></span>
              <strong>{item.name}</strong>
              <small>{t('skill.detail.knowledgeBase')}</small>
              <Tag color={item.enabled === false ? 'error' : item.enabled === true ? 'success' : 'warning'}>
                {item.enabled === false ? t('skill.detail.resourceDisabled') : item.enabled === true ? t('skill.detail.resourceAvailable') : t('skill.detail.resourceUnknown')}
              </Tag>
              <Button type="link" icon={<ArrowRightOutlined />} onClick={options.refresh}>{t('common.refresh')}</Button>
            </div>
          ))}
          {tools.map(item => (
            <div className="detail-resource-list-row" key={`tool-${item.id}`}>
              <span><ToolOutlined /></span>
              <strong>{item.name}</strong>
              <small>{t(`skill.effect.${item.effect}`)}</small>
              <Tag color={item.enabled === false ? 'error' : item.enabled === true ? 'success' : 'warning'}>
                {item.enabled === false ? t('skill.detail.resourceDisabled') : item.enabled === true ? t('skill.detail.resourceAvailable') : t('skill.detail.resourceUnknown')}
              </Tag>
              <Button type="link" icon={<ArrowRightOutlined />} onClick={options.refresh}>{t('common.refresh')}</Button>
            </div>
          ))}
        </div>
      </section>
      {dependencies.handoff_queue && (
        <section className="skill-flow-panel">
          <div className="detail-section-heading"><h2>{t('skill.detail.handoffQueue')}</h2></div>
          <div className="detail-resource-list-row">
            <span><LinkOutlined /></span>
            <strong>{dependencies.handoff_queue}</strong>
            <small>{t('skill.field.handoffQueue')}</small>
          </div>
        </section>
      )}
      <section className="skill-flow-panel">
        <div className="detail-section-heading"><h2>{t('skill.package.title')}</h2></div>
        <SkillPackageCard
          skillKey={skill.key}
          revision={skill.draft_revision}
          weightClass={skill.weight_class}
          canManage={false}
          readOnly
        />
      </section>
    </div>
  );
}

function AnalyticsContent() {
  const { t } = useTranslation();
  return (
    <section className="skill-flow-panel skill-analytics-empty">
      <ApiOutlined />
      <h2>{t('skill.analytics.emptyTitle')}</h2>
      <p>{t('skill.analytics.emptyBody')}</p>
      <Tag color="processing">{t('skill.analytics.pending')}</Tag>
    </section>
  );
}

function DetailSide({
  skill,
  role,
  canManage,
  canTest,
  canPublish,
}: {
  skill: SkillRecord;
  role: string;
  canManage: boolean;
  canTest: boolean;
  canPublish: boolean;
}) {
  const { t } = useTranslation();
  return (
    <aside className="skill-detail-side" aria-label={t('skill.detail.sideLabel')}>
      <section className={`skills-side-card detail-side-status ${skill.status === 'draft' ? 'is-draft' : ''}`}>
        <h2>{t('skill.detail.statusTitle')}</h2>
        <div className="detail-status-line">
          {skill.status === 'published' ? <CheckCircleFilled /> : <ClockCircleFilled />}
          <strong>{t(`skill.status.${skill.status}`)}</strong>
        </div>
        <dl>
          <div><dt>{t('skill.detail.publishedVersion')}</dt><dd>{skill.current_semver ? `v${skill.current_semver}` : '—'}</dd></div>
          <div><dt>{t('skill.detail.draftRevision')}</dt><dd>r{skill.draft_revision}</dd></div>
          <div><dt>{t('skill.detail.publishedAt')}</dt><dd>{skill.published_at ? dateTime(skill.published_at) : '—'}</dd></div>
        </dl>
      </section>
      <section className="skills-side-card detail-side-related">
        <h2>{t('skill.detail.relatedInfo')}</h2>
        <dl>
          <div><dt>{t('skill.field.category')}</dt><dd>{t(`skill.category.${skill.category}`)}</dd></div>
          <div><dt>{t('skill.field.tags')}</dt><dd className="detail-related-tags">{skill.tags.length ? skill.tags.slice(0, 4).map(tag => <span key={tag}>{tag}</span>) : '—'}</dd></div>
          <div><dt>{t('skill.detail.workspace')}</dt><dd><span className="detail-workspace"><BookOutlined />{t('skill.visibility.workspace')}</span></dd></div>
        </dl>
      </section>
      <section className="skills-side-card detail-side-permissions">
        <h2>{t('skill.detail.permissionsTitle')}</h2>
        <dl>
          <div><dt>{t('skill.detail.role')}</dt><dd>{role || '—'}</dd></div>
          <div><dt>{t('skill.detail.canManage')}</dt><dd>{canManage ? t('skill.common.yes') : t('skill.common.no')}</dd></div>
          <div><dt>{t('skill.detail.canTest')}</dt><dd>{canTest ? t('skill.common.yes') : t('skill.common.no')}</dd></div>
          <div><dt>{t('skill.detail.canPublish')}</dt><dd>{canPublish ? t('skill.common.yes') : t('skill.common.no')}</dd></div>
        </dl>
      </section>
    </aside>
  );
}

export function SkillDetailPage({
  skillKey,
  onNavigate,
  initialTab = 'overview',
}: SkillDetailPageProps) {
  const { t } = useTranslation();
  const detail = useSkillDetail(skillKey);
  const permissions = useSkillPermissions();
  const [activeTab, setActiveTab] = useState<SkillDetailTab>(initialTab);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const canManage = permissions.data?.manage ?? false;
  const canTest = permissions.data?.test ?? false;
  const canPublish = permissions.data?.publish ?? false;
  const statusCode = detail.error ? skillErrorStatus(new Error(detail.error)) : null;
  const notFound = statusCode === 404 || /(?:^|\D)404(?:\D|$)/.test(detail.error);

  function openTab(tab: SkillDetailTab) {
    setActiveTab(tab);
    onNavigate(`/skills/${encodeURIComponent(skillKey)}?tab=${tab}`);
  }

  function tabKeyboard(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % tabIds.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabIds.length) % tabIds.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabIds.length - 1;
    else return;
    event.preventDefault();
    tabRefs.current[next]?.focus();
    openTab(tabIds[next]);
  }

  if (detail.error) {
    return (
      <div className="skill-flow-page skill-detail-page">
        <SkillBreadcrumb current={skillKey} onOpenCatalog={() => onNavigate('/skills')} />
        <section className="skill-state-panel" role="alert">
          <Alert
            type={notFound ? 'warning' : 'error'}
            showIcon
            title={notFound ? t('skill.detail.notFoundTitle') : t('skill.detail.loadFailedTitle')}
            description={notFound ? t('skill.detail.notFoundBody {{v0}}', { v0: skillKey }) : errorText(detail.error)}
          />
          <div className="skill-state-actions">
            {!notFound && <Button onClick={detail.refresh}>{t('common.retry')}</Button>}
            <Button type="primary" onClick={() => onNavigate('/skills')}>{t('skill.action.backToLibrary')}</Button>
          </div>
        </section>
      </div>
    );
  }

  if (detail.loading || !detail.data) {
    return (
      <div className="skill-flow-page skill-detail-page">
        <SkillBreadcrumb current={skillKey} onOpenCatalog={() => onNavigate('/skills')} />
        <section className="skill-state-panel" role="status" aria-live="polite">
          <Skeleton active avatar paragraph={{ rows: 8 }} />
          <span className="skill-loading-label">{t('skill.detail.loading')}</span>
        </section>
      </div>
    );
  }

  const skill = detail.data;
  const actions = (
    <div className="skill-detail-actions">
      <Button
        aria-label={t('skill.action.test')}
        icon={<PlayCircleOutlined />}
        disabled={!canTest}
        title={!canTest ? t('skill.detail.testDenied') : undefined}
        onClick={() => openTab('tests')}
      >
        {t('skill.action.test')}
      </Button>
      <Button
        type="primary"
        icon={<RocketOutlined />}
        disabled={!canPublish}
        title={!canPublish ? t('skill.detail.publishDenied') : undefined}
        onClick={() => onNavigate(`/skills/${encodeURIComponent(skillKey)}/edit?stage=release`)}
      >
        {t('skill.action.publish')}
      </Button>
      <Button
        icon={<EditOutlined />}
        disabled={!canManage}
        title={!canManage ? t('skill.detail.editDenied') : undefined}
        onClick={() => onNavigate(`/skills/${encodeURIComponent(skillKey)}/edit`)}
      >
        {t('skill.action.edit')}
      </Button>
    </div>
  );

  function renderContent() {
    if (activeTab === 'capability') return <CapabilityContent skill={skill} />;
    if (activeTab === 'resources') {
      return (
        <ResourcesContent
          skill={skill}
          onEdit={() => onNavigate(`/skills/${encodeURIComponent(skillKey)}/edit?section=dependencies`)}
        />
      );
    }
    if (activeTab === 'tests') {
      return (
        <TestWorkbench
          skill={skill}
          skillKey={skillKey}
          canTest={canTest}
          dirty={false}
          onEdit={() => onNavigate(`/skills/${encodeURIComponent(skillKey)}/edit`)}
          onRelease={() => onNavigate(`/skills/${encodeURIComponent(skillKey)}/edit?stage=release`)}
        />
      );
    }
    if (activeTab === 'versions') {
      return (
        <ReleasePanel
          skill={skill}
          canPublish={canPublish}
          dirty={false}
          onOpenTests={() => openTab('tests')}
          onOpenEditor={section => onNavigate(
            `/skills/${encodeURIComponent(skillKey)}/edit${section ? `?section=${encodeURIComponent(section)}` : ''}`,
          )}
          onPublished={() => {
            detail.refresh();
            setActiveTab('versions');
          }}
        />
      );
    }
    if (activeTab === 'analytics') return <AnalyticsContent />;
    return <OverviewContent skill={skill} onOpenTab={openTab} />;
  }

  return (
    <div className="skill-flow-page skill-detail-page">
      <SkillBreadcrumb current={skill.name || skill.key} onOpenCatalog={() => onNavigate('/skills')} />

      <section className="skill-detail-hero" aria-labelledby="skill-detail-title">
        <span className="skill-detail-icon">
          <img src={`/assets/skills/icon-${detailIcon(skill.category)}.png`} alt="" />
        </span>
        <div className="skill-detail-heading">
          <div>
            <h1 id="skill-detail-title">{skill.name || skill.key}</h1>
            <Tag color={statusTone(skill.status)}>{t(`skill.status.${skill.status}`)}</Tag>
            {skill.has_unpublished_changes && <Tag color="gold">{t('skill.catalog.unpublishedChanges')}</Tag>}
          </div>
          <p>{skill.description || t('skill.detail.noDescription')}</p>
          <div className="skill-detail-meta">
            <span>{skill.current_semver ? `v${skill.current_semver}` : t('skill.catalog.notPublished')}</span>
            <span><Avatar size={18}>{skill.updated_by?.[0] || '—'}</Avatar>{skill.updated_by || skill.created_by || '—'}</span>
            <span><ClockCircleFilled />{skill.updated_at ? dateTime(skill.updated_at) : '—'}</span>
          </div>
          <div className="skill-detail-tags">
            <Tag>{t(`skill.category.${skill.category}`)}</Tag>
            {skill.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}
          </div>
        </div>
        {actions}
        <div className="skill-detail-tabs" role="tablist" aria-label={t('skill.detail.tabsLabel')}>
          {tabIds.map((tab, index) => (
            <button
              type="button"
              key={tab}
              ref={node => { tabRefs.current[index] = node; }}
              role="tab"
              id={`skill-detail-tab-${tab}`}
              aria-selected={activeTab === tab}
              aria-controls={`skill-detail-panel-${tab}`}
              tabIndex={activeTab === tab ? 0 : -1}
              className={activeTab === tab ? 'is-active' : ''}
              onClick={() => openTab(tab)}
              onKeyDown={event => tabKeyboard(event, index)}
            >
              {t(`skill.detail.tab.${tab}`)}
            </button>
          ))}
        </div>
      </section>

      {permissions.error && (
        <Alert
          className="skill-editor-alert"
          type="warning"
          showIcon
          title={t('skill.permission.loadFailed')}
          description={errorText(permissions.error)}
          action={<Button size="small" onClick={permissions.refresh}>{t('common.retry')}</Button>}
        />
      )}

      <div className="skill-detail-dashboard">
        <main
          className="skill-detail-main"
          role="tabpanel"
          id={`skill-detail-panel-${activeTab}`}
          aria-labelledby={`skill-detail-tab-${activeTab}`}
          aria-live="polite"
        >
          {renderContent()}
        </main>
        <DetailSide
          skill={skill}
          role={permissions.data?.role ?? '—'}
          canManage={canManage}
          canTest={canTest}
          canPublish={canPublish}
        />
      </div>
    </div>
  );
}
