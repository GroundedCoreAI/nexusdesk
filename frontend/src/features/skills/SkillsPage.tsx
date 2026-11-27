import { useEffect, useState } from 'react';
import { Alert, Button, Dropdown, Empty, Input, Pagination, Select, Skeleton } from 'antd';
import {
  AppstoreFilled,
  ArrowRightOutlined,
  ArrowUpOutlined,
  EditOutlined,
  MoreOutlined,
  PlusOutlined,
  RightOutlined,
  SearchOutlined,
  StarFilled,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { errorText } from '../../i18n';
import { CreateSkillPage } from './CreateSkillPage';
import { SkillDetailPage, type SkillDetailTab } from './SkillDetailPage';
import { SkillEditor, type EditorSection } from './SkillEditor';
import {
  SKILL_CATEGORIES,
  SKILL_STATUSES,
  type SkillCategory,
  type SkillStatus,
  type SkillSummary,
} from './contracts';
import { useSkillCatalog, useSkillOverview, useSkillPermissions } from './useSkills';
import './skills.css';

type CategoryFilter = 'all' | SkillCategory;
type StatusFilter = 'all' | SkillStatus;
type SkillSort = 'latest' | 'name' | 'usage';
type SkillView = 'grid' | 'list';

// Four columns at the widest breakpoint, so 8 is exactly two full rows. The
// server pages the list; this is only the default page size.
const DEFAULT_PAGE_SIZE = 8;
const PAGE_SIZE_OPTIONS = [8, 16, 32];

const detailTabs: SkillDetailTab[] = ['overview', 'capability', 'resources', 'tests', 'versions', 'analytics'];
const editorSections: EditorSection[] = ['basic', 'capability', 'parameters', 'dependencies', 'runtime'];

// The product has no in-app documentation host yet; these point at the same
// repository the guide links to, so the rows are real destinations rather than
// dead "#" anchors. Move them to a setting when a docs site exists.
const SKILL_DOC_BASE = 'https://github.com/GroundedCoreAI/nexusdesk/tree/main/docs';
const SKILL_GUIDE_URL = `${SKILL_DOC_BASE}/requirement/skill-capability-library`;
const SKILL_RESOURCES = [
  { key: 'practices', href: SKILL_GUIDE_URL },
  { key: 'examples', href: `${SKILL_GUIDE_URL}/phase-3-skill-packaging` },
  { key: 'community', href: 'https://github.com/GroundedCoreAI/nexusdesk/discussions' },
] as const;

interface SkillsPageProps {
  route?: string;
  onNavigate?: (path: string) => void;
  onGuardChange?: (guard: ((destination?: string) => boolean) | null) => void;
}

function categoryIcon(category: SkillCategory): string {
  if (category === 'service') return 'service';
  if (category === 'finance') return 'invoice';
  if (category === 'sales') return 'sales';
  return 'flow';
}

/** Compact, locale-aware magnitude: 1.1万 in zh, 11K in en. */
function compactCount(value: number | null | undefined, locale: string): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function TrendChip({ value, unit }: { value: number | null | undefined; unit: 'percent' | 'stars' }) {
  const { t } = useTranslation();
  if (value === null || value === undefined) return null;
  const direction = value > 0 ? 'up' : value < 0 ? 'down' : 'flat';
  const magnitude = Math.abs(value);
  const label = unit === 'stars' ? magnitude.toFixed(1) : `${magnitude.toFixed(1)}%`;
  const spoken = direction === 'flat'
    ? t('skill.catalog.trend.flat')
    : t(direction === 'up' ? 'skill.catalog.trend.up {{v0}}' : 'skill.catalog.trend.down {{v0}}', { v0: label });
  return (
    <small className={`skill-metric-trend is-${direction}`} title={spoken}>
      <ArrowUpOutlined rotate={direction === 'down' ? 180 : undefined} aria-hidden="true" />
      {label}
    </small>
  );
}

function facetCount(facets: { value: string; count: number }[], value: string): number | null {
  const facet = facets.find(item => item.value === value);
  return facet ? facet.count : null;
}

function SkillSymbol({ category }: { category: SkillCategory }) {
  return (
    <span className={`skill-card-symbol skill-symbol-${category}`}>
      <img src={`/assets/skills/icon-${categoryIcon(category)}.png`} alt="" />
    </span>
  );
}

function routeQuery(route: string): URLSearchParams {
  const query = route.split('?')[1] ?? '';
  return new URLSearchParams(query);
}

export function SkillsPage({
  route = '/skills',
  onNavigate,
  onGuardChange,
}: SkillsPageProps) {
  const { t } = useTranslation();
  const navigate = onNavigate ?? ((path: string) => { window.location.hash = path; });
  const pagePath = route.split('?')[0];
  const query = routeQuery(route);

  useEffect(() => {
    if (!pagePath.match(/^\/skills\/[^/]+\/edit$/)) onGuardChange?.(null);
  }, [onGuardChange, pagePath]);

  if (pagePath === '/skills/create') {
    return <CreateSkillPage onNavigate={navigate} />;
  }

  const editMatch = /^\/skills\/([^/]+)\/edit$/.exec(pagePath);
  if (editMatch) {
    const requestedSection = query.get('section') ?? '';
    const requestedStage = query.get('stage') ?? '';
    return (
      <SkillEditor
        skillKey={decodeURIComponent(editMatch[1])}
        onNavigate={navigate}
        onGuardChange={onGuardChange}
        initialSection={editorSections.includes(requestedSection as EditorSection)
          ? requestedSection as EditorSection
          : 'basic'}
        initialStage={requestedStage === 'test' || requestedStage === 'release' ? requestedStage : 'edit'}
      />
    );
  }

  const detailMatch = /^\/skills\/([^/]+)$/.exec(pagePath);
  if (detailMatch) {
    const requestedTab = query.get('tab') ?? '';
    return (
      <SkillDetailPage
        skillKey={decodeURIComponent(detailMatch[1])}
        onNavigate={navigate}
        initialTab={detailTabs.includes(requestedTab as SkillDetailTab)
          ? requestedTab as SkillDetailTab
          : 'overview'}
      />
    );
  }

  return (
    <SkillCatalogPage
      onNavigate={navigate}
      onOpenCreate={() => navigate('/skills/create')}
    />
  );
}

function SkillCatalogPage({
  onNavigate,
  onOpenCreate,
}: {
  onNavigate: (path: string) => void;
  onOpenCreate: () => void;
}) {
  const { t, i18n } = useTranslation();
  const permissions = useSkillPermissions();
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [sort, setSort] = useState<SkillSort>('latest');
  const [view, setView] = useState<SkillView>('grid');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const catalog = useSkillCatalog({
    q: debouncedQuery,
    category,
    status,
    sort,
    page,
    page_size: pageSize,
  });
  const canManage = permissions.data?.manage ?? false;

  // Reset the page in the same commit as the query: doing it in a later effect
  // would issue a request for "new search, old offset" in between.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [query]);

  // A new filter, sort or page size re-targets the pagination: page 3 of the
  // previous result set means nothing in the new one.
  useEffect(() => {
    setPage(1);
  }, [category, status, sort, pageSize]);

  const items = catalog.data?.items ?? [];
  const overview = useSkillOverview();
  const stats = overview.data?.stats;
  const publishedCount = facetCount(catalog.data?.status_facets ?? [], 'published')
    ?? items.filter(item => item.status === 'published').length;
  const totalCount = catalog.data?.total ?? items.length;
  const lastPage = Math.max(1, Math.ceil(totalCount / pageSize));

  // Archiving or deleting Skills can shrink the list below the current page.
  // Land on the last page that still exists rather than on an empty result that
  // reads as "the catalogue is empty".
  useEffect(() => {
    if (!catalog.loading && page > lastPage) setPage(lastPage);
  }, [catalog.loading, page, lastPage]);
  const categoryOptions: CategoryFilter[] = ['all', ...SKILL_CATEGORIES];
  const statusOptions: StatusFilter[] = ['all', ...SKILL_STATUSES];
  const categoryCounts = (value: CategoryFilter) => {
    if (value === 'all') return totalCount;
    return facetCount(catalog.data?.category_facets ?? [], value)
      ?? items.filter(item => item.category === value).length;
  };
  const clearFilters = () => {
    setQuery('');
    setDebouncedQuery('');
    setCategory('all');
    setStatus('all');
    setPage(1);
  };
  const createButtonTitle = permissions.loading
    ? t('skill.permission.loading')
    : !canManage
      ? t('skill.permission.createDenied')
      : undefined;
  const listLabel = t('skill.catalog.count {{v0}}', { v0: totalCount });
  const popularItems = overview.data?.popular ?? [];
  const locale = i18n.language || 'zh-CN';
  const metricCards = [
    { key: 'total', icon: 'metric-total', tone: 'blue', value: stats?.total.value ?? totalCount, change: stats?.total.change, unit: 'percent' as const },
    { key: 'published', icon: 'metric-published', tone: 'teal', value: stats?.published.value ?? publishedCount, change: stats?.published.change, unit: 'percent' as const },
    { key: 'in_use', icon: 'metric-usage', tone: 'purple', value: stats?.in_use.value ?? null, change: stats?.in_use.change, unit: 'percent' as const },
    { key: 'rating', icon: 'metric-rating', tone: 'orange', value: stats?.rating.value ?? null, change: stats?.rating.change, unit: 'stars' as const },
  ];

  return (
    <div className="skills-page">
      <section className="skills-hero" aria-labelledby="skills-page-title">
        <div className="skills-hero-copy">
          <span className="skills-hero-eyebrow">{t('skill.catalog.eyebrow')}</span>
          <h1 id="skills-page-title">{t('skill.catalog.title')}</h1>
          <p>{t('skill.catalog.subtitle')}</p>
        </div>
        <div className="skills-hero-art" aria-hidden="true">
          <img src="/assets/skills/skill-hero-art.png" alt="" />
        </div>
      </section>

      <div className="skills-category-bar">
        <div className="skills-category-tabs" role="group" aria-label={t('skill.catalog.categoriesLabel')}>
          {categoryOptions.map(item => (
            <button
              type="button"
              key={item}
              className={category === item ? 'is-active' : ''}
              aria-pressed={category === item}
              onClick={() => setCategory(item)}
            >
              <span>{item === 'all' ? t('skill.catalog.allCategories') : t(`skill.category.${item}`)}</span>
              <small>{categoryCounts(item)}</small>
            </button>
          ))}
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!canManage}
          title={createButtonTitle}
          onClick={onOpenCreate}
        >
          {t('skill.action.create')}
        </Button>
      </div>

      {permissions.error && (
        <Alert
          className="skill-catalog-alert"
          type="warning"
          showIcon
          title={t('skill.permission.loadFailed')}
          description={errorText(permissions.error)}
          action={<Button size="small" onClick={permissions.refresh}>{t('common.retry')}</Button>}
        />
      )}

      <div className="skills-dashboard">
        <main className="skills-main-column">
          <section className="skills-metrics" aria-label={t('skill.catalog.metricsLabel')}>
            {metricCards.map(card => (
              <article className="skill-metric" key={card.key}>
                <span className={`metric-icon metric-icon-${card.tone}`}>
                  <img src={`/assets/skills/${card.icon}.png`} alt="" />
                </span>
                <div>
                  <span>{t(`skill.catalog.metric.${card.key}`)}</span>
                  <strong>
                    {card.unit === 'stars'
                      ? card.value === null
                        ? '—'
                        : Number(card.value).toFixed(1)
                      : card.value ?? '—'}
                  </strong>
                  <TrendChip value={card.change} unit={card.unit} />
                </div>
              </article>
            ))}
          </section>

          <section className="skills-catalog-panel" aria-label={t('skill.catalog.listTitle')}>
            {/* The heading is gone from the layout on purpose — the page title and
                the metric strip already say what this is. Keep the count in the
                accessibility tree so filtering changes are still announced. */}
            <p className="sr-only" aria-live="polite">{listLabel}</p>
            <div className="skills-toolbar">
              <Input
                className="skills-search"
                prefix={<SearchOutlined />}
                value={query}
                onChange={event => setQuery(event.target.value)}
                placeholder={t('skill.catalog.searchPlaceholder')}
                aria-label={t('skill.catalog.searchLabel')}
                allowClear
              />
              <Select<StatusFilter>
                value={status}
                onChange={setStatus}
                aria-label={t('skill.catalog.filterStatus')}
                options={statusOptions.map(item => ({
                  value: item,
                  label: item === 'all' ? t('skill.catalog.allStatuses') : t(`skill.status.${item}`),
                }))}
              />
              <Select<CategoryFilter>
                value={category}
                onChange={setCategory}
                aria-label={t('skill.catalog.filterCategory')}
                options={categoryOptions.map(item => ({
                  value: item,
                  label: item === 'all' ? t('skill.catalog.allCategories') : t(`skill.category.${item}`),
                }))}
              />
              <Select<SkillSort>
                value={sort}
                onChange={setSort}
                aria-label={t('skill.catalog.sortLabel')}
                options={[
                  { value: 'latest', label: t('skill.catalog.sort.latest') },
                  { value: 'usage', label: t('skill.catalog.sort.usage') },
                  { value: 'name', label: t('skill.catalog.sort.name') },
                ]}
              />
              <div className="skills-view-switch" role="group" aria-label={t('skill.catalog.viewLabel')}>
                <button
                  type="button"
                  className={view === 'grid' ? 'is-active' : ''}
                  aria-label={t('skill.catalog.view.grid')}
                  aria-pressed={view === 'grid'}
                  onClick={() => setView('grid')}
                >
                  <AppstoreFilled />
                </button>
                <button
                  type="button"
                  className={view === 'list' ? 'is-active' : ''}
                  aria-label={t('skill.catalog.view.list')}
                  aria-pressed={view === 'list'}
                  onClick={() => setView('list')}
                >
                  <UnorderedListOutlined />
                </button>
              </div>
            </div>

            {catalog.loading && items.length === 0 && (
              <div className="skills-card-grid" data-testid="skill-catalog-loading" aria-busy="true">
                {[0, 1, 2, 3].map(index => (
                  <article className="skill-card skill-card-loading" key={index}>
                    <Skeleton active title paragraph={{ rows: 3 }} />
                  </article>
                ))}
              </div>
            )}
            {catalog.error && (
              <div className="skill-catalog-state" role="alert">
                <Alert
                  type="error"
                  showIcon
                  title={t('skill.catalog.loadFailed')}
                  description={errorText(catalog.error)}
                />
                <div className="skill-state-actions">
                  <Button onClick={catalog.refresh}>{t('common.retry')}</Button>
                </div>
              </div>
            )}
            {/* Only a truly empty catalogue gets the empty state. An offset past
                the end is corrected by the effect above, so showing "no Skills"
                for that frame would be a lie. */}
            {!catalog.loading && !catalog.error && items.length === 0 && totalCount === 0 && (
              <div className="skills-empty">
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('skill.catalog.emptyBody')} />
                <div className="skill-state-actions">
                  <Button onClick={clearFilters}>{t('skill.catalog.clearFilters')}</Button>
                  <Button type="primary" disabled={!canManage} title={createButtonTitle} onClick={onOpenCreate}>
                    {t('skill.action.create')}
                  </Button>
                </div>
              </div>
            )}
            {!catalog.error && items.length > 0 && (
              <div className={`skills-card-grid ${view === 'list' ? 'is-list' : ''}`}>
                {items.map(skill => (
                  <article
                    className="skill-card"
                    key={skill.key}
                    data-testid="skill-card"
                    data-skill-key={skill.key}
                    role="button"
                    tabIndex={0}
                    onClick={() => onNavigate(`/skills/${encodeURIComponent(skill.key)}`)}
                    onKeyDown={event => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onNavigate(`/skills/${encodeURIComponent(skill.key)}`);
                      }
                    }}
                  >
                    <div className="skill-card-top">
                      <SkillSymbol category={skill.category} />
                      <span className={`skill-status skill-status-${skill.status}`}>
                        {t(`skill.status.${skill.status}`)}
                      </span>
                    </div>
                    <h2>{skill.name || skill.key}</h2>
                    <p>{skill.description || t('skill.catalog.noDescription')}</p>
                    <div className="skill-tags">
                      <span className="skill-category-tag">{t(`skill.category.${skill.category}`)}</span>
                      {skill.tags.slice(0, 2).map(tag => <span key={tag}>{tag}</span>)}
                      {skill.has_unpublished_changes && (
                        <span className="skill-flag">{t('skill.catalog.unpublishedChanges')}</span>
                      )}
                    </div>
                    <footer className="skill-card-foot">
                      <span className="skill-card-usage">
                        <span>{t('skill.catalog.usagePrefix')}</span>
                        <b>{compactCount(skill.usage_count, locale)}</b>
                        <span>{t('skill.catalog.usageSuffix')}</span>
                        <i aria-hidden="true">·</i>
                        {skill.rating_avg === null ? (
                          <span className="skill-card-rating is-empty">{t('skill.catalog.noRating')}</span>
                        ) : (
                          <span
                            className="skill-card-rating"
                            title={t('skill.catalog.ratingDetail {{v0}}', { v0: compactCount(skill.rating_count, locale) })}
                          >
                            <StarFilled aria-hidden="true" />
                            <b>{skill.rating_avg.toFixed(1)}</b>
                          </span>
                        )}
                      </span>
                      <Dropdown
                        trigger={['click']}
                        menu={{
                          items: [
                            {
                              key: 'edit',
                              icon: <EditOutlined />,
                              label: t('skill.action.edit'),
                              disabled: !canManage,
                              onClick: () => onNavigate(`/skills/${encodeURIComponent(skill.key)}/edit`),
                            },
                          ],
                        }}
                      >
                        <Button
                          type="text"
                          className="skill-card-more"
                          icon={<MoreOutlined />}
                          disabled={!canManage}
                          title={!canManage ? t('skill.catalog.editDenied') : undefined}
                          aria-label={t('skill.catalog.moreActions {{v0}}', { v0: skill.name || skill.key })}
                          onClick={event => event.stopPropagation()}
                        />
                      </Dropdown>
                    </footer>
                  </article>
                ))}
              </div>
            )}
            {!catalog.error && items.length > 0 && (
              <div className="skills-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={totalCount}
                  showSizeChanger
                  pageSizeOptions={PAGE_SIZE_OPTIONS}
                  showTotal={count => t('skill.catalog.pageTotal {{v0}}', { v0: count })}
                  onChange={(next, nextSize) => {
                    // Changing the page size keeps the reader at the top of the
                    // list instead of at an offset that no longer lines up.
                    if (nextSize !== pageSize) {
                      setPageSize(nextSize);
                      setPage(1);
                      return;
                    }
                    setPage(next);
                  }}
                />
              </div>
            )}
          </section>
        </main>

        <aside className="skills-side-column" aria-label={t('skill.catalog.sideLabel')}>
          <section className="skills-side-card skills-popular">
            <div className="skills-side-heading">
              <h2>{t('skill.catalog.side.popularTitle')}</h2>
              <Button type="link" onClick={() => setSort('usage')}>{t('skill.catalog.side.viewAll')}</Button>
            </div>
            {popularItems.length > 0 ? popularItems.map((item, index) => (
              <button
                type="button"
                className="popular-row popular-row-button"
                key={item.key}
                onClick={() => onNavigate(`/skills/${encodeURIComponent(item.key)}`)}
              >
                <span className={`popular-rank rank-${index + 1}`}>{index + 1}</span>
                <span className="popular-row-copy">
                  <strong>{item.name || item.key}</strong>
                </span>
                <span className="popular-rate">
                  {item.success_rate === null ? '—' : `${(item.success_rate * 100).toFixed(1)}%`}
                </span>
              </button>
            )) : (
              <div className="skill-side-empty">
                <p>{overview.loading ? t('common.loading') : t('skill.catalog.side.popularEmpty')}</p>
              </div>
            )}
          </section>

          <section className="skills-side-card skills-guide">
            <div className="guide-copy">
              <h2>{t('skill.catalog.side.guideTitle')}</h2>
              <p>{t('skill.catalog.side.guideBody')}</p>
              <Button
                type="primary"
                href={SKILL_GUIDE_URL}
                target="_blank"
                rel="noreferrer"
              >
                {t('skill.catalog.side.guideAction')}<ArrowRightOutlined />
              </Button>
            </div>
            <img className="guide-robot" src="/assets/skills/skill-guide-robot.png" alt="" aria-hidden="true" />
          </section>

          <section className="skills-side-card skills-resources">
            <div className="skills-side-heading">
              <h2>{t('skill.catalog.side.resourcesTitle')}</h2>
            </div>
            <ul>
              {SKILL_RESOURCES.map(resource => (
                <li key={resource.key}>
                  <a href={resource.href} target="_blank" rel="noreferrer">
                    <RightOutlined aria-hidden="true" />
                    {t(`skill.catalog.side.resource.${resource.key}`)}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}

