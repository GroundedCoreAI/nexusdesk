import { useMemo, useRef, useState } from 'react';
import { Button, Input } from 'antd';
import {
  AppstoreFilled,
  ArrowRightOutlined,
  AuditOutlined,
  BarChartOutlined,
  BookFilled,
  CarryOutFilled,
  CheckCircleFilled,
  CheckSquareFilled,
  ClockCircleFilled,
  DatabaseFilled,
  ExclamationCircleFilled,
  FileFilled,
  FundFilled,
  HeartFilled,
  HomeOutlined,
  MessageFilled,
  SafetyCertificateFilled,
  SendOutlined,
  SettingFilled,
  SettingOutlined,
  ThunderboltFilled,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import './enterprise.css';

type SeriesKey = 'service' | 'finance' | 'sales' | 'research';

type MetricSpec = {
  key: string;
  value: string;
  delta: string;
  tone: 'blue' | 'green' | 'orange' | 'red';
  spark?: number[];
  sparkTone?: string;
};

type TodoSpec = { key: string; tone: 'blue' | 'purple'; iconTone: 'blue' | 'orange' | 'purple'; title: string; time: string };

/** Enterprise aggregates have no backend endpoints yet — single swap point. */
const DEMO = {
  metrics: [
    { key: 'tasks', value: '12.8万', delta: '↑12.5%', tone: 'blue', spark: [32, 38, 35, 42, 40, 46, 44, 52] } satisfies MetricSpec,
    { key: 'success', value: '98.2%', delta: '↑0.3%', tone: 'green', spark: [88, 90, 89, 92, 91, 94, 93, 96] },
    { key: 'duration', value: '28s', delta: '↓8.7%', tone: 'blue', spark: [46, 42, 44, 38, 36, 34, 30, 28], sparkTone: 'teal' },
    { key: 'satisfaction', value: '96.5%', delta: '↑1.2%', tone: 'orange', spark: [80, 84, 83, 88, 90, 89, 92, 95], sparkTone: 'purple' },
    { key: 'pending', value: '23', delta: '', tone: 'red' },
  ],
  days: ['08-13', '08-14', '08-15', '08-16', '08-17', '08-18', '08-19'],
  series: {
    service: [2800, 3200, 2950, 3400, 3520, 3350, 3620],
    finance: [2100, 2400, 2250, 2500, 2680, 2550, 2760],
    sales: [1500, 1750, 1600, 1850, 1980, 1900, 2080],
    research: [900, 1050, 1100, 1200, 1250, 1300, 1420],
  } as Record<SeriesKey, number[]>,
  seriesMax: 6000,
  agents: {
    rate: 98.2,
    online: 48,
    busy: 12,
    offline: 6,
    trend: [28, 36, 32, 40, 34, 44, 38, 48, 42, 52, 46, 56, 50, 58, 54, 62],
  },
  todos: [
    { key: 'service', tone: 'blue', iconTone: 'blue', title: '客户咨询：订单异常未发货，请协助处理', time: '23分钟前' },
    { key: 'finance', tone: 'purple', iconTone: 'orange', title: '报销申请：金额异常，请核实', time: '5分钟前' },
    { key: 'sales', tone: 'blue', iconTone: 'blue', title: '销售线索：高意向客户跟进', time: '8分钟前' },
  ] satisfies TodoSpec[],
  health: { availability: '99.9%', response: '95 ms' },
};

const SHORTCUTS = [
  { key: 'appCenter', icon: <AppstoreFilled />, tint: 'blue', target: 'service-apps' },
  { key: 'taskCenter', icon: <CarryOutFilled />, tint: 'blue', target: '' },
  { key: 'knowledge', icon: <BookFilled />, tint: 'blue', target: 'knowledge' },
  { key: 'analytics', icon: <FundFilled />, tint: 'blue', target: '' },
  { key: 'approval', icon: <CheckSquareFilled />, tint: 'orange', target: 'approvals' },
  { key: 'settings', icon: <SettingFilled />, tint: 'teal', target: 'access' },
] as const;

const SERIES_META: Array<{ key: SeriesKey; colorVar: string; legendKey: string }> = [
  { key: 'service', colorVar: 'var(--sk-blue)', legendKey: 'service' },
  { key: 'finance', colorVar: 'var(--sk-accent-purple)', legendKey: 'finance' },
  { key: 'sales', colorVar: 'var(--sk-accent-orange)', legendKey: 'sales' },
  { key: 'research', colorVar: 'var(--sk-accent-teal)', legendKey: 'research' },
];

/** Catmull-Rom → cubic bezier for smooth multi-series lines. */
function smoothPath(values: number[], width: number, height: number, max: number) {
  const step = width / Math.max(values.length - 1, 1);
  const points = values.map((value, index) => [index * step, height - (value / max) * height] as const);
  let path = `M${points[0][0].toFixed(1)},${points[0][1].toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const previous = points[i - 1] || points[i];
    const current = points[i];
    const next = points[i + 1];
    const after = points[i + 2] || next;
    const c1x = current[0] + (next[0] - previous[0]) / 6;
    const c1y = current[1] + (next[1] - previous[1]) / 6;
    const c2x = next[0] - (after[0] - current[0]) / 6;
    const c2y = next[1] - (after[1] - current[1]) / 6;
    path += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${next[0].toFixed(1)},${next[1].toFixed(1)}`;
  }
  return path;
}

function Sparkline({ values, tone }: { values: number[]; tone: string }) {
  const width = 84;
  const height = 30;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = Math.max(max - min, 1);
  const points = values.map((value, index) =>
    `${((index / (values.length - 1)) * width).toFixed(1)},${(height - ((value - min) / span) * (height - 4) - 2).toFixed(1)}`,
  ).join(' ');
  return (
    <svg className={`ep-spark tone-${tone}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} />
    </svg>
  );
}

export function EnterpriseWorkspacePage({ onNavigate }: { onNavigate?: (path: string) => void }) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<'all' | SeriesKey>('all');
  const [activeDay, setActiveDay] = useState(4);
  const [draft, setDraft] = useState('');
  const plotRef = useRef<HTMLDivElement | null>(null);

  const visibleSeries = useMemo(
    () => SERIES_META.filter(item => filter === 'all' || item.key === filter),
    [filter],
  );

  const chartWidth = 560;
  const chartHeight = 190;
  function pickDay(event: React.MouseEvent) {
    const rect = plotRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
    setActiveDay(Math.round(ratio * (DEMO.days.length - 1)));
  }

  const trendMax = Math.max(...DEMO.agents.trend);

  return <div className="enterprise-page">
    <section className="ep-hero">
      <div className="ep-hero-copy">
        <span className="ep-hero-badge">{t('enterprise.hero.badge')}</span>
        <h1 className="ep-hero-title">{t('enterprise.hero.title')}</h1>
        <p className="ep-hero-sub">{t('enterprise.hero.subtitle')}</p>
      </div>
      <Button type="text" className="ep-hero-more">{t('enterprise.hero.more')}<ArrowRightOutlined /></Button>
      <div className="ep-hero-art" aria-hidden="true"><img src="/assets/enterprise/hero-city.svg" alt="" /></div>
    </section>

    <div className="ep-metrics">
      {DEMO.metrics.map(metric => <article key={metric.key} className={`ep-metric tone-${metric.tone}`}>
        <span className="ep-metric-icon"><MetricIcon metricKey={metric.key} tone={metric.tone} /></span>
        <div className="ep-metric-copy">
          <small className="ep-metric-label">{t(`enterprise.metric.${metric.key}`)}</small>
          <strong className="ep-metric-value">{metric.value}</strong>
          {metric.delta
            ? <em className="ep-metric-delta">{metric.delta}</em>
            : <em className="ep-metric-delta ep-metric-meta">{t('enterprise.metric.pendingMeta')}</em>}
        </div>
        {metric.spark && <Sparkline values={metric.spark} tone={metric.sparkTone ?? metric.tone} />}
        {metric.key === 'pending' && <ArrowRightOutlined className="ep-metric-arrow" />}
      </article>)}
    </div>

    <div className="ep-row-main">
      <section className="ep-panel ep-overview" aria-label={t('enterprise.overview.title')}>
        <header className="ep-panel-head">
          <h2 className="ep-panel-title">{t('enterprise.overview.title')}</h2>
          <Button type="link" size="small" className="ep-link">{t('enterprise.overview.all')}<ArrowRightOutlined /></Button>
        </header>
        <div className="ep-pills" role="tablist" aria-label={t('enterprise.filter.label')}>
          {(['all', 'service', 'finance', 'sales', 'research'] as const).map(key => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={filter === key}
              className={`ep-pill ${filter === key ? 'is-active' : ''}`}
              onClick={() => setFilter(key)}
            >
              {key === 'all' ? t('enterprise.filter.all') : t(`enterprise.filter.${key}`)}
            </button>
          ))}
        </div>
        <div className="ep-chart">
          <ul className="ep-chart-axis">
            <li>6k</li><li>4k</li><li>2k</li><li>0</li>
          </ul>
          <div className="ep-plot" ref={plotRef} onMouseMove={pickDay} onMouseLeave={() => setActiveDay(4)}>
            <div className="ep-legend">
              {visibleSeries.map(item => (
                <span key={item.key}><i style={{ background: item.colorVar }} />{t(`enterprise.legend.${item.legendKey}`)}</span>
              ))}
            </div>
            <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none" aria-hidden="true">
              {[0, 1, 2, 3].map(row => <line
                key={row}
                x1="0"
                x2={chartWidth}
                y1={(chartHeight / 3) * row}
                y2={(chartHeight / 3) * row}
                className="ep-grid-line"
              />)}
              {visibleSeries.map(item => (
                <path key={item.key} d={smoothPath(DEMO.series[item.key], chartWidth, chartHeight, DEMO.seriesMax)} style={{ stroke: item.colorVar }} />
              ))}
              {visibleSeries.map(item => DEMO.series[item.key].map((value, i) => (
                <circle
                  key={`${item.key}-pt-${i}`}
                  cx={(i / (DEMO.days.length - 1)) * chartWidth}
                  cy={chartHeight - (value / DEMO.seriesMax) * chartHeight}
                  r="3"
                  style={{ fill: item.colorVar }}
                />
              )))}
              <line
                x1={(activeDay / (DEMO.days.length - 1)) * chartWidth}
                x2={(activeDay / (DEMO.days.length - 1)) * chartWidth}
                y1="0"
                y2={chartHeight}
                className="ep-cursor-line"
              />
            </svg>
            <div className="ep-tooltip" style={{ left: `${(activeDay / (DEMO.days.length - 1)) * 100}%` }}>
              <b className="ep-tooltip-day">{DEMO.days[activeDay]}</b>
              {visibleSeries.map(item => (
                <span key={item.key} className="ep-tooltip-row">
                  <i style={{ background: item.colorVar }} />
                  {t(`enterprise.legend.${item.legendKey}`)} {DEMO.series[item.key][activeDay].toLocaleString()}
                </span>
              ))}
            </div>
          </div>
        </div>
        <ul className="ep-chart-days">
          {DEMO.days.map(day => <li key={day}>{day}</li>)}
        </ul>
      </section>

      <section className="ep-panel ep-agents" aria-label={t('enterprise.agents.title')}>
          <header className="ep-panel-head">
            <h2 className="ep-panel-title">{t('enterprise.agents.title')}</h2>
            <Button type="link" size="small" className="ep-link">{t('enterprise.agents.viewAll')}<ArrowRightOutlined /></Button>
          </header>
          <div className="ep-agents-body">
            <div className="ep-ring" style={{ ['--pct' as string]: `${DEMO.agents.rate * 3.6}deg` }}>
              <span className="ep-ring-value">{DEMO.agents.rate}%</span>
              <small className="ep-ring-label">{t('enterprise.agents.onlineRate')}</small>
            </div>
            <ul className="ep-agent-stats">
              <li><i className="ep-dot dot-green" /><span className="ep-agent-name">{t('enterprise.agents.online')}</span><b className="ep-agent-count">{DEMO.agents.online}</b></li>
              <li><i className="ep-dot dot-orange" /><span className="ep-agent-name">{t('enterprise.agents.busy')}</span><b className="ep-agent-count">{DEMO.agents.busy}</b></li>
              <li><i className="ep-dot dot-red" /><span className="ep-agent-name">{t('enterprise.agents.offline')}</span><b className="ep-agent-count">{DEMO.agents.offline}</b></li>
            </ul>
          </div>
          <div className="ep-trend">
            <small className="ep-trend-label">{t('enterprise.agents.trend')}</small>
            <div className="ep-trend-bars" aria-hidden="true">
              {DEMO.agents.trend.map((value, index) => (
                <i key={index} style={{ height: `${Math.max((value / trendMax) * 100, 12)}%` }} />
              ))}
            </div>
          </div>
        </section>

        <section className="ep-panel ep-shortcuts" aria-label={t('enterprise.shortcuts.title')}>
          <header className="ep-panel-head"><h2 className="ep-panel-title">{t('enterprise.shortcuts.title')}</h2></header>
          <div className="ep-shortcut-grid">
            {SHORTCUTS.map(item => (
              <button
                key={item.key}
                type="button"
                className="ep-shortcut"
                disabled={!item.target}
                onClick={() => { if (item.target && onNavigate) onNavigate(`/${item.target}`); }}
              >
                <span className={`ep-shortcut-icon tint-${item.tint}`}>{item.icon}</span>
                <span>{t(`enterprise.shortcut.${item.key}`)}</span>
              </button>
            ))}
          </div>
        </section>
    </div>

    <div className="ep-row-bottom">
      <section className="ep-panel ep-todo" aria-label={t('enterprise.todo.title')}>
        <header className="ep-panel-head">
          <h2 className="ep-panel-title">{t('enterprise.todo.title')}</h2>
          <Button type="link" size="small" className="ep-link">{t('enterprise.todo.viewAll')}<ArrowRightOutlined /></Button>
        </header>
        <ul className="ep-todo-list">
          {DEMO.todos.map(todo => <li key={todo.key}>
            <span className={`ep-todo-icon tone-${todo.iconTone}`}>{todo.key === 'service' ? <MessageFilled /> : todo.key === 'finance' ? <FileFilled /> : <ThunderboltFilled />}</span>
            <div className="ep-todo-copy">
              <b className="ep-todo-title">{t(`enterprise.todo.${todo.key}Full`)}</b>
            </div>
            <span className={`ep-todo-tag tone-${todo.tone}`}>{t(`enterprise.tag.${todo.key}`)}</span>
            <time>{t(`enterprise.todo.${todo.key}Time`)}</time>
          </li>)}
        </ul>
      </section>

      <section className="ep-panel ep-health" aria-label={t('enterprise.health.title')}>
        <header className="ep-panel-head">
          <h2 className="ep-panel-title">{t('enterprise.health.title')}</h2>
          <Button type="link" size="small" className="ep-link">{t('enterprise.health.detail')}<ArrowRightOutlined /></Button>
        </header>
        <div className="ep-health-body">
          <div className="ep-health-status">
            <span className="ep-health-shield"><SafetyCertificateFilled /></span>
            <div><b className="ep-health-name">{t('enterprise.health.status')}</b><small className="ep-health-desc">{t('enterprise.health.statusDesc')}</small></div>
          </div>
          <div className="ep-health-stats">
            <div><strong className="ep-health-value">{DEMO.health.availability}</strong><small className="ep-health-label">{t('enterprise.health.availability')}</small></div>
            <div><strong className="ep-health-value">{DEMO.health.response}</strong><small className="ep-health-label">{t('enterprise.health.response')}</small></div>
          </div>
        </div>
      </section>

      <section className="ep-panel ep-assistant" aria-label={t('enterprise.assistant.title')}>
        <header className="ep-panel-head">
          <h2 className="ep-panel-title">{t('enterprise.assistant.title')}</h2>
          <Button type="link" size="small" className="ep-link">{t('enterprise.assistant.more')}<ArrowRightOutlined /></Button>
        </header>
        <div className="ep-assistant-body">
          <span className="ep-assistant-face"><img src="/assets/skills/skill-guide-robot.png" alt="" /></span>
          <div className="ep-assistant-bubble">
            <p className="ep-assistant-text">{t('enterprise.assistant.greeting')}</p>
            <ul>
              <li>{t('enterprise.assistant.item1')}</li>
              <li>{t('enterprise.assistant.item2')}</li>
              <li>{t('enterprise.assistant.item3')}</li>
            </ul>
          </div>
        </div>
        <form className="ep-assistant-form" onSubmit={event => { event.preventDefault(); setDraft(''); }}>
          <Input variant="borderless" value={draft} onChange={event => setDraft(event.target.value)} placeholder={t('enterprise.assistant.placeholder')} />
          <Button type="primary" shape="circle" htmlType="submit" icon={<SendOutlined />} aria-label={t('enterprise.assistant.send')} />
        </form>
      </section>
    </div>
  </div>;
}

function MetricIcon({ metricKey, tone }: { metricKey: string; tone: string }) {
  if (metricKey === 'tasks') return <DatabaseFilled />;
  if (tone === 'green') return <CheckCircleFilled />;
  if (tone === 'orange') return <HeartFilled />;
  if (tone === 'red') return <ExclamationCircleFilled />;
  return <ClockCircleFilled />;
}

const PLACEHOLDER_META = {
  finance: { icon: <AuditOutlined />, tint: 'purple' },
  sales: { icon: <BarChartOutlined />, tint: 'orange' },
  development: { icon: <SettingOutlined />, tint: 'teal' },
} as const;

/** Stand-in page for business spaces that are not onboarded yet. */
export function SpacePlaceholderPage({ kind }: { kind: 'finance' | 'sales' | 'development' }) {
  const { t } = useTranslation();
  const meta = PLACEHOLDER_META[kind];
  return <div className="enterprise-page">
    <section className="ep-panel ep-coming">
      <span className={`ep-coming-icon tint-${meta.tint}`}>{meta.icon}</span>
      <h1 className="ep-coming-title">{t('enterprise.coming.title {{v0}}', { v0: t(`enterprise.filter.${kind === 'development' ? 'research' : kind}`) })}</h1>
      <p className="ep-coming-desc">{t('enterprise.coming.desc')}</p>
      <Button type="primary" icon={<HomeOutlined />} onClick={() => { window.location.hash = '#/enterprise'; }}>
        {t('enterprise.coming.back')}
      </Button>
    </section>
  </div>;
}
