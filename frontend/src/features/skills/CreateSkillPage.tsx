import { useRef, useState, type ReactNode } from 'react';
import { Alert, App as AntApp, Button, Input, Skeleton, Tag } from 'antd';
import {
  AppstoreOutlined,
  ArrowRightOutlined,
  CheckCircleFilled,
  CodeOutlined,
  FileZipOutlined,
  MessageOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { errorText } from '../../i18n';
import { SkillBreadcrumb } from './SkillBreadcrumb';
import { createSkill, importSkillPackage, skillErrorMessage } from './api';
import {
  emptySkillDefinition,
  type CreateSkillRequest,
  type SkillCreationMode,
  type SkillTemplate,
} from './contracts';
import { MAX_PACKAGE_BYTES, usePackageErrorMessage } from './packageError';
import { useSkillPermissions, useSkillTemplates } from './useSkills';
import './skill-workflows.css';

interface CreateSkillPageProps {
  onNavigate: (path: string) => void;
}

interface CreationModeItem {
  id: SkillCreationMode;
  title: string;
  description: string;
  icon: ReactNode;
  iconClass: string;
}

const creationModes: CreationModeItem[] = [
  {
    id: 'ai',
    title: 'skill.create.mode.ai.title',
    description: 'skill.create.mode.ai.description',
    icon: <RobotOutlined />,
    iconClass: 'create-mode-icon-ai',
  },
  {
    id: 'template',
    title: 'skill.create.mode.template.title',
    description: 'skill.create.mode.template.description',
    icon: <AppstoreOutlined />,
    iconClass: 'create-mode-icon-template',
  },
  {
    id: 'professional',
    title: 'skill.create.mode.professional.title',
    description: 'skill.create.mode.professional.description',
    icon: <CodeOutlined />,
    iconClass: 'create-mode-icon-professional',
  },
  {
    // Importing an archive is a creation path, not a package-management action:
    // the zip decides the name, the instructions, and the weight class, so there
    // is nothing to fill in before it runs.
    id: 'package',
    title: 'skill.create.mode.package.title',
    description: 'skill.create.mode.package.description',
    icon: <FileZipOutlined />,
    iconClass: 'create-mode-icon-package',
  },
];

const processSteps = [
  'skill.create.process.create',
  'skill.create.process.configure',
  'skill.create.process.release',
];

function templateIcon(template: SkillTemplate): ReactNode {
  if (template.type === 'knowledge') return <MessageOutlined />;
  if (template.category === 'finance') return <CodeOutlined />;
  return <AppstoreOutlined />;
}

export function CreateSkillPage({ onNavigate }: CreateSkillPageProps) {
  const { t } = useTranslation();
  const { message } = AntApp.useApp();
  const permissions = useSkillPermissions();
  const templates = useSkillTemplates();
  const describePackageError = usePackageErrorMessage();
  const packageInputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<SkillCreationMode>('ai');
  const [prompt, setPrompt] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [packageFile, setPackageFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(false);
  const [fieldError, setFieldError] = useState('');
  const [requestError, setRequestError] = useState('');
  const canManage = permissions.data?.manage ?? false;
  const templateItems = templates.data?.items ?? [];
  const aiEnabled = templates.data?.ai_generation_enabled === true;
  const aiReason = templates.data?.ai_generation_reason
    || (templates.data?.ai_generation_enabled === null
      ? t('skill.create.aiUnavailable')
      : t('skill.create.aiDisabled'));
  const selectedTemplateItem = templateItems.find(item => item.key === selectedTemplate) ?? null;
  const permissionTitle = permissions.loading
    ? t('skill.permission.loading')
    : !canManage
      ? t('skill.permission.createDenied')
      : undefined;

  function validate(modeToCreate: SkillCreationMode): string {
    if (!canManage) return t('skill.permission.createDenied');
    if (modeToCreate === 'ai') {
      if (!aiEnabled) return aiReason;
      const value = prompt.trim();
      if (!value) return t('skill.create.promptRequired');
      if (value.length > 2000) return t('skill.create.promptTooLong');
      return '';
    }
    if (modeToCreate === 'template') {
      if (!selectedTemplate) return t('skill.create.templateRequired');
      if (!selectedTemplateItem) return t('skill.create.templateUnavailable');
      return '';
    }
    if (modeToCreate === 'package') {
      return packageFile ? '' : t('skill.create.packageRequired');
    }
    return '';
  }

  function actionDisabled(modeToCreate: SkillCreationMode): boolean {
    if (creating || !canManage) return true;
    if (modeToCreate === 'ai') return !aiEnabled || templates.loading || !prompt.trim();
    if (modeToCreate === 'template') return templates.loading || !selectedTemplate;
    if (modeToCreate === 'package') return !packageFile;
    return false;
  }

  /** Reject the obvious mistakes before spending a round trip on them. */
  function pickPackage(file: File | undefined | null) {
    if (!file) return;
    setFieldError('');
    setRequestError('');
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setFieldError(t('skill.package.error.skill_package_unsupported'));
      return;
    }
    if (file.size > MAX_PACKAGE_BYTES) {
      setFieldError(t('skill.package.error.skill_package_too_large'));
      return;
    }
    setPackageFile(file);
  }

  async function submitImport(file: File) {
    setMode('package');
    setCreating(true);
    try {
      const created = await importSkillPackage(file);
      message.success(
        t('skill.create.importedToast {{v0}}', {
          v0: t(`skill.weight.short.${created.weight_class}`),
        }),
      );
      // Land on runtime: that section owns the archive and shows what got bound.
      onNavigate(`/skills/${encodeURIComponent(created.key)}/edit?section=runtime`);
    } catch (cause) {
      // Rejections name what to change in the zip, so they get their own mapping.
      setRequestError(errorText(describePackageError(cause)));
    } finally {
      setCreating(false);
    }
  }

  async function submit(modeToCreate: SkillCreationMode = mode) {
    setFieldError('');
    setRequestError('');
    const problem = validate(modeToCreate);
    if (problem) {
      if (modeToCreate === mode) setFieldError(problem);
      return;
    }
    if (modeToCreate === 'package') {
      if (packageFile) await submitImport(packageFile);
      return;
    }
    setMode(modeToCreate);
    setCreating(true);
    let body: CreateSkillRequest;
    if (modeToCreate === 'ai') {
      body = { mode: 'ai', prompt: prompt.trim(), template_key: null, definition: null };
    } else if (modeToCreate === 'template') {
      body = { mode: 'template', prompt: null, template_key: selectedTemplate, definition: null };
    } else {
      body = {
        mode: 'professional',
        prompt: null,
        template_key: null,
        definition: emptySkillDefinition('professional'),
      };
    }
    try {
      const created = await createSkill(body);
      message.success(t('skill.create.created'));
      onNavigate(`/skills/${encodeURIComponent(created.key)}/edit`);
    } catch (cause) {
      setRequestError(errorText(skillErrorMessage(cause)));
    } finally {
      setCreating(false);
    }
  }

  function chooseMode(nextMode: SkillCreationMode) {
    setMode(nextMode);
    setFieldError('');
    setRequestError('');
  }

  function renderModeControl(item: CreationModeItem) {
    if (item.id === 'ai') {
      return (
        <div className="create-ai-control" onClick={event => event.stopPropagation()}>
          {/* The prompt stays visible after a request failure so the user can retry without retyping. */}
          <Input.TextArea
            value={prompt}
            onChange={event => {
              setPrompt(event.target.value);
              setFieldError('');
            }}
            rows={4}
            maxLength={2000}
            showCount
            aria-label={t('skill.create.aiPromptLabel')}
            placeholder={t('skill.create.aiPromptPlaceholder')}
            disabled={!canManage}
          />
          <p className="skill-field-help">{t('skill.create.aiPromptHelp')}</p>
          {!aiEnabled && !templates.loading && (
            <Alert
              type="info"
              showIcon
              title={t('skill.create.aiUnavailableTitle')}
              description={aiReason}
            />
          )}
        </div>
      );
    }
    if (item.id === 'template') {
      return (
        <div className="create-template-picker" onClick={event => event.stopPropagation()}>
          {templates.loading && <Skeleton active paragraph={{ rows: 2 }} title={false} />}
          {templates.error && (
            <Alert
              type="error"
              showIcon
              title={t('skill.create.templatesLoadFailed')}
              description={errorText(templates.error)}
              action={<Button size="small" onClick={templates.refresh}>{t('common.retry')}</Button>}
            />
          )}
          {!templates.loading && !templates.error && templateItems.length === 0 && (
            <p className="skill-editor-empty">{t('skill.create.templatesEmpty')}</p>
          )}
          {!templates.error && templateItems.length > 0 && (
            <div className="create-template-grid" role="radiogroup" aria-label={t('skill.create.templateGroupLabel')}>
              {templateItems.map(template => {
                const selected = selectedTemplate === template.key;
                return (
                  <article
                    key={template.key}
                    className={`create-template-card ${selected ? 'is-selected' : ''}`}
                    role="radio"
                    aria-checked={selected}
                    tabIndex={0}
                    onClick={() => {
                      setSelectedTemplate(template.key);
                      setFieldError('');
                    }}
                    onKeyDown={event => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setSelectedTemplate(template.key);
                        setFieldError('');
                      }
                    }}
                  >
                    <span className="create-template-icon template-icon-blue">{templateIcon(template)}</span>
                    <div>
                      <h3>{template.name || template.key}</h3>
                      <p>{template.description}</p>
                      <div className="create-template-tags">
                        <Tag>{t(`skill.category.${template.category}`)}</Tag>
                        {template.tags.slice(0, 3).map(tag => <span key={tag}>{tag}</span>)}
                      </div>
                    </div>
                    {selected && <CheckCircleFilled className="create-mode-check" aria-hidden="true" />}
                  </article>
                );
              })}
            </div>
          )}
        </div>
      );
    }
    if (item.id === 'package') {
      return (
        <div className="create-package-control" onClick={event => event.stopPropagation()}>
          <input
            ref={packageInputRef}
            type="file"
            accept=".zip,application/zip"
            className="skill-package-file"
            aria-label={t('skill.package.choose')}
            onChange={event => pickPackage(event.target.files?.[0])}
          />
          <button
            type="button"
            className={`skill-package-drop is-compact ${packageFile ? 'is-chosen' : ''}`}
            disabled={creating || !canManage}
            onClick={() => packageInputRef.current?.click()}
            onDragOver={event => event.preventDefault()}
            onDrop={event => {
              event.preventDefault();
              pickPackage(event.dataTransfer.files?.[0]);
            }}
          >
            <FileZipOutlined />
            <strong>
              {packageFile ? packageFile.name : t('skill.package.dropHint')}
            </strong>
            <span>
              {packageFile ? t('skill.create.packageChange') : t('skill.package.dropRules')}
            </span>
          </button>
        </div>
      );
    }
    return (
      <div className="create-professional-note">
        <CodeOutlined />
        <div>
          <strong>{t('skill.create.professionalTitle')}</strong>
          <p>{t('skill.create.professionalBody')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="skill-flow-page create-skill-page">
      <SkillBreadcrumb current={t('skill.create.title')} onOpenCatalog={() => onNavigate('/skills')} />

      <section className="skill-create-hero" aria-labelledby="create-skill-title">
        <div className="skill-create-hero-copy">
          <span className="skills-hero-eyebrow">{t('skill.catalog.eyebrow')}</span>
          <h1 id="create-skill-title">{t('skill.create.title')}</h1>
          <p>{t('skill.create.subtitle')}</p>
        </div>
        <div className="skill-create-hero-art" aria-hidden="true">
          <img src="/assets/skills/skill-hero-art.png" alt="" />
        </div>
      </section>

      <div className="skill-wizard" aria-label={t('skill.create.processLabel')}>
        {processSteps.map((item, index) => (
          <div className={`skill-wizard-step ${index === 0 ? 'is-active' : ''}`} key={item}>
            <span className="skill-wizard-number">{index + 1}</span>
            <span>{t(item)}</span>
            {index < processSteps.length - 1 && <i aria-hidden="true" />}
          </div>
        ))}
      </div>

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
      {!permissions.loading && !canManage && (
        <Alert
          className="skill-editor-alert"
          type="info"
          showIcon
          title={t('skill.permission.createDenied')}
          description={t('skill.permission.createDeniedBody')}
        />
      )}
      {requestError && (
        <Alert
          className="skill-editor-alert"
          type="error"
          showIcon
          title={t('skill.create.failed')}
          description={requestError}
        />
      )}
      {fieldError && (
        <Alert
          className="skill-editor-alert"
          type="warning"
          showIcon
          title={t('skill.create.validationTitle')}
          description={fieldError}
        />
      )}

      <section className="create-mode-grid" aria-label={t('skill.create.modeLabel')}>
        {creationModes.map(item => {
          const selected = mode === item.id;
          return (
            <article
              key={item.id}
              className={`create-mode-card ${selected ? 'is-selected' : ''} ${item.id === 'package' ? 'is-import' : ''}`}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              onClick={() => chooseMode(item.id)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  chooseMode(item.id);
                }
              }}
            >
              {item.id === 'ai' && <span className="create-recommend">{t('skill.create.recommended')}</span>}
              {selected && <CheckCircleFilled className="create-mode-check" aria-hidden="true" />}
              <span className={`create-mode-icon ${item.iconClass}`}>{item.icon}</span>
              <h2>{t(item.title)}</h2>
              <p>{t(item.description)}</p>
              {selected && renderModeControl(item)}
              <Button
                type={selected ? 'primary' : 'default'}
                className="create-mode-action"
                loading={creating && mode === item.id}
                disabled={actionDisabled(item.id)}
                title={permissionTitle}
                onClick={event => {
                  event.stopPropagation();
                  if (!selected) {
                    chooseMode(item.id);
                    return;
                  }
                  void submit(item.id);
                }}
              >
                {t(`skill.create.mode.${item.id}.action`)}<ArrowRightOutlined aria-hidden="true" />
              </Button>
            </article>
          );
        })}
      </section>

      <footer className="skill-flow-footer">
        <Button aria-label={t('skill.action.cancel')} onClick={() => onNavigate('/skills')}>
          {t('skill.action.cancel')}
        </Button>
        <div>
          <span className="skill-create-footer-note">{t('skill.create.footerNote')}</span>
          <Button
            type="primary"
            loading={creating}
            disabled={!canManage}
            title={permissionTitle}
            onClick={() => void submit()}
          >
            {t('skill.action.create')}<ArrowRightOutlined aria-hidden="true" />
          </Button>
        </div>
      </footer>
    </div>
  );
}
