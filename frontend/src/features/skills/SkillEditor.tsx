import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { App as AntApp, Alert, Button, Input, InputNumber, Modal, Select, Skeleton, Switch, Tag } from 'antd';
import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  ArrowUpOutlined,
  CheckCircleFilled,
  CodeOutlined,
  DeleteOutlined,
  PlusOutlined,
  RocketOutlined,
  SaveOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { dateTime, errorText } from '../../i18n';
import { SkillBreadcrumb } from './SkillBreadcrumb';
import { ReleasePanel } from './ReleasePanel';
import { SkillPackageCard } from './SkillPackageCard';
import { TestWorkbench } from './TestWorkbench';
import {
  SKILL_CATEGORIES,
  SKILL_ERROR_BEHAVIORS,
  SKILL_IDEMPOTENCY,
  SKILL_OUTPUT_FORMATS,
  SKILL_PARAMETER_TYPES,
  SKILL_RETRY_POLICIES,
  SKILL_TRIGGERS,
  SKILL_TYPES,
  type SkillCategory,
  type SkillCreationMode,
  type SkillDefinition,
  type SkillErrorBehavior,
  type SkillIdempotency,
  type SkillOutputFormat,
  type SkillParameter,
  type SkillParameterType,
  type SkillRecord,
  type SkillRetryPolicy,
  type SkillTrigger,
  type SkillType,
} from './contracts';
import {
  duplicateSkill,
  isSkillRevisionConflict,
  saveSkillDraft,
  skillErrorMessage,
} from './api';
import {
  useSkillDependencyOptions,
  useSkillDetail,
  useSkillPermissions,
} from './useSkills';
import './skill-workflows.css';

export type EditorSection = 'basic' | 'capability' | 'parameters' | 'dependencies' | 'runtime';
type EditorStage = 'edit' | 'test' | 'release';

interface EditorParameter extends Omit<SkillParameter, 'default'> {
  defaultText: string;
}

interface EditorValues {
  creationMode: SkillCreationMode;
  name: string;
  description: string;
  category: SkillCategory;
  tags: string[];
  type: SkillType;
  trigger: SkillTrigger;
  instructions: string;
  outputFormat: SkillOutputFormat;
  outputSchemaText: string;
  parameters: EditorParameter[];
  modelProfileId: string;
  modelProfileVersion: number;
  knowledgeBaseIds: string[];
  toolNames: string[];
  handoffQueue: string;
  timeoutSeconds: number;
  retryPolicy: SkillRetryPolicy;
  confirmationRequired: boolean;
  idempotency: SkillIdempotency;
  errorBehavior: SkillErrorBehavior;
  maxAmount: number | null;
}

interface ValidationIssue {
  field: string;
  section: EditorSection;
  message: string;
}

interface SkillEditorProps {
  skillKey: string;
  onNavigate: (path: string) => void;
  onGuardChange?: (guard: ((destination?: string) => boolean) | null) => void;
  initialSection?: EditorSection;
  initialStage?: EditorStage;
}

const sectionIds: EditorSection[] = ['basic', 'capability', 'parameters', 'dependencies', 'runtime'];

function defaultText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function editorValues(skill: SkillRecord): EditorValues {
  const definition = skill.definition;
  return {
    creationMode: definition.creation_mode,
    name: skill.name,
    description: skill.description,
    category: skill.category,
    tags: skill.tags,
    type: definition.type,
    trigger: definition.trigger,
    instructions: definition.instructions,
    outputFormat: definition.output.format,
    outputSchemaText: definition.output.schema ? JSON.stringify(definition.output.schema, null, 2) : '',
    parameters: definition.parameters.map(parameter => ({ ...parameter, defaultText: defaultText(parameter.default) })),
    modelProfileId: definition.dependencies.model_profile_id ?? '',
    modelProfileVersion: definition.dependencies.model_profile_version ?? 1,
    knowledgeBaseIds: definition.dependencies.knowledge_base_ids,
    toolNames: definition.dependencies.tool_names,
    handoffQueue: definition.dependencies.handoff_queue ?? '',
    timeoutSeconds: definition.runtime.timeout_seconds,
    retryPolicy: definition.runtime.retry_policy,
    confirmationRequired: definition.runtime.confirmation_required,
    idempotency: definition.runtime.idempotency,
    errorBehavior: definition.runtime.error_behavior,
    maxAmount: definition.runtime.max_amount,
  };
}

function parseDefault(parameter: EditorParameter): { value: unknown; error: string | null } {
  const text = parameter.defaultText.trim();
  if (!text) return { value: null, error: null };
  if (parameter.type === 'string') return { value: parameter.defaultText, error: null };
  if (parameter.type === 'number' || parameter.type === 'integer') {
    const value = Number(text);
    if (!Number.isFinite(value)) return { value: null, error: 'number' };
    if (parameter.type === 'integer' && !Number.isInteger(value)) return { value: null, error: 'integer' };
    return { value, error: null };
  }
  if (parameter.type === 'boolean') {
    if (text !== 'true' && text !== 'false') return { value: null, error: 'boolean' };
    return { value: text === 'true', error: null };
  }
  try {
    const value: unknown = JSON.parse(text);
    if (parameter.type === 'array' && !Array.isArray(value)) return { value: null, error: 'array' };
    if (parameter.type === 'object' && (typeof value !== 'object' || value === null || Array.isArray(value))) {
      return { value: null, error: 'object' };
    }
    return { value, error: null };
  } catch {
    return { value: null, error: parameter.type };
  }
}

function buildDefinition(values: EditorValues): SkillDefinition {
  return {
    schema_version: 'v1',
    creation_mode: values.creationMode,
    type: values.type,
    trigger: values.trigger,
    instructions: values.instructions.trim(),
    parameters: values.parameters.map(parameter => ({
      name: parameter.name.trim(),
      type: parameter.type,
      required: parameter.required,
      default: parseDefault(parameter).value,
      description: parameter.description.trim(),
    })),
    output: {
      format: values.outputFormat,
      schema: values.outputFormat === 'json' ? JSON.parse(values.outputSchemaText || '{}') as Record<string, unknown> : null,
    },
    dependencies: {
      model_profile_id: values.modelProfileId || null,
      model_profile_version: values.modelProfileId ? values.modelProfileVersion : null,
      knowledge_base_ids: values.knowledgeBaseIds,
      tool_names: values.toolNames,
      handoff_queue: values.handoffQueue.trim() || null,
    },
    runtime: {
      timeout_seconds: values.timeoutSeconds,
      retry_policy: values.retryPolicy,
      confirmation_required: values.confirmationRequired,
      idempotency: values.idempotency,
      error_behavior: values.errorBehavior,
      max_amount: values.maxAmount,
    },
    permission_scope: 'workspace',
  };
}

function Field({
  id,
  label,
  required = false,
  error,
  help,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className={`skill-field ${error ? 'has-error' : ''}`}>
      <label htmlFor={id}>
        {label}
        {required && <span className="skill-required" aria-hidden="true">*</span>}
      </label>
      {children}
      {error && <p id={`${id}-error`} className="skill-field-error" role="alert">{error}</p>}
      {!error && help && <p className="skill-field-help">{help}</p>}
    </div>
  );
}

function categoryLabel(category: SkillCategory): string {
  return `skill.category.${category}`;
}

function typeLabel(type: SkillType): string {
  return `skill.type.${type}`;
}

function modeLabel(mode: SkillCreationMode): string {
  return `skill.mode.${mode}`;
}

function executionMode(values: Pick<EditorValues, 'type' | 'toolNames' | 'knowledgeBaseIds' | 'modelProfileId'>): string {
  if (values.type === 'instruction') return 'skill.execution.model';
  if (values.type === 'knowledge') return values.knowledgeBaseIds.length ? 'skill.execution.retrieval' : 'skill.execution.retrievalMissing';
  if (values.type === 'query') return values.toolNames.length ? 'skill.execution.readTool' : 'skill.execution.readToolMissing';
  if (values.type === 'action') return values.toolNames.length ? 'skill.execution.controlledAction' : 'skill.execution.actionMissing';
  return 'skill.execution.handoff';
}

function sectionLabel(section: EditorSection): string {
  return `skill.section.${section}`;
}

function statusLabel(status: SkillRecord['status']): string {
  return `skill.status.${status}`;
}

export function SkillEditor({
  skillKey,
  onNavigate,
  onGuardChange,
  initialSection = 'basic',
  initialStage = 'edit',
}: SkillEditorProps) {
  const { t } = useTranslation();
  const { message, modal } = AntApp.useApp();
  const detail = useSkillDetail(skillKey);
  const permissions = useSkillPermissions();
  const dependencies = useSkillDependencyOptions(Boolean(detail.data));
  const [activeSection, setActiveSection] = useState<EditorSection>(initialSection);
  const [stage, setStage] = useState<EditorStage>(initialStage);
  const [values, setValues] = useState<EditorValues | null>(null);
  const [savedValues, setSavedValues] = useState<EditorValues | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [conflictOpen, setConflictOpen] = useState(false);
  const [currentRecord, setCurrentRecord] = useState<SkillRecord | null>(null);
  const loadedRevision = useRef('');
  const dirtyRef = useRef(false);
  const pendingDestination = useRef<string | null>(null);
  const allowNavigation = useRef(false);
  const sectionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const canManage = permissions.data?.manage ?? false;
  const canTest = permissions.data?.test ?? false;
  const canPublish = permissions.data?.publish ?? false;
  const dirty = useMemo(
    () => values !== null && savedValues !== null && JSON.stringify(values) !== JSON.stringify(savedValues),
    [savedValues, values],
  );
  dirtyRef.current = dirty;

  useEffect(() => {
    if (!detail.data || detail.loading) return;
    const signature = `${detail.data.key}:${detail.data.draft_revision}:${detail.data.updated_at}`;
    if (loadedRevision.current === signature) return;
    const next = editorValues(detail.data);
    setCurrentRecord(detail.data);
    setValues(next);
    setSavedValues(next);
    setSaveError('');
    setIssues([]);
    loadedRevision.current = signature;
  }, [detail.data, detail.loading]);

  const leaveTo = useCallback((destination: string) => {
    allowNavigation.current = true;
    dirtyRef.current = false;
    onGuardChange?.(null);
    onNavigate(destination);
  }, [onGuardChange, onNavigate]);

  const requestDiscard = useCallback((destination: string) => {
    modal.confirm({
      title: t('skill.editor.discardTitle'),
      content: t('skill.editor.discardBody'),
      okText: t('skill.editor.discardConfirm'),
      cancelText: t('skill.editor.keepEditing'),
      okButtonProps: { danger: true },
      onOk: () => leaveTo(destination),
    });
  }, [leaveTo, modal, t]);

  const guard = useCallback((destination?: string) => {
    if (!destination || allowNavigation.current || !dirtyRef.current) return true;
    pendingDestination.current = destination;
    requestDiscard(destination);
    return false;
  }, [requestDiscard]);

  useEffect(() => {
    onGuardChange?.(guard);
    return () => onGuardChange?.(null);
  }, [guard, onGuardChange]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, []);

  function patch<K extends keyof EditorValues>(key: K, value: EditorValues[K]) {
    setValues(current => current ? { ...current, [key]: value } : current);
    setSaveError('');
    setIssues([]);
  }

  function validate(): ValidationIssue[] {
    if (!values) return [];
    const next: ValidationIssue[] = [];
    if (!values.name.trim()) {
      next.push({ field: 'skill-name', section: 'basic', message: t('skill.validation.nameRequired') });
    }
    if (values.name.trim().length > 100) {
      next.push({ field: 'skill-name', section: 'basic', message: t('skill.validation.nameLength') });
    }
    if (values.description.length > 1000) {
      next.push({ field: 'skill-description', section: 'basic', message: t('skill.validation.descriptionLength') });
    }
    if (values.tags.length > 10) {
      next.push({ field: 'skill-tags', section: 'basic', message: t('skill.validation.tagsCount') });
    }
    if (values.tags.some(tag => tag.length > 32)) {
      next.push({ field: 'skill-tags', section: 'basic', message: t('skill.validation.tagLength') });
    }
    if (values.instructions.length > 12000) {
      next.push({ field: 'skill-instructions', section: 'capability', message: t('skill.validation.instructionsLength') });
    }
    if (values.outputFormat === 'json') {
      try {
        const schema: unknown = JSON.parse(values.outputSchemaText || '{}');
        if (typeof schema !== 'object' || schema === null || Array.isArray(schema)) {
          next.push({ field: 'skill-output-schema', section: 'capability', message: t('skill.validation.invalidSchema') });
        }
      } catch {
        next.push({ field: 'skill-output-schema', section: 'capability', message: t('skill.validation.invalidJson') });
      }
    }
    const names = new Set<string>();
    values.parameters.forEach((parameter, index) => {
      const name = parameter.name.trim();
      if (!/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(name)) {
        next.push({ field: `skill-param-name-${index}`, section: 'parameters', message: t('skill.validation.parameterName') });
      } else if (names.has(name)) {
        next.push({ field: `skill-param-name-${index}`, section: 'parameters', message: t('skill.validation.parameterDuplicate') });
      }
      names.add(name);
      if (parameter.description.length > 200) {
        next.push({ field: `skill-param-description-${index}`, section: 'parameters', message: t('skill.validation.parameterDescription') });
      }
      const parsed = parseDefault(parameter);
      if (parsed.error) {
        next.push({ field: `skill-param-default-${index}`, section: 'parameters', message: t('skill.validation.parameterDefault') });
      }
    });
    if (values.type === 'instruction') {
      if (!values.instructions.trim()) {
        next.push({ field: 'skill-instructions', section: 'capability', message: t('skill.validation.instructionsRequired') });
      }
      if (!values.modelProfileId) {
        next.push({ field: 'skill-model-profile', section: 'dependencies', message: t('skill.validation.modelRequired') });
      }
    }
    if (values.type === 'knowledge' && !values.knowledgeBaseIds.length) {
      next.push({ field: 'skill-knowledge-bases', section: 'dependencies', message: t('skill.validation.knowledgeRequired') });
    }
    if (values.type === 'query') {
      const selected = dependencies.data?.tools.find(tool => values.toolNames.includes(tool.id));
      if (!selected || selected.effect !== 'read') {
        next.push({ field: 'skill-tools', section: 'dependencies', message: t('skill.validation.readToolRequired') });
      }
    }
    if (values.type === 'action') {
      const selected = dependencies.data?.tools.find(tool => values.toolNames.includes(tool.id));
      if (!selected || selected.effect !== 'write') {
        next.push({ field: 'skill-tools', section: 'dependencies', message: t('skill.validation.writeToolRequired') });
      }
      if (!values.confirmationRequired) {
        next.push({ field: 'skill-confirmation', section: 'runtime', message: t('skill.validation.confirmationRequired') });
      }
    }
    if (values.type === 'handoff' && !values.handoffQueue.trim()) {
      next.push({ field: 'skill-handoff-queue', section: 'dependencies', message: t('skill.validation.queueRequired') });
    }
    if (values.timeoutSeconds < 1 || values.timeoutSeconds > 60) {
      next.push({ field: 'skill-timeout', section: 'runtime', message: t('skill.validation.timeout') });
    }
    if (values.errorBehavior === 'handoff' && !values.handoffQueue.trim()) {
      next.push({ field: 'skill-handoff-queue', section: 'dependencies', message: t('skill.validation.queueRequired') });
    }
    if (values.maxAmount !== null && values.maxAmount < 0) {
      next.push({ field: 'skill-max-amount', section: 'runtime', message: t('skill.validation.maxAmount') });
    }
    return next;
  }

  async function save() {
    if (!values || !currentRecord || saving || !canManage) return;
    const found = validate();
    if (found.length) {
      setIssues(found);
      setActiveSection(found[0].section);
      window.requestAnimationFrame(() => document.getElementById(found[0].field)?.focus());
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const saved = await saveSkillDraft(skillKey, {
        revision: currentRecord.draft_revision,
        name: values.name.trim(),
        description: values.description.trim(),
        category: values.category,
        tags: values.tags,
        visibility: 'workspace',
        definition: buildDefinition(values),
      });
      const next = editorValues(saved);
      setCurrentRecord(saved);
      setValues(next);
      setSavedValues(next);
      setIssues([]);
      loadedRevision.current = `${saved.key}:${saved.draft_revision}:${saved.updated_at}`;
      detail.refresh();
      message.success(t('skill.editor.savedToast'));
    } catch (cause) {
      if (isSkillRevisionConflict(cause)) {
        setConflictOpen(true);
      } else {
        setSaveError(errorText(skillErrorMessage(cause)));
      }
    } finally {
      setSaving(false);
    }
  }

  async function duplicate() {
    if (!currentRecord || !values) return;
    try {
      const copy = await duplicateSkill(skillKey, currentRecord.draft_revision, values.name.trim() || currentRecord.name);
      setConflictOpen(false);
      leaveTo(`/skills/${encodeURIComponent(copy.key)}/edit`);
    } catch (cause) {
      setSaveError(errorText(skillErrorMessage(cause)));
      setConflictOpen(false);
    }
  }

  function reloadServerDraft() {
    setConflictOpen(false);
    loadedRevision.current = '';
    detail.refresh();
  }

  function cancel() {
    const destination = `/skills/${encodeURIComponent(skillKey)}`;
    if (dirty) requestDiscard(destination);
    else leaveTo(destination);
  }

  function addParameter() {
    if (!values) return;
    let index = values.parameters.length + 1;
    let name = `parameter_${index}`;
    while (values.parameters.some(parameter => parameter.name === name)) {
      index += 1;
      name = `parameter_${index}`;
    }
    patch('parameters', [...values.parameters, {
      name,
      type: 'string',
      required: false,
      defaultText: '',
      description: '',
    }]);
    setActiveSection('parameters');
  }

  function updateParameter(index: number, patchValue: Partial<EditorParameter>) {
    if (!values) return;
    patch('parameters', values.parameters.map((parameter, current) =>
      current === index ? { ...parameter, ...patchValue } : parameter));
  }

  function moveParameter(index: number, direction: -1 | 1) {
    if (!values) return;
    const target = index + direction;
    if (target < 0 || target >= values.parameters.length) return;
    const next = [...values.parameters];
    [next[index], next[target]] = [next[target], next[index]];
    patch('parameters', next);
  }

  function removeParameter(index: number) {
    if (!values) return;
    patch('parameters', values.parameters.filter((_, current) => current !== index));
  }

  function currentIssue(field: string): string | undefined {
    return issues.find(issue => issue.field === field)?.message;
  }

  function handleSectionKeys(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + sectionIds.length) % sectionIds.length;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % sectionIds.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = sectionIds.length - 1;
    setActiveSection(sectionIds[next]);
    sectionRefs.current[next]?.focus();
  }

  function renderBasic() {
    if (!values) return null;
    return (
      <div className="skill-editor-section" role="tabpanel" id="skill-panel-basic" aria-labelledby="skill-tab-basic">
        <div className="skill-editor-section-heading">
          <h2>{t('skill.section.basic')}</h2>
          <p>{t('skill.editor.basicHelp')}</p>
        </div>
        <div className="skill-form-grid">
          <Field id="skill-key" label={t('skill.field.key')} required help={t('skill.field.keyHelp')}>
            <Input id="skill-key" value={skillKey} disabled />
          </Field>
          <Field id="skill-owner" label={t('skill.field.owner')}>
            <Input id="skill-owner" value={currentRecord?.updated_by || currentRecord?.created_by || '—'} disabled />
          </Field>
          <Field id="skill-name" label={t('skill.field.name')} required error={currentIssue('skill-name')}>
            <Input
              id="skill-name"
              value={values.name}
              maxLength={100}
              showCount
              onChange={event => patch('name', event.target.value)}
              aria-invalid={Boolean(currentIssue('skill-name'))}
              aria-describedby={currentIssue('skill-name') ? 'skill-name-error' : undefined}
            />
          </Field>
          <Field id="skill-category" label={t('skill.field.category')} required>
            <Select
              id="skill-category"
              value={values.category}
              onChange={value => patch('category', value)}
              options={SKILL_CATEGORIES.map(value => ({ value, label: t(categoryLabel(value)) }))}
            />
          </Field>
          <Field
            id="skill-description"
            label={t('skill.field.description')}
            error={currentIssue('skill-description')}
            help={t('skill.field.descriptionHelp')}
          >
            <Input.TextArea
              id="skill-description"
              rows={4}
              maxLength={1000}
              showCount
              value={values.description}
              onChange={event => patch('description', event.target.value)}
              aria-invalid={Boolean(currentIssue('skill-description'))}
            />
          </Field>
          <Field id="skill-tags" label={t('skill.field.tags')} error={currentIssue('skill-tags')} help={t('skill.field.tagsHelp')}>
            <Select
              id="skill-tags"
              mode="tags"
              value={values.tags}
              onChange={next => patch('tags', next)}
              tokenSeparators={[',']}
              maxTagCount="responsive"
            />
          </Field>
          <Field id="skill-visibility" label={t('skill.field.visibility')} required help={t('skill.field.visibilityHelp')}>
            <Select
              id="skill-visibility"
              value="workspace"
              disabled
              options={[{ value: 'workspace', label: t('skill.visibility.workspace') }]}
            />
          </Field>
        </div>
      </div>
    );
  }

  function renderCapability() {
    if (!values) return null;
    const inputSchema = {
      type: 'object',
      properties: Object.fromEntries(values.parameters.map(parameter => [
        parameter.name || 'unnamed',
        { type: parameter.type, description: parameter.description },
      ])),
      required: values.parameters.filter(parameter => parameter.required).map(parameter => parameter.name),
      additionalProperties: false,
    };
    return (
      <div className="skill-editor-section" role="tabpanel" id="skill-panel-capability" aria-labelledby="skill-tab-capability">
        <div className="skill-editor-section-heading">
          <h2>{t('skill.section.capability')}</h2>
          <p>{t('skill.editor.capabilityHelp')}</p>
        </div>
        <div className="skill-form-grid">
          <Field id="skill-type" label={t('skill.field.type')} required>
            <Select
              id="skill-type"
              value={values.type}
              onChange={value => patch('type', value)}
              options={SKILL_TYPES.map(value => ({ value, label: t(typeLabel(value)) }))}
            />
          </Field>
          <Field id="skill-trigger" label={t('skill.field.trigger')} required>
            <Select
              id="skill-trigger"
              value={values.trigger}
              onChange={value => patch('trigger', value)}
              options={SKILL_TRIGGERS.map(value => ({ value, label: t(`skill.trigger.${value}`) }))}
            />
          </Field>
          <Field id="skill-execution-mode" label={t('skill.field.executionMode')} help={t('skill.field.executionModeHelp')}>
            <Input id="skill-execution-mode" value={t(executionMode(values))} disabled />
          </Field>
          <Field id="skill-output-format" label={t('skill.field.outputFormat')} required>
            <Select
              id="skill-output-format"
              value={values.outputFormat}
              onChange={value => patch('outputFormat', value)}
              options={SKILL_OUTPUT_FORMATS.map(value => ({ value, label: t(`skill.output.${value}`) }))}
            />
          </Field>
          {(values.type === 'instruction' || values.instructions) && (
            <Field
              id="skill-instructions"
              label={t('skill.field.instructions')}
              required={values.type === 'instruction'}
              error={currentIssue('skill-instructions')}
              help={t('skill.field.instructionsHelp')}
            >
              <Input.TextArea
                id="skill-instructions"
                className="skill-code-input"
                rows={8}
                maxLength={12000}
                showCount
                value={values.instructions}
                onChange={event => patch('instructions', event.target.value)}
                spellCheck={false}
              />
            </Field>
          )}
          <Field id="skill-input-schema" label={t('skill.field.inputSchema')} help={t('skill.field.derivedHelp')}>
            <pre id="skill-input-schema" className="skill-schema-preview">{JSON.stringify(inputSchema, null, 2)}</pre>
          </Field>
          {values.outputFormat === 'json' && (
            <Field
              id="skill-output-schema"
              label={t('skill.field.outputSchema')}
              required
              error={currentIssue('skill-output-schema')}
              help={t('skill.field.outputSchemaHelp')}
            >
              <Input.TextArea
                id="skill-output-schema"
                className="skill-code-input"
                rows={8}
                value={values.outputSchemaText}
                onChange={event => patch('outputSchemaText', event.target.value)}
                spellCheck={false}
              />
            </Field>
          )}
        </div>
      </div>
    );
  }

  function renderParameters() {
    if (!values) return null;
    return (
      <div className="skill-editor-section" role="tabpanel" id="skill-panel-parameters" aria-labelledby="skill-tab-parameters">
        <div className="skill-editor-section-heading skill-editor-heading-actions">
          <div>
            <h2>{t('skill.section.parameters')}</h2>
            <p>{t('skill.editor.parametersHelp')}</p>
          </div>
          <Button type="dashed" icon={<PlusOutlined />} onClick={addParameter} disabled={!canManage}>
            {t('skill.action.addParameter')}
          </Button>
        </div>
        {!values.parameters.length && (
          <div className="skill-editor-empty">
            <CodeOutlined />
            <strong>{t('skill.parameters.emptyTitle')}</strong>
            <p>{t('skill.parameters.emptyBody')}</p>
          </div>
        )}
        <div className="skill-parameter-list">
          {values.parameters.map((parameter, index) => (
            <article className="skill-parameter-row" key={`${index}-${parameter.name}`}>
              <div className="skill-parameter-order">
                <strong>{String(index + 1).padStart(2, '0')}</strong>
                <div>
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowUpOutlined />}
                    aria-label={t('skill.action.moveUp')}
                    disabled={index === 0}
                    onClick={() => moveParameter(index, -1)}
                  />
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowDownOutlined />}
                    aria-label={t('skill.action.moveDown')}
                    disabled={index === values.parameters.length - 1}
                    onClick={() => moveParameter(index, 1)}
                  />
                </div>
              </div>
              <Field
                id={`skill-param-name-${index}`}
                label={t('skill.field.parameterName')}
                required
                error={currentIssue(`skill-param-name-${index}`)}
              >
                <Input
                  id={`skill-param-name-${index}`}
                  value={parameter.name}
                  onChange={event => updateParameter(index, { name: event.target.value })}
                />
              </Field>
              <Field id={`skill-param-type-${index}`} label={t('skill.field.parameterType')} required>
                <Select<SkillParameterType>
                  id={`skill-param-type-${index}`}
                  value={parameter.type}
                  onChange={value => updateParameter(index, { type: value })}
                  options={SKILL_PARAMETER_TYPES.map(value => ({ value, label: value }))}
                />
              </Field>
              <Field id={`skill-param-required-${index}`} label={t('skill.field.required')}>
                <Switch
                  id={`skill-param-required-${index}`}
                  checked={parameter.required}
                  onChange={checked => updateParameter(index, { required: checked })}
                  checkedChildren={t('skill.common.yes')}
                  unCheckedChildren={t('skill.common.no')}
                />
              </Field>
              <Field
                id={`skill-param-default-${index}`}
                label={t('skill.field.defaultValue')}
                error={currentIssue(`skill-param-default-${index}`)}
              >
                <Input
                  id={`skill-param-default-${index}`}
                  value={parameter.defaultText}
                  placeholder={t('skill.field.defaultPlaceholder')}
                  onChange={event => updateParameter(index, { defaultText: event.target.value })}
                />
              </Field>
              <Field
                id={`skill-param-description-${index}`}
                label={t('skill.field.parameterDescription')}
                error={currentIssue(`skill-param-description-${index}`)}
              >
                <Input
                  id={`skill-param-description-${index}`}
                  value={parameter.description}
                  maxLength={200}
                  onChange={event => updateParameter(index, { description: event.target.value })}
                />
              </Field>
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
                aria-label={t('skill.action.removeParameter')}
                onClick={() => removeParameter(index)}
                disabled={!canManage}
              />
            </article>
          ))}
        </div>
      </div>
    );
  }

  function renderDependencies() {
    if (!values) return null;
    const options = dependencies.data;
    const selectedTools = options?.tools.filter(tool => values.toolNames.includes(tool.id)) ?? [];
    return (
      <div className="skill-editor-section" role="tabpanel" id="skill-panel-dependencies" aria-labelledby="skill-tab-dependencies">
        <div className="skill-editor-section-heading">
          <h2>{t('skill.section.dependencies')}</h2>
          <p>{t('skill.editor.dependenciesHelp')}</p>
        </div>
        {dependencies.loading && <Skeleton active paragraph={{ rows: 3 }} title={false} />}
        {options?.errors.models && <Alert type="error" showIcon title={t('skill.dependencies.modelLoadError')} description={errorText(options.errors.models)} action={<Button size="small" onClick={dependencies.refresh}>{t('common.retry')}</Button>} />}
        {options?.errors.knowledgeBases && <Alert type="error" showIcon title={t('skill.dependencies.knowledgeLoadError')} description={errorText(options.errors.knowledgeBases)} action={<Button size="small" onClick={dependencies.refresh}>{t('common.retry')}</Button>} />}
        {options?.errors.tools && <Alert type="error" showIcon title={t('skill.dependencies.toolLoadError')} description={errorText(options.errors.tools)} action={<Button size="small" onClick={dependencies.refresh}>{t('common.retry')}</Button>} />}
        <div className="skill-form-grid">
          <Field id="skill-model-profile" label={t('skill.field.modelProfile')} required={values.type === 'instruction'} error={currentIssue('skill-model-profile')} help={t('skill.field.modelProfileHelp')}>
            <Select
              id="skill-model-profile"
              allowClear
              showSearch
              optionFilterProp="label"
              value={values.modelProfileId || undefined}
              onChange={value => {
                const profile = options?.models.find(item => item.id === value);
                patch('modelProfileId', value ?? '');
                if (profile) patch('modelProfileVersion', profile.version);
              }}
              options={options?.models.filter(model => model.enabled).map(model => ({
                value: model.id,
                label: `${model.name} · v${model.version}`,
              })) ?? []}
            />
          </Field>
          <Field id="skill-knowledge-bases" label={t('skill.field.knowledgeBases')} required={values.type === 'knowledge'} error={currentIssue('skill-knowledge-bases')} help={t('skill.field.knowledgeBasesHelp')}>
            <Select
              id="skill-knowledge-bases"
              mode="multiple"
              allowClear
              optionFilterProp="label"
              value={values.knowledgeBaseIds}
              onChange={next => patch('knowledgeBaseIds', next)}
              options={options?.knowledgeBases.filter(base => base.enabled).map(base => ({ value: base.id, label: base.name })) ?? []}
            />
          </Field>
          <Field id="skill-tools" label={t('skill.field.tools')} required={values.type === 'query' || values.type === 'action'} error={currentIssue('skill-tools')} help={t('skill.field.toolsHelp')}>
            <Select
              id="skill-tools"
              mode="multiple"
              allowClear
              optionFilterProp="label"
              value={values.toolNames}
              onChange={next => patch('toolNames', next)}
              options={options?.tools.filter(tool => tool.enabled).map(tool => ({
                value: tool.id,
                label: `${tool.name} · ${t(`skill.effect.${tool.effect}`)}`,
              })) ?? []}
            />
          </Field>
          <Field id="skill-handoff-queue" label={t('skill.field.handoffQueue')} required={values.type === 'handoff'} error={currentIssue('skill-handoff-queue')} help={t('skill.field.handoffQueueHelp')}>
            <Input
              id="skill-handoff-queue"
              value={values.handoffQueue}
              maxLength={100}
              placeholder={t('skill.field.handoffQueuePlaceholder')}
              onChange={event => patch('handoffQueue', event.target.value)}
            />
          </Field>
          <Field id="skill-connector-summary" label={t('skill.field.connectors')} help={t('skill.field.connectorsHelp')}>
            <div id="skill-connector-summary" className="skill-summary-box">
              {t('skill.dependencies.derivedCount {{v0}}', { v0: selectedTools.length })}
              {selectedTools.length > 0 && (
                <div>{selectedTools.map(tool => <Tag key={tool.id}>{tool.name}</Tag>)}</div>
              )}
            </div>
          </Field>
        </div>
      </div>
    );
  }

  function renderRuntime() {
    if (!values) return null;
    return (
      <div className="skill-editor-section" role="tabpanel" id="skill-panel-runtime" aria-labelledby="skill-tab-runtime">
        <div className="skill-editor-section-heading">
          <h2>{t('skill.section.runtime')}</h2>
          <p>{t('skill.editor.runtimeHelp')}</p>
        </div>
        <div className="skill-runtime-alert">
          <SafetyCertificateOutlined />
          <div>
            <strong>{t('skill.runtime.safetyTitle')}</strong>
            <p>{t('skill.runtime.safetyBody')}</p>
          </div>
        </div>
        <div className="skill-form-grid">
          <Field id="skill-timeout" label={t('skill.field.timeout')} required error={currentIssue('skill-timeout')} help={t('skill.field.timeoutHelp')}>
            <InputNumber
              id="skill-timeout"
              min={1}
              max={60}
              value={values.timeoutSeconds}
              onChange={value => patch('timeoutSeconds', value ?? 30)}
              style={{ width: '100%' }}
            />
          </Field>
          <Field id="skill-retry" label={t('skill.field.retryPolicy')} required>
            <Select
              id="skill-retry"
              value={values.retryPolicy}
              onChange={value => patch('retryPolicy', value)}
              options={SKILL_RETRY_POLICIES.map(value => ({ value, label: t(`skill.retry.${value}`) }))}
            />
          </Field>
          <Field id="skill-confirmation" label={t('skill.field.confirmation')} error={currentIssue('skill-confirmation')} help={t('skill.field.confirmationHelp')}>
            <Switch
              id="skill-confirmation"
              checked={values.confirmationRequired}
              onChange={checked => patch('confirmationRequired', checked)}
              checkedChildren={t('skill.common.required')}
              unCheckedChildren={t('skill.common.notRequired')}
            />
          </Field>
          <Field id="skill-idempotency" label={t('skill.field.idempotency')} required>
            <Select
              id="skill-idempotency"
              value={values.idempotency}
              onChange={value => patch('idempotency', value)}
              options={SKILL_IDEMPOTENCY.map(value => ({ value, label: t(`skill.idempotency.${value}`) }))}
            />
          </Field>
          <Field id="skill-error-behavior" label={t('skill.field.errorBehavior')} required>
            <Select
              id="skill-error-behavior"
              value={values.errorBehavior}
              onChange={value => patch('errorBehavior', value)}
              options={SKILL_ERROR_BEHAVIORS.map(value => ({ value, label: t(`skill.errorBehavior.${value}`) }))}
            />
          </Field>
          <Field id="skill-max-amount" label={t('skill.field.maxAmount')} error={currentIssue('skill-max-amount')} help={t('skill.field.maxAmountHelp')}>
            <InputNumber
              id="skill-max-amount"
              min={0}
              precision={2}
              value={values.maxAmount}
              disabled={values.type !== 'action'}
              onChange={value => patch('maxAmount', value)}
              style={{ width: '100%' }}
            />
          </Field>
          <Field id="skill-permission-scope" label={t('skill.field.permissionScope')} help={t('skill.field.permissionScopeHelp')}>
            <Input id="skill-permission-scope" value={t('skill.visibility.workspace')} disabled />
          </Field>
        </div>
        <SkillPackageCard
          skillKey={skillKey}
          revision={currentRecord?.draft_revision ?? 0}
          weightClass={currentRecord?.weight_class}
          canManage={canManage}
          onAttached={record => setCurrentRecord(record)}
        />
      </div>
    );
  }

  function renderEditor() {
    if (!values) return null;
    return (
      <>
        {saveError && (
          <Alert
            className="skill-editor-alert"
            type="error"
            showIcon
            title={t('skill.editor.saveFailed')}
            description={saveError}
          />
        )}
        {issues.length > 0 && (
          <Alert
            className="skill-editor-alert"
            type="warning"
            showIcon
              title={t('skill.editor.validationSummary {{v0}}', { v0: issues.length })}
            description={issues.slice(0, 3).map(issue => issue.message).join(' · ')}
          />
        )}
        <div className="skill-editor-layout">
          <nav className="skill-editor-nav" role="tablist" aria-label={t('skill.editor.sections')} aria-orientation="vertical">
            {sectionIds.map((section, index) => (
              <button
                ref={node => { sectionRefs.current[index] = node; }}
                id={`skill-tab-${section}`}
                key={section}
                type="button"
                role="tab"
                aria-selected={activeSection === section}
                aria-controls={`skill-panel-${section}`}
                tabIndex={activeSection === section ? 0 : -1}
                className={activeSection === section ? 'is-active' : ''}
                onClick={() => setActiveSection(section)}
                onKeyDown={event => handleSectionKeys(event, index)}
              >
                {section === 'basic' && <CheckCircleFilled />}
                {section === 'capability' && <ThunderboltOutlined />}
                {section === 'parameters' && <CodeOutlined />}
                {section === 'dependencies' && <ArrowRightOutlined />}
                {section === 'runtime' && <SafetyCertificateOutlined />}
                <span>{t(sectionLabel(section))}</span>
              </button>
            ))}
          </nav>
          <fieldset className="skill-editor-form" disabled={!canManage}>
            {activeSection === 'basic' && renderBasic()}
            {activeSection === 'capability' && renderCapability()}
            {activeSection === 'parameters' && renderParameters()}
            {activeSection === 'dependencies' && renderDependencies()}
            {activeSection === 'runtime' && renderRuntime()}
          </fieldset>
        </div>
      </>
    );
  }

  if (detail.error) {
    return (
      <div className="skill-flow-page skill-editor-page">
        <SkillBreadcrumb current={skillKey} onOpenCatalog={() => onNavigate('/skills')} />
        <section className="skill-state-panel" role="alert">
          <Alert type="error" showIcon title={t('skill.detail.loadFailed')} description={errorText(detail.error)} />
          <div className="skill-state-actions">
            <Button onClick={detail.refresh}>{t('common.retry')}</Button>
            <Button type="primary" onClick={() => onNavigate('/skills')}>{t('skill.action.backToLibrary')}</Button>
          </div>
        </section>
      </div>
    );
  }

  if (detail.loading || !values || !currentRecord) {
    return (
      <div className="skill-flow-page skill-editor-page">
        <SkillBreadcrumb current={skillKey} onOpenCatalog={() => onNavigate('/skills')} />
        <section className="skill-state-panel" role="status" aria-live="polite">
          <Skeleton active paragraph={{ rows: 8 }} />
          <span className="skill-loading-label">{t('skill.editor.loading')}</span>
        </section>
      </div>
    );
  }

  if (stage === 'test') {
    return (
      <div className="skill-flow-page skill-editor-page">
        <SkillBreadcrumb current={currentRecord.name || skillKey} onOpenCatalog={() => onNavigate('/skills')} />
        <div className="skill-stage-bar">
          <Button icon={<ArrowLeftOutlined />} onClick={() => setStage('edit')}>{t('skill.stage.backToEditor')}</Button>
          <span>{t('skill.stage.testingDraft {{v0}}', { v0: currentRecord.draft_revision })}</span>
        </div>
        <TestWorkbench
          skill={currentRecord}
          skillKey={skillKey}
          canTest={canTest}
          dirty={dirty}
          onEdit={() => setStage('edit')}
          onRelease={() => setStage('release')}
        />
      </div>
    );
  }

  if (stage === 'release') {
    return (
      <div className="skill-flow-page skill-editor-page">
        <SkillBreadcrumb current={currentRecord.name || skillKey} onOpenCatalog={() => onNavigate('/skills')} />
        <div className="skill-stage-bar">
          <Button icon={<ArrowLeftOutlined />} onClick={() => setStage('edit')}>{t('skill.stage.backToEditor')}</Button>
          <span>{t('skill.stage.releaseDraft {{v0}}', { v0: currentRecord.draft_revision })}</span>
        </div>
        <ReleasePanel
          skill={currentRecord}
          canPublish={canPublish}
          dirty={dirty}
          onOpenTests={() => setStage('test')}
          onOpenEditor={section => {
            if (section && sectionIds.includes(section as EditorSection)) setActiveSection(section as EditorSection);
            setStage('edit');
          }}
          onPublished={refresh => {
            detail.refresh();
            if (refresh) setStage('edit');
          }}
        />
      </div>
    );
  }

  return (
    <div className="skill-flow-page skill-editor-page">
      <SkillBreadcrumb current={currentRecord.name || skillKey} onOpenCatalog={() => onNavigate('/skills')} />
      {!canManage && (
        <Alert
          className="skill-editor-alert"
          type="info"
          showIcon
          title={t('skill.permission.readOnlyTitle')}
          description={t('skill.permission.readOnlyBody')}
        />
      )}
      <section className="skill-editor-hero" aria-labelledby="skill-editor-title">
        <div className="skill-editor-hero-icon" aria-hidden="true"><CodeOutlined /></div>
        <div className="skill-editor-hero-copy">
          <div>
            <h1 id="skill-editor-title">{currentRecord.name || t('skill.editor.untitled')}</h1>
            <Tag color={dirty ? 'gold' : 'blue'}>{dirty ? t('skill.editor.unsaved') : t('skill.editor.saved')}</Tag>
            <Tag>{t(modeLabel(values.creationMode))}</Tag>
            <Tag color="geekblue">{t(statusLabel(currentRecord.status))}</Tag>
          </div>
          <p>{currentRecord.description || t('skill.editor.noDescription')}</p>
          <div className="skill-editor-meta">
            <span>{t('skill.editor.draftRevision {{v0}}', { v0: currentRecord.draft_revision })}</span>
            <span>{currentRecord.current_semver ? t('skill.editor.liveVersion {{v0}}', { v0: currentRecord.current_semver }) : t('skill.editor.notPublished')}</span>
            <span>{t('skill.editor.lastSaved {{v0}}', { v0: currentRecord.updated_at ? dateTime(currentRecord.updated_at) : '—' })}</span>
          </div>
        </div>
        <div className="skill-editor-actions">
          <Button onClick={cancel}>{t('skill.action.cancel')}</Button>
          <Button
            icon={<ThunderboltOutlined />}
            disabled={!canTest || dirty}
            title={dirty ? t('skill.editor.saveBeforeTest') : !canTest ? t('skill.permission.testDenied') : undefined}
            onClick={() => setStage('test')}
          >
            {t('skill.action.test')}
          </Button>
          <Button
            icon={<RocketOutlined />}
            disabled={!canPublish || dirty}
            title={dirty ? t('skill.editor.saveBeforeRelease') : !canPublish ? t('skill.permission.publishDenied') : undefined}
            onClick={() => setStage('release')}
          >
            {t('skill.action.release')}
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            disabled={!dirty || !canManage}
            onClick={() => void save()}
          >
            {saving ? t('skill.editor.saving') : t('skill.action.saveDraft')}
          </Button>
        </div>
      </section>
      {renderEditor()}
      <Modal
        open={conflictOpen}
        title={t('skill.editor.conflictTitle')}
        onCancel={() => setConflictOpen(false)}
        footer={[
          <Button key="keep" onClick={() => setConflictOpen(false)}>{t('skill.editor.keepEditing')}</Button>,
          <Button key="duplicate" onClick={() => void duplicate()}>{t('skill.editor.duplicateAsNew')}</Button>,
          <Button key="reload" type="primary" onClick={reloadServerDraft}>{t('skill.editor.reloadServer')}</Button>,
        ]}
      >
        <p>{t('skill.editor.conflictBody {{v0}}', { v0: currentRecord.draft_revision })}</p>
      </Modal>
      {pendingDestination.current && <span className="sr-only" aria-live="polite">{t('skill.editor.discardPending')}</span>}
    </div>
  );
}
