import { useState } from 'react';
import { Button, Input, Select } from 'antd';
import {
  ArrowRightOutlined,
  BarChartOutlined,
  BookOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CodeOutlined,
  CustomerServiceOutlined,
  LineChartOutlined,
  MessageOutlined,
  MinusOutlined,
  PlusOutlined,
  SendOutlined,
  ThunderboltOutlined,
  WalletOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { Agent, Summary } from '../../shared/api/client';
import { useResource } from '../../shared/components/ui';
import './overview.css';

type SceneKey = 'service' | 'finance' | 'sales' | 'research' | 'more';

type RingSpec = { key: string; value: number };

/** Fallback numbers, used until the aggregate endpoints exist. */
const DEMO = {
  conversations: [52000, 61000, 58000, 74000, 88000, 82000, 101000],
  tickets: [31000, 38000, 42000, 40000, 56000, 61000, 72000],
  satisfaction: 92.3,
  todos: [
    { id: 'refund', tone: 'warning' as const, title: '需要人工审核：大额退款申请', meta: '工单 #TK2025001', time: '10:24' },
    { id: 'complaint', tone: 'info' as const, title: '客户投诉待处理', meta: '来自：张先生', time: '10:20' },
    { id: 'done', tone: 'success' as const, title: 'AI 处理完成：订单咨询', meta: '已自动回复', time: '09:50' },
  ],
  shortcuts: [
    { key: 'ticket', icon: <MessageOutlined />, tint: 'blue' as const },
    { key: 'agent', icon: <ThunderboltOutlined />, tint: 'orange' as const },
    { key: 'knowledge', icon: <BookOutlined />, tint: 'teal' as const },
    { key: 'report', icon: <BarChartOutlined />, tint: 'purple' as const },
  ],
};

const SCENES: Array<{ key: SceneKey; icon: React.ReactNode; tint: string }> = [
  { key: 'service', icon: <CustomerServiceOutlined />, tint: 'blue' },
  { key: 'finance', icon: <WalletOutlined />, tint: 'teal' },
  { key: 'sales', icon: <LineChartOutlined />, tint: 'blue' },
  { key: 'research', icon: <CodeOutlined />, tint: 'purple' },
  { key: 'more', icon: <PlusOutlined />, tint: 'purple' },
];

function compact(value: number) {
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return String(value);
}

/** Catmull-Rom → cubic bezier, so the two series read as smooth curves. */
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

export function OverviewPage() {
  const { t } = useTranslation();
  const summary = useResource<Summary>('/observability/summary', 15000);
  const agents = useResource<Agent[]>('/agents', 30000);
  const [scene, setScene] = useState<SceneKey>('service');
  const [range, setRange] = useState('week');
  const [draft, setDraft] = useState('');

  const data = summary.data;
  const total = data && data.total > 0 ? data.total : 128000;
  const completed = data && data.total > 0 ? data.completed : 93600;
  const resolvedRate = total > 0 ? (completed / total) * 100 : 93.6;
  const avgSeconds = data?.average_seconds ?? 28;
  const rings: RingSpec[] = [
    { key: 'availability', value: data && data.total > 0 ? Math.max(0, 100 - (data.failed / data.total) * 100) : 98.2 },
    { key: 'success', value: resolvedRate },
    { key: 'satisfaction', value: DEMO.satisfaction },
  ];

  const liveAgents = (agents.data || []).filter(agent => !agent.archived).slice(0, 3);
  const agentRows = liveAgents.length
    ? liveAgents.map(agent => ({ id: agent.id, name: agent.name, meta: agent.description }))
    : [
        { id: 'service', name: t('overview.agent.service'), meta: t('overview.agent.serviceMeta') },
        { id: 'sales', name: t('overview.agent.sales'), meta: t('overview.agent.salesMeta') },
        { id: 'research', name: t('overview.agent.research'), meta: t('overview.agent.researchMeta') },
      ];

  const chartWidth = 460;
  const chartHeight = 118;
  const chartMax = 150000;
  const conversations = smoothPath(DEMO.conversations, chartWidth, chartHeight, chartMax);
  const tickets = smoothPath(DEMO.tickets, chartWidth, chartHeight, chartMax);
  const weekdays = ['overview.weekday.mon', 'overview.weekday.tue', 'overview.weekday.wed', 'overview.weekday.thu', 'overview.weekday.fri', 'overview.weekday.sat', 'overview.weekday.sun'];

  return <div className="overview-page">
    <section className="ov-hero">
      <div className="ov-hero-copy">
        <h1>{t('overview.hero.title')}</h1>
        <p>{t('overview.hero.subtitle')}</p>
        <button type="button" className="ov-hero-pill">
          {t('overview.hero.pending {{v0}}', { v0: DEMO.todos.length })}
          <ArrowRightOutlined />
        </button>
      </div>
      <div className="ov-hero-art" aria-hidden="true"><img src="/assets/skills/skill-guide-robot.png" alt="" /></div>
    </section>

    <div className="ov-scenes" role="tablist" aria-label={t('overview.scenes.label')}>
      {SCENES.map(item => <button
        key={item.key}
        type="button"
        role="tab"
        aria-selected={scene === item.key}
        className={`ov-scene ${scene === item.key ? 'is-active' : ''}`}
        onClick={() => setScene(item.key)}
      >
        <span className={`ov-scene-icon tint-${item.tint}`}>{item.icon}</span>
        <span className="ov-scene-copy">
          <b>{t(`overview.scene.${item.key}.title`)}</b>
          <small>{t(`overview.scene.${item.key}.desc`)}</small>
        </span>
        <ArrowRightOutlined className="ov-scene-arrow" />
      </button>)}
    </div>

    <div className="ov-dashboard">
      <div className="ov-main">
        <section className="ov-panel ov-summary" aria-label={t('overview.summary.title')}>
          <header className="ov-panel-head">
            <h2>{t('overview.summary.title')}</h2>
            <Select
              size="small"
              variant="borderless"
              value={range}
              onChange={setRange}
              options={[{ value: 'week', label: t('overview.range.week') }, { value: 'month', label: t('overview.range.month') }]}
              className="ov-range"
            />
          </header>
          <div className="ov-summary-body">
            <div className="ov-metrics">
              <article className="ov-metric">
                <span className="ov-metric-icon tint-blue"><MessageOutlined /></span>
                <small>{t('overview.metric.conversations')}</small>
                <strong>{compact(total)}</strong>
                <em className="is-up">↑ 12.5%</em>
              </article>
              <article className="ov-metric">
                <span className="ov-metric-icon tint-teal"><CheckCircleFilled /></span>
                <small>{t('overview.metric.resolved')}</small>
                <strong>{resolvedRate.toFixed(1)}%</strong>
                <em className="is-up">↑ 1.2%</em>
              </article>
              <article className="ov-metric">
                <span className="ov-metric-icon tint-blue"><ClockCircleOutlined /></span>
                <small>{t('overview.metric.response')}</small>
                <strong>{Math.round(avgSeconds)}s</strong>
                <em className="is-down">↓ 8.7%</em>
              </article>
              <article className="ov-metric">
                <span className="ov-metric-icon tint-purple"><ThunderboltOutlined /></span>
                <small>{t('overview.metric.tickets')}</small>
                <strong>{compact(completed)}</strong>
                <em className="is-up">↑ 10.1%</em>
              </article>
            </div>
            <figure className="ov-chart">
              <figcaption className="ov-legend">
                <span><i className="dot-blue" />{t('overview.legend.conversations')}</span>
                <span><i className="dot-purple" />{t('overview.legend.tickets')}</span>
              </figcaption>
              <div className="ov-chart-body">
                <ul className="ov-chart-axis">
                  <li>150k</li><li>100k</li><li>50k</li><li>0</li>
                </ul>
                <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none" aria-hidden="true">
                  {[0, 1, 2, 3].map(row => <line
                    key={row}
                    x1="0"
                    x2={chartWidth}
                    y1={(chartHeight / 3) * row}
                    y2={(chartHeight / 3) * row}
                    className="ov-grid-line"
                  />)}
                  <path d={tickets} className="ov-line-purple" />
                  <path d={conversations} className="ov-line-blue" />
                </svg>
              </div>
              <ul className="ov-chart-days">{weekdays.map(key => <li key={key}>{t(key)}</li>)}</ul>
            </figure>
          </div>
        </section>

        <div className="ov-pair">
          <section className="ov-panel ov-agents" aria-label={t('overview.agents.title')}>
            <header className="ov-panel-head"><h2>{t('overview.agents.title')}</h2></header>
            <div className="ov-agent-row">
              {agentRows.map((agent, index) => <article key={agent.id} className="ov-agent-card">
                <span className={`ov-agent-face tint-${['blue', 'teal', 'purple'][index] || 'blue'}`}>
                  {agent.name.slice(0, 1)}
                </span>
                <div>
                  <b>{agent.name}</b>
                  <small>
                    <i className="ov-online-dot" />
                    {t('overview.agents.online {{v0}}', { v0: [8, 12, 3][index] ?? 0 })}
                  </small>
                </div>
                <ArrowRightOutlined className="ov-agent-arrow" />
              </article>)}
            </div>
          </section>

          <section className="ov-panel ov-health" aria-label={t('overview.health.title')}>
            <header className="ov-panel-head">
              <h2>{t('overview.health.title')}</h2>
              <span className="ov-health-badge">{t('overview.health.normal')}</span>
            </header>
            <div className="ov-ring-row">
              {rings.map(ring => <div key={ring.key} className="ov-ring-cell">
                <div className="ov-ring" style={{ ['--pct' as string]: `${Math.max(0, Math.min(ring.value, 100)) * 3.6}deg` }}>
                  <span>{ring.value.toFixed(1)}%</span>
                </div>
                <small>{t(`overview.health.${ring.key}`)}</small>
              </div>)}
            </div>
          </section>
        </div>

        <section className="ov-panel ov-shortcuts" aria-label={t('overview.shortcuts.title')}>
          <header className="ov-panel-head"><h2>{t('overview.shortcuts.title')}</h2></header>
          <div className="ov-shortcut-row">
            {DEMO.shortcuts.map(item => <button key={item.key} type="button" className="ov-shortcut">
              <span className={`ov-shortcut-icon tint-${item.tint}`}>{item.icon}</span>
              <span className="ov-shortcut-copy">
                <b>{t(`overview.shortcut.${item.key}.title`)}</b>
                <small>{t(`overview.shortcut.${item.key}.desc`)}</small>
              </span>
              <ArrowRightOutlined className="ov-shortcut-arrow" />
            </button>)}
          </div>
        </section>
      </div>

      <aside className="ov-side">
        <section className="ov-panel ov-todo" aria-label={t('overview.todo.title')}>
          <header className="ov-panel-head">
            <h2>{t('overview.todo.title')}<sup>{DEMO.todos.length}</sup></h2>
            <Button type="link" size="small">{t('overview.todo.all')}</Button>
          </header>
          <ul className="ov-todo-list">
            {DEMO.todos.map(todo => <li key={todo.id} className={`ov-todo-item tone-${todo.tone}`}>
              <span className="ov-todo-dot" />
              <div>
                <b>{todo.title}</b>
                <small>{todo.meta}</small>
              </div>
              <time>{todo.time}</time>
            </li>)}
          </ul>
        </section>

        <section className="ov-assistant" aria-label={t('overview.assistant.title')}>
          <header className="ov-assistant-head">
            <span className="ov-assistant-mark"><ThunderboltOutlined /></span>
            <b>{t('overview.assistant.title')}</b>
            <button type="button" className="ov-assistant-min" aria-label={t('overview.assistant.collapse')}><MinusOutlined /></button>
          </header>
          <div className="ov-assistant-body">
            <p>{t('overview.assistant.greeting')}</p>
            <ul>
              <li>{t('overview.assistant.item1')}</li>
              <li>{t('overview.assistant.item2')}</li>
              <li>{t('overview.assistant.item3')}</li>
              <li>{t('overview.assistant.item4')}</li>
            </ul>
            <button type="button" className="ov-assistant-cta">{t('overview.assistant.cta')}</button>
          </div>
          <form className="ov-assistant-form" onSubmit={event => { event.preventDefault(); setDraft(''); }}>
            <Input variant="borderless" value={draft} onChange={event => setDraft(event.target.value)} placeholder={t('overview.assistant.placeholder')} />
            <Button type="primary" shape="circle" htmlType="submit" icon={<SendOutlined />} aria-label={t('overview.assistant.send')} />
          </form>
        </section>
      </aside>
    </div>
  </div>;
}
