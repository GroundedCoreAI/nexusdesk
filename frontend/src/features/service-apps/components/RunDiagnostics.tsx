import type { ReactNode } from 'react';
import { Alert, Empty, Tag, Timeline } from 'antd';
import { dateTime } from '../../../i18n/index';
import { KnowledgeRecall, type RunKnowledgeRetrieval } from '../../../shared/components/ui';
import { say } from '../labels';
import './run-diagnostics.css';

/** Fixed stages the runtime stamps before the first model round. */
export interface RunTiming {
    queued_ms?: number | null;
    prepare_ms?: number | null;
    exec_ms?: number | null;
    total_ms?: number | null;
}

/** One model round, as recorded by model.started/model.completed. */
export interface RunModelRound {
    round?: number | null;
    offset_ms?: number | null;
    duration_ms?: number | null;
    first_token_ms?: number | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    tool_calls?: number | null;
    model?: string | null;
    upstream_ms?: number | null;
}

export interface RunSkill {
    key: string;
    status: string;
    duration_ms?: number | null;
    error?: string | null;
}

/** Trace payload shared by the live preview and the rebuilt run history. */
export interface RunTrace {
    retrieval?: RunKnowledgeRetrieval[];
    timing?: RunTiming;
    rounds?: RunModelRound[];
    tool_calls?: Array<{ name?: string; offset_ms?: number | null }>;
    [key: string]: unknown;
}

export interface RunDiagnosticMeta {
    label: string;
    value: ReactNode;
}

const UNAVAILABLE_REASONS: Record<string, string> = {
    not_dispatched: '这一轮没有派发到运行时，因此没有可回放的事件。',
    run_events_missing: '运行时事件已被清理，且没有留下快照。',
};

function millis(value?: number | null): string {
    return typeof value === 'number' ? `${value}ms` : '—';
}

function statusLabel(status: string): string {
    if (status === 'completed') return say('已完成');
    if (status === 'failed') return say('失败');
    if (status === 'running' || status === 'queued') return say('运行中');
    if (status === 'cancelled') return say('已取消');
    return status || say('未知');
}

function statusColor(status: string): string {
    if (status === 'completed') return 'green';
    if (status === 'failed') return 'red';
    if (status === 'running' || status === 'queued') return 'processing';
    return 'default';
}

interface TimelineStep {
    /** Milliseconds from run start; steps are drawn in this order. */
    offset: number;
    color: string;
    node: ReactNode;
}

function buildSteps({
    status,
    createdAt,
    input,
    reply,
    error,
    skills,
    trace,
}: {
    status: string;
    createdAt?: string | null;
    input: string;
    reply: string;
    error?: string | null;
    skills: RunSkill[];
    trace: RunTrace;
}): TimelineStep[] {
    const timing = trace.timing;
    const rounds = trace.rounds || [];
    const retrievals = trace.retrieval || [];
    const steps: TimelineStep[] = [];

    // Every step knows when it began relative to the run, so the timeline is
    // ordered by real time instead of by category: the second model round only
    // makes sense after the search that fed it.
    const pendingOffsets = new Map<string, number[]>();
    for (const call of trace.tool_calls || []) {
        const name = String(call.name || '');
        if (!name || typeof call.offset_ms !== 'number') continue;
        const queue = pendingOffsets.get(name) || [];
        queue.push(call.offset_ms);
        pendingOffsets.set(name, queue);
    }
    const cancelOffset = (name: string) => {
        const queue = pendingOffsets.get(name);
        return queue?.length ? queue.shift() as number : null;
    };

    const queueMs = timing?.queued_ms;
    const prepareMs = timing?.prepare_ms;
    steps.push({
        offset: 0,
        color: 'blue',
        node: <div className="sa-run-diag-step">
            <div className="sa-run-diag-step-head">
                <strong>{say('收到客户消息')}</strong>
                {createdAt && <span className="sa-run-diag-step-meta">{dateTime(createdAt)}</span>}
            </div>
            <p>{input}</p>
            {(queueMs != null || prepareMs != null) && <small>
                {[
                    queueMs != null ? say('排队 {{v0}}ms', { v0: queueMs }) : null,
                    prepareMs != null ? say('上下文准备 {{v0}}ms', { v0: prepareMs }) : null,
                ].filter(Boolean).join(' · ')}
            </small>}
        </div>,
    });

    rounds.forEach((round, index) => {
        const number = round.round ?? index + 1;
        const body = [
            round.first_token_ms != null
                ? say('首字 {{v0}}', { v0: `${round.first_token_ms}ms` })
                : null,
            round.input_tokens != null || round.output_tokens != null
                ? say('输入 {{v0}} tok · 输出 {{v1}} tok', {
                    v0: round.input_tokens ?? 0,
                    v1: round.output_tokens ?? 0,
                })
                : null,
            round.tool_calls
                ? say('调用 {{v0}} 个工具', { v0: round.tool_calls })
                : null,
        ].filter(Boolean).join(' · ');
        steps.push({
            offset: round.offset_ms ?? 0,
            color: 'blue',
            node: <div className="sa-run-diag-step">
                <div className="sa-run-diag-step-head">
                    <strong>
                        {say('模型第 {{v0}} 轮', { v0: number })}
                        {round.model
                            ? <> <span className="sa-run-diag-step-model">{round.model}</span></>
                            : null}
                    </strong>
                    <span className="sa-run-diag-step-duration">{millis(round.duration_ms)}</span>
                </div>
                {body && <p>{body}</p>}
            </div>,
        });
    });

    retrievals.forEach(item => {
        const embedding = item.embedding_ms;
        const search = item.search_ms;
        steps.push({
            offset: item.offset_ms ?? 0,
            color: 'green',
            node: <div className="sa-run-diag-step">
                <div className="sa-run-diag-step-head">
                    <strong>{say('知识检索')}</strong>
                    <span className="sa-run-diag-step-duration">{millis(item.duration_ms)}</span>
                </div>
                <p>
                    {item.query}
                    {' · '}
                    {say('{{v0}} 条', { v0: item.sources?.length || 0 })}
                </p>
                {(embedding != null || search != null) && <div className="sa-run-diag-step-split">
                    {embedding != null && <span>{say('嵌入 {{v0}}ms', { v0: embedding })}</span>}
                    {search != null && <span>{say('检索融合 {{v0}}ms', { v0: search })}</span>}
                </div>}
            </div>,
        });
    });

    skills.forEach((skill, index) => {
        // A skill without a matching tool call has no timestamp; it still
        // belongs before the reply, so it sorts last among the timed steps.
        const offset = cancelOffset(skill.key);
        steps.push({
            offset: offset ?? Number.MAX_SAFE_INTEGER,
            color: skill.status === 'completed' ? 'green' : 'orange',
            node: <div className="sa-run-diag-step" key={`skill-${skill.key}-${index}`}>
                <div className="sa-run-diag-step-head">
                    <strong>{skill.key}</strong>
                    <span className="sa-run-diag-step-duration">{millis(skill.duration_ms)}</span>
                </div>
                <p>{skill.status}</p>
            </div>,
        });
    });

    steps.push({
        offset: Number.MAX_SAFE_INTEGER,
        color: status === 'failed' ? 'red' : 'green',
        node: <div className="sa-run-diag-step">
            <div className="sa-run-diag-step-head">
                <strong>{status === 'failed' ? say('失败') : say('应用返回回复')}</strong>
                <span className="sa-run-diag-step-duration">{millis(timing?.total_ms)}</span>
            </div>
            <p>{reply || error || say('暂无回复')}</p>
        </div>,
    });

    // Stable sort keeps the reply last when several steps share a sentinel offset.
    return steps.sort((left, right) => left.offset - right.offset);
}

/**
 * One run's diagnostic body: dialogue, timed timeline, skills, knowledge recall
 * and the raw trace.
 *
 * Shared by the debug preview drawer and the customer-conversation records, so
 * an operator reads the same evidence whether the turn came from a manual test
 * or from a real visitor.
 */
export function RunDiagnostics({
    status,
    runId,
    input,
    reply,
    error,
    skills,
    trace,
    meta,
    createdAt,
    unavailableReason,
}: {
    status: string;
    runId?: string | null;
    input: string;
    reply: string;
    error?: string | null;
    skills: RunSkill[];
    trace: RunTrace;
    meta?: RunDiagnosticMeta[];
    createdAt?: string | null;
    /** Set when the backend could not rebuild the trace; only dialogue shows. */
    unavailableReason?: string | null;
}) {
    const retrievals = trace.retrieval || [];
    const recalledSources = retrievals.reduce(
        (total, item) => total + (item.sources?.length || 0),
        0,
    );
    const timing = trace.timing;
    const steps = unavailableReason
        ? []
        : buildSteps({ status, createdAt, input, reply, error, skills, trace });
    const timelineItems = steps.map((step, index) => ({
        color: step.color,
        children: <div key={`timeline-step-${index}`}>{step.node}</div>,
    }));

    return <div className="sa-run-diag">
        <div className="sa-run-diag-head">
            <div>
                <span>{say('运行诊断')}</span>
                <strong className="mono">{runId ? `#${runId}` : say('本轮没有运行记录')}</strong>
            </div>
            <Tag color={statusColor(status)}>{statusLabel(status)}</Tag>
        </div>

        {error && <Alert type="error" showIcon message={error}/>}

        {meta && meta.length > 0 && <div className="sa-run-diag-meta">
            {meta.map(item => <div key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
            </div>)}
        </div>}

        {unavailableReason && <Alert
            type="info"
            showIcon
            message={say('这一轮没有可回放的运行事件')}
            description={say(UNAVAILABLE_REASONS[unavailableReason]
                || '运行时事件不可用，只能看到对话内容。')}
        />}

        <section className="sa-run-diag-section">
            <h4>{say('对话记录')}</h4>
            <div className="sa-run-diag-dialogue">
                <div>
                    <span>{say('客户消息')}</span>
                    <p>{input || say('暂无内容')}</p>
                </div>
                <div>
                    <span>{say('应用回复')}</span>
                    <p>{reply || error || say('暂无回复')}</p>
                </div>
            </div>
        </section>

        {!unavailableReason && <section className="sa-run-diag-section">
            <div className="sa-run-diag-section-title">
                <h4>{say('运行时间线')}</h4>
                {timing?.total_ms != null
                    ? <Tag>{say('总耗时 {{v0}}ms', { v0: timing.total_ms })}</Tag>
                    : <span>{say('暂无耗时数据')}</span>}
            </div>
            {timelineItems.length
                ? <Timeline items={timelineItems}/>
                : <Empty description={say('暂无事件')}/>}
        </section>}

        {!unavailableReason && <section className="sa-run-diag-section">
            <div className="sa-run-diag-section-title">
                <h4>{say('技能与 Trace')}</h4>
                {(skills.length || retrievals.length)
                    ? <Tag>{skills.length + retrievals.length}</Tag>
                    : <span>{say('暂无技能调用')}</span>}
            </div>
            <div className="sa-run-diag-chips">
                {retrievals.map((item, index) => <Tag
                    key={`knowledge-${index}`}
                    color="green"
                >
                    {say('知识检索')} · {say('{{v0}} 条', { v0: item.sources?.length || 0 })}
                </Tag>)}
                {skills.map(skill => <Tag
                    key={skill.key}
                    color={skill.status === 'completed' ? 'green' : 'orange'}
                >
                    {skill.key} · {skill.status}
                </Tag>)}
            </div>
        </section>}

        {!unavailableReason && <section className="sa-run-diag-section">
            <div className="sa-run-diag-section-title">
                <h4>{say('知识召回')}</h4>
                {recalledSources
                    ? <Tag>{recalledSources}</Tag>
                    : <span>{say('本轮没有调用知识检索')}</span>}
            </div>
            <KnowledgeRecall items={retrievals}/>
        </section>}

        {!unavailableReason && <section className="sa-run-diag-section">
            <h4>{say('原始 JSON')}</h4>
            <pre className="sa-run-diag-raw">{JSON.stringify({ skills, trace }, null, 2)}</pre>
        </section>}
    </div>;
}
