import { useEffect, useRef, useState } from 'react';
import { App as AntApp, Alert, Button, Input, Modal, Select, Skeleton, Tag } from 'antd';
import {
  CheckCircleFilled,
  ClockCircleOutlined,
  DownOutlined,
  HistoryOutlined,
  ReloadOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  UndoOutlined,
  WarningFilled,
  CloseCircleFilled,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { dateTime, errorText } from '../../i18n';
import {
  publishSkill,
  rollbackSkill,
  skillErrorMessage,
} from './api';
import {
  nextSemver,
  type ReadinessCheck,
  type SkillRecord,
  type SkillVersion,
  type VersionBump,
} from './contracts';
import { useSkillReadiness, useSkillVersions } from './useSkills';
import { useStrictFocusTrap } from './useStrictFocusTrap';
import './skill-workflows.css';

interface ReleasePanelProps {
  skill: SkillRecord;
  canPublish: boolean;
  dirty: boolean;
  onOpenTests: () => void;
  onOpenEditor: (section?: string) => void;
  onPublished: (refresh: boolean) => void;
}

function releaseKindLabel(kind: SkillVersion['release_kind']): string {
  return `skill.release.kind.${kind}`;
}

function checkLabel(code: string): string {
  return `skill.readiness.${code}`;
}

function checkIcon(status: ReadinessCheck['status']) {
  if (status === 'pass') return <CheckCircleFilled />;
  if (status === 'warning') return <WarningFilled />;
  return <CloseCircleFilled />;
}

function definitionPreview(version: SkillVersion): string {
  if (!version.definition) return '';
  try {
    return JSON.stringify(version.definition, null, 2);
  } catch {
    return '';
  }
}

export function ReleasePanel({
  skill,
  canPublish,
  dirty,
  onOpenTests,
  onOpenEditor,
  onPublished,
}: ReleasePanelProps) {
  const { t } = useTranslation();
  const { message } = AntApp.useApp();
  const readiness = useSkillReadiness(skill.key, skill.draft_revision, Boolean(skill.key));
  const versions = useSkillVersions(skill.key, Boolean(skill.key));
  const [publishOpen, setPublishOpen] = useState(false);
  const [bump, setBump] = useState<VersionBump>('minor');
  const [notes, setNotes] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState('');
  const [rollbackTarget, setRollbackTarget] = useState<SkillVersion | null>(null);
  const [rollbackNotes, setRollbackNotes] = useState('');
  const [rollingBack, setRollingBack] = useState(false);
  const [rollbackError, setRollbackError] = useState('');
  const [createdVersion, setCreatedVersion] = useState<SkillVersion | null>(null);
  const publishDialogRef = useRef<HTMLDivElement>(null);
  const rollbackDialogRef = useRef<HTMLDivElement>(null);
  const versionItems = versions.data?.items ?? [];
  const currentVersion = skill.published_version;
  const firstRelease = !currentVersion;
  const suggestedSemver = readiness.data?.next_semver ?? nextSemver(skill.current_semver, bump);
  const blockerCount = readiness.data?.checks.filter(check => check.status === 'fail').length ?? 0;
  const warningChecks = readiness.data?.checks.filter(check => check.status === 'warning') ?? [];
  const blockingChecks = readiness.data?.checks.filter(check => check.status === 'fail') ?? [];
  const publishReady = Boolean(readiness.data?.ready && !dirty && canPublish);
  const rollbackBlockedReason = !canPublish
    ? t('skill.versions.rollbackDisabledPermission')
    : dirty
      ? t('skill.versions.rollbackDisabledDirty')
      : '';

  useStrictFocusTrap(publishOpen, publishDialogRef);
  useStrictFocusTrap(Boolean(rollbackTarget), rollbackDialogRef);

  useEffect(() => {
    if (!publishOpen) return;
    setPublishError('');
  }, [publishOpen]);

  function openPublish() {
    setBump(firstRelease ? 'minor' : 'patch');
    setNotes('');
    setPublishError('');
    setPublishOpen(true);
  }

  function jumpToCheck(check: ReadinessCheck) {
    if (check.destination === 'tests') {
      onOpenTests();
      return;
    }
    if (check.destination === 'permission') return;
    if (check.destination && ['basic', 'capability', 'parameters', 'dependencies', 'runtime'].includes(check.destination)) {
      onOpenEditor(check.destination);
      return;
    }
    if (check.code === 'latest_test_passed') onOpenTests();
    else onOpenEditor();
  }

  async function confirmPublish() {
    if (!notes.trim() || publishing) return;
    setPublishing(true);
    setPublishError('');
    try {
      const version = await publishSkill(skill.key, {
        revision: skill.draft_revision,
        bump,
        release_notes: notes.trim(),
      });
      setCreatedVersion(version);
      setPublishOpen(false);
      readiness.refresh();
      versions.refresh();
      message.success(t('skill.release.publishedToast {{v0}}', { v0: version.semver }));
      onPublished(false);
    } catch (cause) {
      setPublishError(errorText(skillErrorMessage(cause)));
    } finally {
      setPublishing(false);
    }
  }

  function openRollback(version: SkillVersion) {
    if (!canPublish || dirty) return;
    setRollbackTarget(version);
    setRollbackNotes('');
    setRollbackError('');
  }

  async function confirmRollback() {
    if (!canPublish || !rollbackTarget || !rollbackNotes.trim() || rollingBack) return;
    setRollingBack(true);
    setRollbackError('');
    try {
      const version = await rollbackSkill(skill.key, {
        revision: skill.draft_revision,
        target_version: rollbackTarget.version,
        release_notes: rollbackNotes.trim(),
      });
      setCreatedVersion(version);
      setRollbackTarget(null);
      readiness.refresh();
      versions.refresh();
      message.success(t('skill.release.rollbackToast {{v0}}', { v0: version.semver }));
      onPublished(false);
    } catch (cause) {
      setRollbackError(errorText(skillErrorMessage(cause)));
    } finally {
      setRollingBack(false);
    }
  }

  const checks = readiness.data?.checks ?? [];
  const latestVersion = createdVersion ?? versionItems[0] ?? null;

  return (
    <section className="skill-release-panel" aria-labelledby="skill-release-title">
      <div className="skill-release-heading">
        <div>
          <h1 id="skill-release-title">{t('skill.release.title')}</h1>
          <p>{t('skill.release.subtitle')}</p>
        </div>
        <div className="skill-release-heading-actions">
          <Tag color="blue">{t('skill.release.draftRevision {{v0}}', { v0: skill.draft_revision })}</Tag>
          {skill.current_semver && <Tag color="green">{t('skill.release.currentVersion {{v0}}', { v0: skill.current_semver })}</Tag>}
          <Button
            type="primary"
            icon={<RocketOutlined />}
            disabled={!publishReady}
            title={dirty
              ? t('skill.release.saveFirst')
              : !canPublish
                ? t('skill.permission.publishDenied')
                : blockerCount
                  ? t('skill.release.blockedCount {{v0}}', { v0: blockerCount })
                  : undefined}
            onClick={openPublish}
          >
            {firstRelease ? t('skill.release.publishFirst') : t('skill.release.publish')}
          </Button>
        </div>
      </div>
      {dirty && <Alert type="warning" showIcon title={t('skill.release.dirtyTitle')} description={t('skill.release.dirtyBody')} />}
      {!canPublish && <Alert type="info" showIcon title={t('skill.permission.publishDenied')} />}
      <div className="skill-release-layout">
        <section className="skill-release-readiness" aria-labelledby="skill-readiness-title">
          <div className="skill-release-section-heading">
            <div>
              <h2 id="skill-readiness-title">{t('skill.readiness.title')}</h2>
              <p>{t('skill.readiness.subtitle')}</p>
            </div>
            {readiness.loading && <span role="status">{t('common.loading')}</span>}
            {!readiness.loading && <Button type="text" icon={<ReloadOutlined />} onClick={readiness.refresh}>{t('common.refresh')}</Button>}
          </div>
          {readiness.error && <Alert type="error" showIcon title={t('skill.readiness.loadError')} description={errorText(readiness.error)} action={<Button size="small" onClick={readiness.refresh}>{t('common.retry')}</Button>} />}
          {readiness.loading && !checks.length ? <Skeleton active paragraph={{ rows: 5 }} title={false} /> : checks.length ? (
            <>
              {readiness.data?.ready && !dirty && <div className="skill-readiness-ready"><CheckCircleFilled /><div><strong>{t('skill.readiness.readyTitle')}</strong><p>{t('skill.readiness.readyBody')}</p></div></div>}
              <div className="skill-checklist">
                {checks.map(check => (
                  <article className={`skill-check-row is-${check.status}`} key={check.code}>
                    <span className="skill-check-icon">{checkIcon(check.status)}</span>
                    <div>
                      <strong>{t(checkLabel(check.code))}</strong>
                      <p>{check.reason || t('skill.readiness.noReason')}</p>
                      {check.destination && check.destination !== 'permission' && (
                        <Button type="link" onClick={() => jumpToCheck(check)}>{t('skill.readiness.openDestination')}</Button>
                      )}
                    </div>
                    <Tag color={check.status === 'pass' ? 'green' : check.status === 'warning' ? 'gold' : 'red'}>{t(`skill.readiness.status.${check.status}`)}</Tag>
                  </article>
                ))}
              </div>
              {blockingChecks.length > 0 && (
                <Alert type="warning" showIcon title={t('skill.readiness.blockedSummary {{v0}}', { v0: blockingChecks.length })} description={t('skill.readiness.blockedBody')} />
              )}
              {warningChecks.length > 0 && (
                <div className="skill-readiness-warnings">
                  <strong>{t('skill.readiness.warnings')}</strong>
                  {warningChecks.map(check => <p key={check.code}>{t(checkLabel(check.code))} · {check.reason}</p>)}
                </div>
              )}
            </>
          ) : !readiness.error ? (
            <div className="skill-readiness-empty"><SafetyCertificateOutlined /><p>{t('skill.readiness.empty')}</p></div>
          ) : null}
        </section>
        <section className="skill-release-versions" aria-labelledby="skill-versions-title">
          <div className="skill-release-section-heading">
            <div>
              <h2 id="skill-versions-title">{t('skill.versions.title')}</h2>
              <p>{t('skill.versions.subtitle')}</p>
            </div>
            {versions.loading && <span role="status">{t('common.loading')}</span>}
            {!versions.loading && <Button type="text" icon={<ReloadOutlined />} onClick={versions.refresh}>{t('common.refresh')}</Button>}
          </div>
          {versions.error && <Alert type="error" showIcon title={t('skill.versions.loadError')} description={errorText(versions.error)} action={<Button size="small" onClick={versions.refresh}>{t('common.retry')}</Button>} />}
          {versions.loading && !versionItems.length ? <Skeleton active paragraph={{ rows: 4 }} title={false} /> : versionItems.length ? (
            <div className="skill-version-list">
              {versionItems.map(version => {
                const isCurrent = version.version === currentVersion;
                return (
                  <article className={`skill-version-row ${isCurrent ? 'is-current' : ''}`} key={version.id || `${version.version}-${version.semver}`}>
                    <div className="skill-version-main">
                      <span className="skill-version-icon"><HistoryOutlined /></span>
                      <div>
                        <div className="skill-version-title">
                          <strong>v{version.semver}</strong>
                          <Tag>{t(releaseKindLabel(version.release_kind))}</Tag>
                          {isCurrent && <Tag color="blue">{t('skill.versions.current')}</Tag>}
                          {version.rollback_from !== null && <Tag color="purple">{t('skill.versions.rollbackFrom {{v0}}', { v0: version.rollback_from })}</Tag>}
                        </div>
                        <p>{version.release_notes || t('skill.versions.noNotes')}</p>
                        <div className="skill-version-meta">
                          <span>{version.created_by || '—'}</span>
                          <span>{version.created_at ? dateTime(version.created_at) : '—'}</span>
                          <span>{t('skill.versions.sourceRevision {{v0}}', { v0: version.source_draft_revision })}</span>
                        </div>
                        {version.definition && (
                          <details className="skill-version-details">
                            <summary>{t('skill.versions.viewSnapshot')} <DownOutlined /></summary>
                            <pre>{definitionPreview(version)}</pre>
                            {version.definition_digest && <code>{version.definition_digest}</code>}
                          </details>
                        )}
                      </div>
                    </div>
                    {!isCurrent ? (
                      <Button
                        icon={<UndoOutlined />}
                        disabled={Boolean(rollbackBlockedReason)}
                        title={rollbackBlockedReason || undefined}
                        onClick={() => openRollback(version)}
                      >
                        {t('skill.versions.rollback')}
                      </Button>
                    ) : <span className="skill-version-current"><CheckCircleFilled />{t('skill.versions.current')}</span>}
                  </article>
                );
              })}
            </div>
          ) : !versions.error ? (
            <div className="skill-versions-empty"><ClockCircleOutlined /><strong>{t('skill.versions.emptyTitle')}</strong><p>{t('skill.versions.emptyBody')}</p></div>
          ) : null}
          {latestVersion && !versions.loading && (
            <p className="skill-version-latest-note" role="status">{t('skill.versions.latestCreated {{v0}}', { v0: latestVersion.semver })}</p>
          )}
        </section>
      </div>
      <Modal
        open={publishOpen}
        panelRef={publishDialogRef}
        title={t('skill.release.publishDialogTitle {{v0}}', { v0: skill.name })}
        onCancel={() => { if (!publishing) setPublishOpen(false); }}
        maskClosable={!publishing}
        footer={[
          <Button key="cancel" disabled={publishing} onClick={() => setPublishOpen(false)}>{t('skill.action.cancel')}</Button>,
          <Button key="publish" type="primary" icon={<RocketOutlined />} loading={publishing} disabled={!notes.trim()} onClick={() => void confirmPublish()}>{publishing ? t('skill.release.publishing') : t('skill.release.confirmPublish')}</Button>,
        ]}
      >
        {publishError && <Alert type="error" showIcon title={t('skill.release.publishError')} description={publishError} />}
        <div className="skill-release-summary">
          <div><span>{t('skill.release.skill')}</span><strong>{skill.name}</strong></div>
          <div><span>{t('skill.release.sourceRevision')}</span><strong>r{skill.draft_revision}</strong></div>
          <div><span>{t('skill.release.nextVersion')}</span><strong>v{suggestedSemver}</strong></div>
        </div>
        <label className="skill-release-field" htmlFor="skill-bump">
          <span>{t('skill.release.bump')}</span>
          <Select<VersionBump>
            id="skill-bump"
            value={bump}
            disabled={firstRelease}
            onChange={setBump}
            options={[
              { value: 'patch', label: t('skill.release.bump.patch') },
              { value: 'minor', label: t('skill.release.bump.minor') },
              { value: 'major', label: t('skill.release.bump.major') },
            ]}
          />
        </label>
        {firstRelease && <Alert type="info" showIcon title={t('skill.release.firstVersionHint')} />}
        <label className="skill-release-field" htmlFor="skill-release-notes">
          <span>{t('skill.release.notes')}<i aria-hidden="true">*</i></span>
          <Input.TextArea
            id="skill-release-notes"
            rows={4}
            maxLength={2000}
            showCount
            value={notes}
            onChange={event => setNotes(event.target.value)}
            placeholder={t('skill.release.notesPlaceholder')}
          />
        </label>
        <p className="skill-release-hint">{t('skill.release.confirmHint')}</p>
      </Modal>
      <Modal
        open={Boolean(rollbackTarget)}
        panelRef={rollbackDialogRef}
        title={t('skill.release.rollbackDialogTitle')}
        onCancel={() => { if (!rollingBack) setRollbackTarget(null); }}
        maskClosable={!rollingBack}
        footer={[
          <Button key="cancel" disabled={rollingBack} onClick={() => setRollbackTarget(null)}>{t('skill.action.cancel')}</Button>,
          <Button
            key="rollback"
            type="primary"
            danger
            icon={<UndoOutlined />}
            loading={rollingBack}
            disabled={!canPublish || !rollbackNotes.trim()}
            title={!canPublish ? t('skill.versions.rollbackDisabledPermission') : undefined}
            onClick={() => void confirmRollback()}
          >{rollingBack ? t('skill.release.rollingBack') : t('skill.release.confirmRollback')}</Button>,
        ]}
      >
        {rollbackError && <Alert type="error" showIcon title={t('skill.release.rollbackError')} description={rollbackError} />}
        <Alert type="warning" showIcon title={t('skill.release.rollbackWarning')} />
        {rollbackTarget && (
          <div className="skill-release-summary">
            <div><span>{t('skill.release.rollbackTarget')}</span><strong>v{rollbackTarget.semver}</strong></div>
            <div><span>{t('skill.release.currentVersionLabel')}</span><strong>{skill.current_semver ? `v${skill.current_semver}` : '—'}</strong></div>
            <div><span>{t('skill.release.newVersion')}</span><strong>{t('skill.release.newVersionAuto')}</strong></div>
          </div>
        )}
        <label className="skill-release-field" htmlFor="skill-rollback-notes">
          <span>{t('skill.release.rollbackNotes')}<i aria-hidden="true">*</i></span>
          <Input.TextArea
            id="skill-rollback-notes"
            rows={4}
            maxLength={2000}
            showCount
            value={rollbackNotes}
            onChange={event => setRollbackNotes(event.target.value)}
            placeholder={t('skill.release.rollbackNotesPlaceholder')}
          />
        </label>
      </Modal>
    </section>
  );
}
