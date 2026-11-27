import { useRef, useState } from 'react';
import { Alert, App as AntApp, Button, Popconfirm, Tag } from 'antd';
import {
  CloudUploadOutlined,
  DeleteOutlined,
  DownOutlined,
  FileZipOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { dateTime } from '../../i18n';
import { deleteSkillPackage, uploadSkillPackage } from './api';
import type { SkillRecord, SkillWeightClass } from './contracts';
import { MAX_PACKAGE_BYTES, usePackageErrorMessage } from './packageError';
import { useSkillPackage } from './useSkills';

interface SkillPackageCardProps {
  skillKey: string;
  revision: number;
  weightClass?: SkillWeightClass;
  canManage: boolean;
  readOnly?: boolean;
  onAttached?: (record: SkillRecord) => void;
}

function shortDigest(digest: string): string {
  return digest.replace(/^sha256:/, '').slice(0, 12);
}

function formatBytes(value: number | null): string {
  if (value === null || Number.isNaN(value) || value <= 0) return '—';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function SkillPackageCard({
  skillKey,
  revision,
  weightClass,
  canManage,
  readOnly = false,
  onAttached,
}: SkillPackageCardProps) {
  const { t } = useTranslation();
  const { message } = AntApp.useApp();
  const describeError = usePackageErrorMessage();
  const state = useSkillPackage(skillKey, revision || null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);

  const attached = state.data;
  const editable = canManage && !readOnly;
  const cardClass = `skill-package-card${readOnly ? ' is-readonly' : ''}`;

  async function send(file: File | undefined | null) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setError(t('skill.package.error.skill_package_unsupported'));
      return;
    }
    if (file.size > MAX_PACKAGE_BYTES) {
      setError(t('skill.package.error.skill_package_too_large'));
      return;
    }
    setBusy(true);
    setError('');
    try {
      const record = await uploadSkillPackage(skillKey, file);
      onAttached?.(record);
      const next = record.weight_class;
      if (next !== 'declarative') {
        message.success(
          t('skill.package.attachedToast {{v0}}', { v0: t(`skill.weight.short.${next}`) }),
        );
      } else {
        message.success(t('skill.package.attached'));
      }
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  async function detach() {
    setBusy(true);
    setError('');
    try {
      const record = await deleteSkillPackage(skillKey);
      onAttached?.(record);
      setExpanded(false);
      message.success(t('skill.package.detached'));
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  }

  const fileInput = !readOnly && (
    <input
      ref={inputRef}
      type="file"
      accept=".zip,application/zip"
      className="skill-package-file"
      aria-label={t('skill.package.choose')}
      onChange={event => void send(event.target.files?.[0])}
    />
  );

  if (state.loading && !attached) {
    return (
      <section className={cardClass} aria-busy="true">
        <div className="skill-package-heading">
          <h3>{t('skill.package.title')}</h3>
        </div>
        <div className="skill-package-skeleton" />
      </section>
    );
  }

  if (state.error && !attached) {
    return (
      <section className={cardClass}>
        <div className="skill-package-heading">
          <h3>{t('skill.package.title')}</h3>
        </div>
        <Alert
          type="error"
          showIcon
          title={t('skill.package.loadFailed')}
          description={state.error}
          action={<Button size="small" onClick={state.refresh}>{t('common.retry')}</Button>}
        />
      </section>
    );
  }

  return (
    <section className={cardClass} aria-labelledby="skill-package-title">
      <div className="skill-package-heading">
        <div>
          <h3 id="skill-package-title">{t('skill.package.title')}</h3>
          <p>{t('skill.package.subtitle')}</p>
        </div>
        {attached && (
          <div className="skill-package-tags">
            {weightClass && (
              <Tag className="skill-class-tag" title={t('skill.weight.hint')}>
                {t(`skill.weight.short.${weightClass}`)}
              </Tag>
            )}
            <Tag color={attached.has_scripts ? 'orange' : 'default'}>
              {attached.has_scripts ? t('skill.package.hasScripts') : t('skill.package.textOnly')}
            </Tag>
          </div>
        )}
      </div>

      {!attached && (
        <>
          {editable ? (
            <button
              type="button"
              className={`skill-package-drop ${dragging ? 'is-dragging' : ''} ${busy ? 'is-busy' : ''}`}
              disabled={busy}
              onClick={() => inputRef.current?.click()}
              onDragOver={event => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={event => {
                event.preventDefault();
                setDragging(false);
                void send(event.dataTransfer.files?.[0]);
              }}
            >
              <CloudUploadOutlined />
              <strong>{busy ? t('skill.package.uploading') : t('skill.package.dropHint')}</strong>
              <span>{t('skill.package.dropRules')}</span>
            </button>
          ) : (
            <p className="skill-package-empty">{t('skill.package.empty')}</p>
          )}
          {fileInput}
        </>
      )}

      {attached && (
        <>
          <div className="skill-package-summary">
            <span className="skill-package-icon"><FileZipOutlined /></span>
            <div className="skill-package-copy">
              <strong>{attached.filename || `${shortDigest(attached.digest)}.zip`}</strong>
              <span>
                {formatBytes(attached.size_bytes)}
                {' · '}
                {t('skill.package.metaFiles {{v0}}', { v0: attached.file_count ?? 0 })}
                {' · '}
                {attached.entrypoint
                  ? t('skill.package.metaEntrypoint {{v0}}', { v0: attached.entrypoint })
                  : t('skill.package.metaNoEntrypoint')}
              </span>
              <span className="skill-package-digest" title={attached.digest}>
                sha256:{shortDigest(attached.digest)}
                {attached.created_at ? ` · ${dateTime(attached.created_at)}` : ''}
              </span>
            </div>
            <div className="skill-package-actions">
              <Button
                type="text"
                size="small"
                icon={expanded ? <DownOutlined /> : <RightOutlined />}
                onClick={() => setExpanded(value => !value)}
              >
                {t('skill.package.files')}
              </Button>
              {editable && (
                <>
                  <Button size="small" disabled={busy} onClick={() => inputRef.current?.click()}>
                    {busy ? t('skill.package.uploading') : t('skill.package.replace')}
                  </Button>
                  <Popconfirm
                    title={t('skill.package.removeTitle')}
                    description={t('skill.package.removeBody')}
                    okText={t('skill.package.remove')}
                    cancelText={t('common.cancel')}
                    okButtonProps={{ danger: true, disabled: busy }}
                    onConfirm={() => void detach()}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} disabled={busy}>
                      {t('skill.package.remove')}
                    </Button>
                  </Popconfirm>
                </>
              )}
            </div>
          </div>
          {fileInput}
          {expanded && (
            <ul className="skill-package-files" aria-label={t('skill.package.files')}>
              {state.data?.files.length ? state.data.files.map(file => (
                <li key={file.path}>
                  <code>{file.path}</code>
                  {file.executable && <Tag color="orange">{t('skill.package.fileScript')}</Tag>}
                  <span>{formatBytes(file.size)}</span>
                </li>
              )) : (
                <li className="skill-package-files-empty">{t('skill.package.filesEmpty')}</li>
              )}
            </ul>
          )}
        </>
      )}

      {error && (
        <Alert
          className="skill-package-error"
          type="error"
          showIcon
          title={t('skill.package.rejected')}
          description={error}
          closable
          onClose={() => setError('')}
        />
      )}
    </section>
  );
}
