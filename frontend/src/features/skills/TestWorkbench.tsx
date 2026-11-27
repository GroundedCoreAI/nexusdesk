import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Input, InputNumber, Skeleton, Space, Switch, Tag } from 'antd';
import {
  CheckCircleFilled,
  ClockCircleOutlined,
  CodeOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
  WarningOutlined,
  CloseCircleFilled,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { errorText, dateTime } from '../../i18n';
import { runSkillTest, skillErrorCode, skillErrorMessage } from './api';
import {
  buildInputSummary,
  type JsonObject,
  type SkillParameter,
  type SkillRecord,
  type SkillTestRun,
} from './contracts';
import { useSkillTestRuns } from './useSkills';
import './skill-workflows.css';

interface TestWorkbenchProps {
  skill: SkillRecord;
  skillKey: string;
  canTest: boolean;
  dirty: boolean;
  onEdit: () => void;
  onRelease: () => void;
}

type InputMode = 'form' | 'raw';
type DisplayStatus = SkillTestRun['status'] | 'running' | null;

function parameterInitial(parameter: SkillParameter): unknown {
  if (parameter.default !== null && parameter.default !== undefined) return parameter.default;
  if (parameter.type === 'boolean') return false;
  if (parameter.type === 'number' || parameter.type === 'integer') return null;
  if (parameter.type === 'array') return [];
  if (parameter.type === 'object') return {};
  return '';
}

function initialPayload(skill: SkillRecord): JsonObject {
  return Object.fromEntries(skill.definition.parameters.map(parameter => [
    parameter.name,
    parameterInitial(parameter),
  ]));
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'string' && value.trim() === '');
}

function valueMatchesType(value: unknown, type: SkillParameter['type']): boolean {
  if (type === 'string') return typeof value === 'string';
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
  if (type === 'integer') return typeof value === 'number' && Number.isInteger(value);
  if (type === 'boolean') return typeof value === 'boolean';
  if (type === 'array') return Array.isArray(value);
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function statusLabel(status: DisplayStatus): string {
  if (!status) return 'skill.test.empty';
  return `skill.test.status.${status}`;
}

function statusIcon(status: DisplayStatus) {
  if (status === 'passed') return <CheckCircleFilled />;
  if (status === 'failed') return <CloseCircleFilled />;
  if (status === 'blocked') return <StopOutlined />;
  if (status === 'error') return <WarningOutlined />;
  if (status === 'running') return <ClockCircleOutlined />;
  return <PlayCircleOutlined />;
}

function resultOutput(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === undefined || value === null) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function diagnosticsText(value: JsonObject): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return '';
  }
}

function parsePayload(text: string): { payload: JsonObject; error: string } {
  try {
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { payload: {}, error: 'object' };
    }
    return { payload: parsed as JsonObject, error: '' };
  } catch {
    return { payload: {}, error: 'json' };
  }
}

export function TestWorkbench({
  skill,
  skillKey,
  canTest,
  dirty,
  onEdit,
  onRelease,
}: TestWorkbenchProps) {
  const { t } = useTranslation();
  const history = useSkillTestRuns(skillKey);
  const [inputMode, setInputMode] = useState<InputMode>('form');
  const [values, setValues] = useState<JsonObject>(() => initialPayload(skill));
  const [rawText, setRawText] = useState(() => JSON.stringify(initialPayload(skill), null, 2));
  const [scenario, setScenario] = useState('');
  const [inputError, setInputError] = useState('');
  const [requestError, setRequestError] = useState('');
  const [requestErrorCode, setRequestErrorCode] = useState('');
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<SkillTestRun | null>(null);
  const [resultSource, setResultSource] = useState<'live' | 'history'>('live');
  const [selectedRunId, setSelectedRunId] = useState('');

  useEffect(() => {
    const next = initialPayload(skill);
    setValues(next);
    setRawText(JSON.stringify(next, null, 2));
    setInputError('');
    setResult(null);
    setRequestError('');
    setRequestErrorCode('');
    setSelectedRunId('');
  }, [skill.draft_revision, skill.definition]);

  useEffect(() => {
    if (!running) return;
    const started = performance.now();
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Math.floor(performance.now() - started)), 100);
    return () => window.clearInterval(timer);
  }, [running]);

  const blockedError = requestErrorCode === 'skill_test_execution_blocked';
  const displayStatus: DisplayStatus = running
    ? 'running'
    : result?.status ?? (blockedError ? 'blocked' : requestError ? 'error' : null);
  const currentPass = Boolean(
    result
    && result.status === 'passed'
    && result.draft_revision === skill.draft_revision
    && !dirty,
  );
  const stale = Boolean(result && (dirty || result.draft_revision !== skill.draft_revision));
  const historyItems = history.data?.items ?? [];

  const requiredParameters = useMemo(
    () => skill.definition.parameters.filter(parameter => parameter.required),
    [skill.definition.parameters],
  );

  function updateValue(name: string, value: unknown) {
    setValues(current => ({ ...current, [name]: value }));
    setInputError('');
    setRequestError('');
  }

  function validatePayload(payload: JsonObject): string {
    for (const parameter of requiredParameters) {
      if (isEmpty(payload[parameter.name])) {
      return t('skill.test.validation.required {{v0}}', { v0: parameter.name });
      }
    }
    for (const parameter of skill.definition.parameters) {
      const value = payload[parameter.name];
      if (!isEmpty(value) && !valueMatchesType(value, parameter.type)) {
      return t('skill.test.validation.type {{v0}}', { v0: parameter.name });
      }
    }
    const known = new Set(skill.definition.parameters.map(parameter => parameter.name));
    const extra = Object.keys(payload).find(key => !known.has(key));
    if (extra && skill.definition.parameters.length) {
    return t('skill.test.validation.extra {{v0}}', { v0: extra });
    }
    return '';
  }

  function switchMode(next: InputMode) {
    if (next === inputMode) return;
    if (next === 'raw') {
      setRawText(JSON.stringify(values, null, 2));
      setInputMode('raw');
      return;
    }
    const parsed = parsePayload(rawText);
    if (parsed.error) {
      setInputError(t('skill.test.validation.json'));
      return;
    }
    const invalid = validatePayload(parsed.payload);
    if (invalid) {
      setInputError(invalid);
      return;
    }
    setValues(parsed.payload);
    setInputError('');
    setInputMode('form');
  }

  async function run() {
    if (!canTest || running || dirty) return;
    let payload = values;
    if (inputMode === 'raw') {
      const parsed = parsePayload(rawText);
      if (parsed.error) {
        setInputError(t('skill.test.validation.json'));
        return;
      }
      payload = parsed.payload;
      setValues(payload);
    }
    const invalid = validatePayload(payload);
    if (invalid) {
      setInputError(invalid);
      return;
    }
    setInputError('');
    setRequestError('');
    setRequestErrorCode('');
    setRunning(true);
    setResultSource('live');
    try {
      const runResult = await runSkillTest(skillKey, {
        draft_revision: skill.draft_revision,
        input: payload,
        scenario: scenario.trim(),
        client_request_id: crypto.randomUUID(),
      });
      setResult(runResult);
      setSelectedRunId(runResult.id);
      history.refresh();
    } catch (cause) {
      setRequestErrorCode(skillErrorCode(cause));
      const message = errorText(skillErrorMessage(cause));
      setRequestError(message);
    } finally {
      setRunning(false);
    }
  }

  function showHistoryRun(run: SkillTestRun) {
    setResult(run);
    setResultSource('history');
    setSelectedRunId(run.id);
    setRequestError('');
    setRequestErrorCode('');
    setInputMode('form');
    setValues(run.input);
    setRawText(JSON.stringify(run.input, null, 2));
  }

  function renderControl(parameter: SkillParameter) {
    const value = values[parameter.name];
    const id = `skill-test-input-${parameter.name}`;
    if (parameter.type === 'boolean') {
      return (
        <Switch
          id={id}
          checked={Boolean(value)}
          onChange={checked => updateValue(parameter.name, checked)}
          checkedChildren={t('skill.common.true')}
          unCheckedChildren={t('skill.common.false')}
        />
      );
    }
    if (parameter.type === 'number' || parameter.type === 'integer') {
      return (
        <InputNumber
          id={id}
          value={typeof value === 'number' ? value : null}
          precision={parameter.type === 'integer' ? 0 : undefined}
          onChange={next => updateValue(parameter.name, next)}
          style={{ width: '100%' }}
        />
      );
    }
    if (parameter.type === 'object' || parameter.type === 'array') {
      return (
        <Input.TextArea
          id={id}
          rows={4}
          value={value === null || value === undefined ? '' : typeof value === 'string' ? value : resultOutput(value)}
          onChange={event => {
            try {
              const parsed: unknown = JSON.parse(event.target.value);
              updateValue(parameter.name, parsed);
            } catch {
              updateValue(parameter.name, event.target.value);
            }
          }}
        />
      );
    }
    return (
      <Input
        id={id}
        value={typeof value === 'string' ? value : ''}
        onChange={event => updateValue(parameter.name, event.target.value)}
      />
    );
  }

  return (
    <section className="skill-test-workbench" aria-labelledby="skill-test-title">
      <div className="skill-test-heading">
        <div>
          <h1 id="skill-test-title">{t('skill.test.title')}</h1>
          <p>{t('skill.test.subtitle')}</p>
        </div>
        <div className="skill-test-heading-actions">
          <Tag>{t('skill.test.savedRevision {{v0}}', { v0: skill.draft_revision })}</Tag>
          {dirty && <Tag color="gold">{t('skill.test.dirty')}</Tag>}
          <Button icon={<CodeOutlined />} onClick={onEdit}>{t('skill.test.editDraft')}</Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={running}
            disabled={!canTest || dirty || running}
            onClick={() => void run()}
            title={dirty ? t('skill.test.saveFirst') : !canTest ? t('skill.permission.testDenied') : undefined}
          >
            {running ? t('skill.test.running {{v0}}', { v0: (elapsed / 1000).toFixed(1) }) : t('skill.test.run')}
          </Button>
        </div>
      </div>
      {!canTest && <Alert type="info" showIcon title={t('skill.permission.testDenied')} />}
      {requestError && <Alert className="skill-test-alert" type={blockedError ? 'warning' : 'error'} showIcon title={t('skill.test.requestFailed')} description={requestError} action={<Button size="small" onClick={() => void run()}>{t('common.retry')}</Button>} />}
      <div className="skill-test-panes">
        <section className="skill-test-input" aria-labelledby="skill-test-input-title">
          <div className="skill-test-pane-heading">
            <div>
              <h2 id="skill-test-input-title">{t('skill.test.inputTitle')}</h2>
              <p>{t('skill.test.inputSubtitle')}</p>
            </div>
            <div className="skill-test-mode" role="tablist" aria-label={t('skill.test.inputMode')}>
              <button type="button" role="tab" aria-selected={inputMode === 'form'} className={inputMode === 'form' ? 'is-active' : ''} onClick={() => switchMode('form')}>{t('skill.test.formMode')}</button>
              <button type="button" role="tab" aria-selected={inputMode === 'raw'} className={inputMode === 'raw' ? 'is-active' : ''} onClick={() => switchMode('raw')}>{t('skill.test.rawMode')}</button>
            </div>
          </div>
          {inputError && <Alert type="error" showIcon title={inputError} />}
          {inputMode === 'form' ? (
            <div className="skill-test-fields">
              {skill.definition.parameters.length ? skill.definition.parameters.map(parameter => (
                <label className="skill-test-field" key={parameter.name} htmlFor={`skill-test-input-${parameter.name}`}>
                  <span>{parameter.name}{parameter.required && <i aria-hidden="true">*</i>}<small>{parameter.type}</small></span>
                  {renderControl(parameter)}
                </label>
              )) : (
                <div className="skill-test-empty-params">
                  <CodeOutlined />
                  <p>{t('skill.test.noParameters')}</p>
                </div>
              )}
            </div>
          ) : (
            <Input.TextArea
              id="skill-test-raw"
              aria-label={t('skill.test.rawLabel')}
              className="skill-test-raw"
              rows={14}
              value={rawText}
              onChange={event => { setRawText(event.target.value); setInputError(''); }}
              spellCheck={false}
            />
          )}
          <label className="skill-test-scenario" htmlFor="skill-test-scenario">
            <span>{t('skill.test.scenario')}</span>
            <Input.TextArea
              id="skill-test-scenario"
              rows={2}
              maxLength={500}
              value={scenario}
              onChange={event => setScenario(event.target.value)}
              placeholder={t('skill.test.scenarioPlaceholder')}
            />
          </label>
          {dirty && <p className="skill-test-hint" role="status">{t('skill.test.dirtyHint')}</p>}
        </section>
        <section className={`skill-test-result ${displayStatus ? `is-${displayStatus}` : ''}`} aria-labelledby="skill-test-result-title" aria-live="polite">
          <div className="skill-test-pane-heading">
            <div>
              <h2 id="skill-test-result-title">{t('skill.test.resultTitle')}</h2>
              <p>{t('skill.test.resultSubtitle')}</p>
            </div>
            {displayStatus && <span className={`skill-test-status skill-test-status-${displayStatus}`}>{statusIcon(displayStatus)}{t(statusLabel(displayStatus))}</span>}
          </div>
          {stale && <Alert type="warning" showIcon title={t('skill.test.staleTitle')} description={t('skill.test.staleBody {{v0}} {{v1}}', { v0: result?.draft_revision ?? 0, v1: skill.draft_revision })} />}
          {running ? (
            <div className="skill-test-running" role="status">
              <span className="skill-test-spinner" />
              <strong>{t('skill.test.running {{v0}}', { v0: (elapsed / 1000).toFixed(1) })}</strong>
              <p>{t('skill.test.runningBody')}</p>
            </div>
          ) : result || requestError ? (
            <div className="skill-test-result-body">
              {result && (
                <>
                  <dl className="skill-test-result-meta">
                    <div><dt>{t('skill.test.revision')}</dt><dd>r{result.draft_revision}</dd></div>
                    <div><dt>{t('skill.test.duration')}</dt><dd>{result.duration_ms} ms</dd></div>
                    <div><dt>{t('skill.test.executionKind')}</dt><dd>{t(`skill.test.kind.${result.execution_kind}`)}</dd></div>
                    <div><dt>{t('skill.test.executedBy')}</dt><dd>{result.executed_by || '—'}</dd></div>
                  </dl>
                  {result.output !== null && result.output !== undefined && (
                    <div className="skill-test-output">
                      <h3>{t('skill.test.output')}</h3>
                      <pre>{resultOutput(result.output)}</pre>
                    </div>
                  )}
                  {result.reason_code && <p className="skill-test-reason"><strong>{t('skill.test.reason')}</strong>{result.reason_code}</p>}
                  {Object.keys(result.diagnostics).length > 0 && (
                    <details className="skill-test-diagnostics">
                      <summary>{t('skill.test.diagnostics')}</summary>
                      <pre>{diagnosticsText(result.diagnostics)}</pre>
                    </details>
                  )}
                </>
              )}
              {!result && requestError && <div className="skill-test-error-copy">{requestError}</div>}
              {currentPass && <Button type="primary" onClick={onRelease}>{t('skill.test.continueRelease')}</Button>}
            </div>
          ) : (
            <div className="skill-test-empty">
              <ThunderboltIcon />
              <strong>{t('skill.test.emptyTitle')}</strong>
              <p>{t('skill.test.emptyBody')}</p>
            </div>
          )}
        </section>
      </div>
      <section className="skill-test-history" aria-labelledby="skill-test-history-title">
        <div className="skill-test-pane-heading">
          <div>
            <h2 id="skill-test-history-title">{t('skill.test.historyTitle')}</h2>
            <p>{t('skill.test.historySubtitle')}</p>
          </div>
          {history.loading && <span role="status">{t('common.loading')}</span>}
          {history.error && <Button size="small" icon={<ReloadOutlined />} onClick={history.refresh}>{t('common.retry')}</Button>}
        </div>
        {history.error && <Alert type="error" showIcon title={t('skill.test.historyError')} description={errorText(history.error)} />}
        {history.loading && !historyItems.length ? <Skeleton active paragraph={{ rows: 3 }} title={false} /> : historyItems.length ? (
          <div className="skill-test-history-table-wrap">
            <table className="skill-test-history-table">
              <thead>
                <tr>
                  <th>{t('skill.test.history.time')}</th>
                  <th>{t('skill.test.history.revision')}</th>
                  <th>{t('skill.test.history.input')}</th>
                  <th>{t('skill.test.history.status')}</th>
                  <th>{t('skill.test.history.duration')}</th>
                  <th>{t('skill.test.history.executor')}</th>
                  <th>{t('skill.test.history.detail')}</th>
                </tr>
              </thead>
              <tbody>
                {historyItems.map(run => (
                  <tr key={run.id} className={run.id === selectedRunId ? 'is-active' : ''}>
                    <td>{run.created_at ? dateTime(run.created_at) : '—'}</td>
                    <td>r{run.draft_revision}</td>
                    <td><span className="skill-test-input-summary">{run.input_summary || buildInputSummary(run.input)}</span></td>
                    <td><Tag color={run.status === 'passed' ? 'green' : run.status === 'blocked' ? 'gold' : 'red'}>{t(statusLabel(run.status))}</Tag></td>
                    <td>{run.duration_ms} ms</td>
                    <td>{run.executed_by || '—'}</td>
                    <td><Button type="link" onClick={() => showHistoryRun(run)}>{t('skill.test.history.view')}</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !history.error ? (
          <div className="skill-test-history-empty"><ThunderboltIcon /><span>{t('skill.test.history.empty')}</span></div>
        ) : null}
      </section>
      {resultSource === 'history' && <span className="sr-only" aria-live="polite">{t('skill.test.history.activeAnnouncement')}</span>}
    </section>
  );
}

function ThunderboltIcon() {
  return <span className="skill-test-empty-icon" aria-hidden="true">⌁</span>;
}
