import { useMemo, useState, type ReactNode } from 'react';
import {
  Alert as InlineAlert,
  Button,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Spin,
  Switch,
} from 'antd';
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloudDownloadOutlined,
  CodeOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  FieldTimeOutlined,
  HistoryOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ToolOutlined,
  UserSwitchOutlined,
} from '@ant-design/icons';
import type {
  IndustryPackCatalog,
  IndustryPackInstallation,
  IndustryPackInstallationPage,
  IndustryPackInstallResult,
  IndustryPackMaturity,
  IndustryPackSummary,
  IndustryPackUpgradePreview,
  IndustryPackUpgradeStatus,
  ServiceProvider,
  ServiceProviderInput,
  ServiceProviderKind,
  ServiceProviderPage,
} from '../../shared/api/client';
import {
  applyIndustryPackUpgrade,
  createServiceProvider,
  installIndustryPack,
  previewIndustryPackUpgrade,
  updateServiceProvider,
} from '../../shared/api/client';
import { Alert, toast, useAccess, useResource } from '../../shared/components/ui';
import { dateTime, t } from '../../i18n/index';

type IndustryTab = 'packs' | 'providers' | 'upgrades';

interface InstallFormValues {
  application_key?: string;
  pack_version: string;
  install_scope: 'all' | 'blueprint';
}

interface ProviderFormValues {
  key: string;
  kind: ServiceProviderKind;
  name: string;
  description?: string;
  enabled: boolean;
  config_text: string;
}

interface Props {
  onNavigate: (path: string) => void;
}

const tabs: Array<{ key: IndustryTab; label: string; icon: ReactNode }> = [
  { key: 'packs', label: '行业模板', icon: <DeploymentUnitOutlined/> },
  { key: 'providers', label: '接入能力', icon: <LinkOutlined/> },
  { key: 'upgrades', label: '升级记录', icon: <HistoryOutlined/> },
];

const maturityLabel: Record<IndustryPackMaturity, string> = {
  alpha: '内测',
  beta: '公测',
  ga: '正式',
};

const maturityDescription: Record<IndustryPackMaturity, string> = {
  alpha: '仅用于验证，不允许生产发布',
  beta: '需要灰度渠道才能发布',
  ga: '可正式发布给客户',
};

const installationStatusLabel: Record<IndustryPackInstallation['status'], string> = {
  installed: '已安装',
  upgrading: '升级中',
  conflicted: '有冲突',
  blocked: '已阻断',
};

const upgradeStatusLabel: Record<IndustryPackUpgradeStatus, string> = {
  clean: '可安全升级',
  conflicted: '存在冲突',
  blocked: '无法升级',
};

const providerKindLabel: Record<ServiceProviderKind, string> = {
  object: '业务对象',
  tool: '工具能力',
  human_queue: '人工队列',
};

const providerKindDescription: Record<ServiceProviderKind, string> = {
  object: '订单、发票、物流等业务数据来源',
  tool: '查询、办理和外部系统调用能力',
  human_queue: '转人工后的坐席队列与承接方式',
};

function providerKindOptions() {
  return (Object.keys(providerKindLabel) as ServiceProviderKind[])
    .map(value => ({ value, label: t(providerKindLabel[value]) }));
}

function timeLabel(value?: string | null): string {
  return value ? dateTime(value) : t('暂无记录');
}

function packTone(maturity: IndustryPackMaturity): string {
  if (maturity === 'ga') return 'ga';
  if (maturity === 'beta') return 'beta';
  return 'alpha';
}

function providerIcon(kind: ServiceProviderKind): ReactNode {
  if (kind === 'object') return <DatabaseOutlined/>;
  if (kind === 'tool') return <ToolOutlined/>;
  return <UserSwitchOutlined/>;
}

function conflictPaths(preview: IndustryPackUpgradePreview): string[] {
  const scenarioPaths = preview.scenarios.flatMap(item =>
    item.conflicts.map(conflict => `${item.scenario_key} · ${conflict.path || t('整体配置')}`));
  const applicationPaths = preview.application_conflicts.map(conflict =>
    `${t('应用配置')} · ${conflict.path || t('整体配置')}`);
  return [...new Set([...scenarioPaths, ...applicationPaths])];
}

function parseConfig(value: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  }
  catch {
    throw new Error(t('请输入有效的 JSON 对象。'));
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(t('请输入有效的 JSON 对象。'));
  }
  return parsed as Record<string, unknown>;
}

export function IndustryCapabilitiesPage({ onNavigate }: Props) {
  const { admin } = useAccess();
  const [tab, setTab] = useState<IndustryTab>('packs');
  const packs = useResource<IndustryPackCatalog>('/industry-packs');
  const installations = useResource<IndustryPackInstallationPage>('/industry-packs/installations');
  const [providerKind, setProviderKind] = useState<ServiceProviderKind | 'all'>('all');
  const [providerQuery, setProviderQuery] = useState('');
  const providerPath = useMemo(() => {
    const params = new URLSearchParams();
    if (providerKind !== 'all') params.set('kind', providerKind);
    if (providerQuery.trim()) params.set('q', providerQuery.trim());
    const suffix = params.toString();
    return `/service-providers${suffix ? `?${suffix}` : ''}`;
  }, [providerKind, providerQuery]);
  const providers = useResource<ServiceProviderPage>(providerPath);

  const [installForm] = Form.useForm<InstallFormValues>();
  const [installPack, setInstallPack] = useState<IndustryPackSummary | null>(null);
  const [installBusy, setInstallBusy] = useState(false);
  const [installError, setInstallError] = useState('');
  const [installResult, setInstallResult] = useState<IndustryPackInstallResult | null>(null);

  const [providerForm] = Form.useForm<ProviderFormValues>();
  const [providerOpen, setProviderOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ServiceProvider | null>(null);
  const [providerBusy, setProviderBusy] = useState(false);
  const [providerError, setProviderError] = useState('');

  const [upgradeInstallation, setUpgradeInstallation] = useState<IndustryPackInstallation | null>(null);
  const [upgradeTargetVersion, setUpgradeTargetVersion] = useState('');
  const [upgradePreview, setUpgradePreview] = useState<IndustryPackUpgradePreview | null>(null);
  const [upgradeBusy, setUpgradeBusy] = useState(false);
  const [upgradeError, setUpgradeError] = useState('');

  const packItems = packs.data?.items || [];
  const installationItems = installations.data?.items || [];
  const providerItems = providers.data?.items || [];
  const providerTotal = providers.data?.total ?? providerItems.length;
  const packByKey = useMemo(
    () => new Map(packItems.map(item => [item.pack_key, item])),
    [packItems],
  );
  const installedCount = installations.data?.total ?? installationItems.length;
  const enabledProviderCount = providerItems.filter(item => item.enabled).length;

  function openInstall(pack: IndustryPackSummary) {
    setInstallPack(pack);
    setInstallError('');
    setInstallResult(null);
    installForm.resetFields();
    installForm.setFieldsValue({
      application_key: pack.application_key || '',
      pack_version: pack.pack_version,
      install_scope: 'blueprint',
    });
  }

  async function submitInstall() {
    if (!installPack) return;
    const values = await installForm.validateFields();
    setInstallBusy(true);
    setInstallError('');
    try {
      const result = await installIndustryPack(installPack.pack_key, {
        pack_version: values.pack_version.trim(),
        application_key: values.application_key?.trim() || undefined,
        install_scenarios: values.install_scope === 'all',
      });
      setInstallResult(result);
      packs.refresh();
      installations.refresh();
      providers.refresh();
      toast.success(
        result.created
          ? t('行业模板已安装，场景和应用已保存为草稿。')
          : t('该行业模板已安装到所选应用，无需重复安装。'),
      );
    }
    catch (cause) {
      setInstallError(cause instanceof Error ? cause.message : t('安装行业模板失败。'));
    }
    finally {
      setInstallBusy(false);
    }
  }

  function openProvider(provider?: ServiceProvider) {
    setEditingProvider(provider || null);
    setProviderError('');
    providerForm.resetFields();
    providerForm.setFieldsValue({
      key: provider?.key || '',
      kind: provider?.kind || (providerKind === 'all' ? 'object' : providerKind),
      name: provider?.name || '',
      description: provider?.description || '',
      enabled: provider?.enabled ?? false,
      config_text: JSON.stringify(provider?.config || {}, null, 2),
    });
    setProviderOpen(true);
  }

  async function submitProvider() {
    const values = await providerForm.validateFields();
    setProviderBusy(true);
    setProviderError('');
    try {
      const config = parseConfig(values.config_text);
      const body: ServiceProviderInput = {
        key: values.key.trim(),
        kind: values.kind,
        name: values.name.trim(),
        description: values.description?.trim() || '',
        enabled: values.enabled,
        config,
      };
      if (editingProvider) {
        await updateServiceProvider(editingProvider.kind, editingProvider.key, {
          ...body,
          revision: editingProvider.revision,
        });
        toast.success(t('接入能力已更新。'));
      }
      else {
        await createServiceProvider(body);
        toast.success(t('接入能力已创建。'));
      }
      providers.refresh();
      setProviderOpen(false);
      setEditingProvider(null);
    }
    catch (cause) {
      setProviderError(cause instanceof Error ? cause.message : t('保存接入能力失败。'));
    }
    finally {
      setProviderBusy(false);
    }
  }

  function openUpgrade(installation: IndustryPackInstallation) {
    setUpgradeInstallation(installation);
    setUpgradeTargetVersion(packByKey.get(installation.pack_key)?.pack_version || '');
    setUpgradePreview(null);
    setUpgradeError('');
  }

  async function runUpgradePreview() {
    if (!upgradeInstallation) return;
    setUpgradeBusy(true);
    setUpgradeError('');
    setUpgradePreview(null);
    try {
      const preview = await previewIndustryPackUpgrade(
        upgradeInstallation.id,
        upgradeTargetVersion.trim() || undefined,
      );
      setUpgradePreview(preview);
    }
    catch (cause) {
      setUpgradeError(cause instanceof Error ? cause.message : t('检查升级失败。'));
    }
    finally {
      setUpgradeBusy(false);
    }
  }

  async function applyUpgrade() {
    if (!upgradeInstallation || !upgradePreview || upgradePreview.status !== 'clean') return;
    setUpgradeBusy(true);
    setUpgradeError('');
    try {
      await applyIndustryPackUpgrade(
        upgradeInstallation.id,
        upgradePreview.id,
        upgradeTargetVersion.trim() || undefined,
      );
      packs.refresh();
      installations.refresh();
      providers.refresh();
      setUpgradePreview(null);
      setUpgradeInstallation(null);
      toast.success(t('行业模板升级已应用，相关场景和应用仍保持草稿状态。'));
    }
    catch (cause) {
      setUpgradeError(cause instanceof Error ? cause.message : t('应用升级失败。'));
    }
    finally {
      setUpgradeBusy(false);
    }
  }

  return <div className="sa-industry">
    <section className="sa-industry-hero">
      <div>
        <span className="sa-eyebrow">INDUSTRY CAPABILITIES</span>
        <h2>{t('把行业模板和接入能力变成可复用的服务资产')}</h2>
        <p>{t('在服务应用体系内安装行业模板、配置业务数据来源，并安全合并后续模板升级。所有变更先进入草稿，不自动对外发布。')}</p>
        <div className="sa-industry-hero-actions">
          <Button icon={<ArrowLeftOutlined/>} onClick={() => onNavigate('/service-apps')}>
            {t('返回服务应用')}
          </Button>
          <span><SafetyCertificateOutlined/> {t('模板升级不覆盖本地业务修改')}</span>
        </div>
      </div>
      <div className="sa-industry-hero-mark">
        <DeploymentUnitOutlined/>
        <strong>{t('行业能力中心')}</strong>
        <small>{t('模板 · 接入 · 升级')}</small>
      </div>
    </section>

    <Alert error={packs.error || installations.error || providers.error}/>

    <section className="sa-industry-metrics">
      <IndustryMetric label={t('行业模板')} value={String(packs.data?.total ?? packItems.length)} hint={t('可安装的行业能力包')}/>
      <IndustryMetric label={t('已安装')} value={String(installedCount)} hint={t('已落地到服务应用')}/>
      <IndustryMetric label={t('接入能力')} value={String(providerTotal)} hint={t('业务对象、工具与人工队列')}/>
      <IndustryMetric label={t('当前启用')} value={String(enabledProviderCount)} hint={t('可被发布检查使用的接入项')}/>
    </section>

    <nav className="sa-studio-tabs sa-industry-tabs" aria-label={t('行业能力管理')}>
      {tabs.map(item => <button
        type="button"
        key={item.key}
        className={tab === item.key ? 'is-active' : ''}
        onClick={() => setTab(item.key)}
      >
        {item.icon}
        {t(item.label)}
        <i>
          {item.key === 'packs'
            ? packItems.length
            : item.key === 'providers'
              ? providerTotal
              : installedCount}
        </i>
      </button>)}
    </nav>

    {tab === 'packs' && <section className="sa-industry-section">
      <div className="sa-section-head">
        <div>
          <span className="sa-eyebrow">PACK CATALOG</span>
          <h3>{t('行业模板')}</h3>
          <p>{t('安装后生成独立的场景和应用草稿，不覆盖已有同标识资产。')}</p>
        </div>
        <Button icon={<ReloadOutlined/>} onClick={packs.refresh} loading={packs.loading}>
          {t('刷新')}
        </Button>
      </div>
      <div className="sa-pack-grid">
        {packItems.map(pack => <article className={`sa-pack-card ${packTone(pack.maturity)}`} key={pack.pack_key}>
          <div className="sa-pack-card-head">
            <span className="sa-pack-icon"><DeploymentUnitOutlined/></span>
            <span className={`sa-maturity-tag ${packTone(pack.maturity)}`}>
              <i/>{t(maturityLabel[pack.maturity])}
            </span>
          </div>
          <div className="sa-pack-title">
            <h3>{pack.name}</h3>
            <span>v{pack.pack_version}</span>
          </div>
          <p>{pack.description || t('暂无模板说明')}</p>
          <div className="sa-pack-numbers">
            <span><strong>{pack.object_count}</strong><small>{t('业务对象')}</small></span>
            <span><strong>{pack.scenario_count}</strong><small>{t('服务场景')}</small></span>
            <span><strong>{pack.installation_count}</strong><small>{t('安装次数')}</small></span>
          </div>
          <div className="sa-pack-maturity-note">
            <ExclamationCircleFilled/>
            <span>{t(maturityDescription[pack.maturity])}</span>
          </div>
          <div className="sa-pack-card-foot">
            <span><FieldTimeOutlined/> {t('应用标识：{{v0}}', { v0: pack.application_key || t('安装时指定') })}</span>
            <Button
              type="primary"
              icon={<CloudDownloadOutlined/>}
              disabled={!admin}
              onClick={() => openInstall(pack)}
            >
              {t('安装')}
            </Button>
          </div>
        </article>)}
        {packs.loading && !packs.data && <div className="sa-industry-loading"><Spin/></div>}
        {!packs.loading && !packItems.length && <IndustryEmpty
          icon={<DeploymentUnitOutlined/>}
          title={t('暂无行业模板')}
          detail={t('内置或扩展提供的行业模板会显示在这里。')}
        />}
      </div>
    </section>}

    {tab === 'providers' && <section className="sa-industry-section">
      <div className="sa-section-head">
        <div>
          <span className="sa-eyebrow">PROVIDER REGISTRY</span>
          <h3>{t('接入能力')}</h3>
          <p>{t('维护业务对象、工具和人工队列的可用状态，发布检查只消费业务结果。')}</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined/>}
          disabled={!admin}
          onClick={() => openProvider()}
        >
          {t('新建接入能力')}
        </Button>
      </div>
      <div className="sa-provider-toolbar">
        <Select
          value={providerKind}
          onChange={setProviderKind}
          options={[
            { value: 'all', label: t('全部类型') },
            ...providerKindOptions(),
          ]}
        />
        <Input.Search
          allowClear
          value={providerQuery}
          placeholder={t('搜索名称、标识或说明')}
          onChange={event => setProviderQuery(event.target.value)}
        />
        <Button icon={<ReloadOutlined/>} onClick={providers.refresh} loading={providers.loading}>
          {t('刷新')}
        </Button>
      </div>
      <div className="sa-provider-grid">
        {providerItems.map(provider => <article className="sa-provider-card" key={provider.id}>
          <div className="sa-provider-card-head">
            <span className={`sa-provider-icon ${provider.kind}`}>{providerIcon(provider.kind)}</span>
            <span className={`sa-provider-state ${provider.enabled ? 'enabled' : 'disabled'}`}>
              <i/>{provider.enabled ? t('已启用') : t('未启用')}
            </span>
          </div>
          <div className="sa-provider-title">
            <div>
              <h3>{provider.name}</h3>
              <small>{t(providerKindLabel[provider.kind])} · {provider.key}</small>
            </div>
            <Button
              type="text"
              icon={<EditOutlined/>}
              aria-label={t('编辑 {{v0}}', { v0: provider.name })}
              disabled={!admin}
              onClick={() => openProvider(provider)}
            />
          </div>
          <p>{provider.description || t(providerKindDescription[provider.kind])}</p>
          <div className="sa-provider-meta">
            <span><CodeOutlined/> {t('{{v0}} 项配置', { v0: Object.keys(provider.config || {}).length })}</span>
            <span>{t('版本 r{{v0}}', { v0: provider.revision })}</span>
          </div>
          <div className="sa-provider-foot">
            <span>{t('来源：{{v0}}', { v0: provider.source || t('手工配置') })}</span>
            {provider.source_ref && <span title={provider.source_ref}>{provider.source_ref}</span>}
          </div>
        </article>)}
        {providers.loading && !providers.data && <div className="sa-industry-loading"><Spin/></div>}
        {!providers.loading && !providerItems.length && <IndustryEmpty
          icon={<LinkOutlined/>}
          title={t('暂无接入能力')}
          detail={t('新建业务对象、工具或人工队列后，发布检查可以确认执行链路是否就绪。')}
        />}
      </div>
    </section>}

    {tab === 'upgrades' && <section className="sa-industry-section">
      <div className="sa-section-head">
        <div>
          <span className="sa-eyebrow">INSTALLATIONS & UPGRADES</span>
          <h3>{t('升级记录')}</h3>
          <p>{t('先检查三方合并结果，再应用升级；有冲突或阻断时不会修改现有草稿。')}</p>
        </div>
        <Button icon={<ReloadOutlined/>} onClick={installations.refresh} loading={installations.loading}>
          {t('刷新')}
        </Button>
      </div>
      <div className="sa-upgrade-list">
        {installationItems.map(installation => {
          const pack = packByKey.get(installation.pack_key);
          return <article className="sa-upgrade-card" key={installation.id}>
            <span className={`sa-upgrade-icon ${installation.status}`}>
              {installation.status === 'installed' ? <CheckCircleFilled/> : <HistoryOutlined/>}
            </span>
            <div className="sa-upgrade-main">
              <div className="sa-upgrade-title">
                <div>
                  <h3>{pack?.name || installation.pack_key}</h3>
                  <p>{t('应用 {{v0}}', { v0: installation.application_key })}</p>
                </div>
                <span className={`sa-installation-status ${installation.status}`}>
                  {t(installationStatusLabel[installation.status])}
                </span>
              </div>
              <div className="sa-upgrade-meta">
                <span>{t('已安装版本')} <strong>v{installation.pack_version}</strong></span>
                <span>{t('目标版本')} <strong>v{pack?.pack_version || installation.pack_version}</strong></span>
                <span>{t('{{v0}} 个场景', { v0: Object.keys(installation.installed_scenarios).length })}</span>
                <span><ClockCircleOutlined/> {timeLabel(installation.updated_at || installation.created_at)}</span>
              </div>
            </div>
            <Button
              icon={<ArrowRightOutlined/>}
              disabled={!admin}
              onClick={() => openUpgrade(installation)}
            >
              {t('检查升级')}
            </Button>
          </article>;
        })}
        {installations.loading && !installations.data && <div className="sa-industry-loading"><Spin/></div>}
        {!installations.loading && !installationItems.length && <IndustryEmpty
          icon={<HistoryOutlined/>}
          title={t('暂无行业模板安装记录')}
          detail={t('安装行业模板后，可以在这里检查新版本并预览合并结果。')}
        />}
      </div>
    </section>}

    <Modal
      title={installPack ? t('安装 {{v0}}', { v0: installPack.name }) : t('安装行业模板')}
      open={!!installPack}
      okText={installResult ? t('关闭') : t('开始安装')}
      cancelText={t('取消')}
      confirmLoading={installBusy}
      destroyOnHidden
      onCancel={() => {
        if (installBusy) return;
        setInstallPack(null);
        setInstallError('');
        setInstallResult(null);
      }}
      onOk={() => {
        if (installResult) {
          setInstallPack(null);
          setInstallResult(null);
          return;
        }
        void submitInstall();
      }}
    >
      <InlineAlert
        type={installResult ? 'success' : 'info'}
        showIcon
        message={installResult
          ? installResult.created
            ? t('安装完成')
            : t('模板已存在')
          : t('安装会创建场景和应用草稿')}
        description={installResult
          ? installResult.created
            ? t('场景、应用和接入能力占位已写入，可在服务应用中继续配置。')
            : t('当前应用已安装同一版本的行业模板。')
          : t('安装不会覆盖已有场景，也不会自动发布。')}
        style={{ marginBottom: 16 }}
      />
      <Alert error={installError}/>
      {!installResult && <Form form={installForm} layout="vertical">
        <Form.Item
          name="application_key"
          label={t('应用标识')}
          extra={t('留空时使用模板提供的默认应用标识；应用已存在时安装会中止。')}
          rules={[{
            pattern: /^[a-z][a-z0-9_-]{0,63}$/,
            message: t('请使用小写字母、数字、- 或 _，并以小写字母开头'),
          }]}
        >
          <Input addonBefore="/service-apps/" maxLength={64} placeholder="content-community-service"/>
        </Form.Item>
        <Form.Item
          name="pack_version"
          label={t('模板版本')}
          rules={[{ required: true, whitespace: true, message: t('请输入模板版本') }]}
        >
          <Input placeholder="1.0.0"/>
        </Form.Item>
        <Form.Item
          name="install_scope"
          label={t('场景范围')}
          rules={[{ required: true }]}
        >
          <Radio.Group className="sa-install-scope">
            <Radio value="blueprint">
              <strong>{t('仅应用蓝图场景')}</strong>
              <small>{t('只安装应用默认引用的场景，适合快速开始。')}</small>
            </Radio>
            <Radio value="all">
              <strong>{t('全部场景')}</strong>
              <small>{t('安装模板中的全部场景，可按需在应用内启用。')}</small>
            </Radio>
          </Radio.Group>
        </Form.Item>
      </Form>}
      {installResult && <dl className="sa-install-result">
        <dt>{t('应用标识')}</dt><dd>{installResult.installation.application_key}</dd>
        <dt>{t('模板版本')}</dt><dd>v{installResult.installation.pack_version}</dd>
        <dt>{t('安装场景')}</dt><dd>{Object.keys(installResult.installation.installed_scenarios).length}</dd>
        <dt>{t('安装状态')}</dt><dd>{t(installationStatusLabel[installResult.installation.status])}</dd>
      </dl>}
    </Modal>

    <Modal
      title={editingProvider ? t('编辑接入能力') : t('新建接入能力')}
      open={providerOpen}
      okText={t('保存')}
      cancelText={t('取消')}
      confirmLoading={providerBusy}
      destroyOnHidden
      width={640}
      onCancel={() => {
        if (providerBusy) return;
        setProviderOpen(false);
        setEditingProvider(null);
        setProviderError('');
      }}
      onOk={() => void submitProvider()}
    >
      <Alert error={providerError}/>
      <Form form={providerForm} layout="vertical">
        <div className="sa-form-grid two">
          <Form.Item
            name="key"
            label={t('能力标识')}
            rules={[
              { required: true, whitespace: true, message: t('请输入能力标识') },
              {
                pattern: /^[a-z][a-z0-9_.:-]{0,99}$/,
                message: t('请使用小写字母、数字、点、冒号、下划线或 -'),
              },
            ]}
          >
            <Input disabled={!!editingProvider} placeholder="order-data"/>
          </Form.Item>
          <Form.Item
            name="kind"
            label={t('能力类型')}
            rules={[{ required: true, message: t('请选择能力类型') }]}
          >
            <Select disabled={!!editingProvider} options={providerKindOptions()}/>
          </Form.Item>
        </div>
        <Form.Item
          name="name"
          label={t('展示名称')}
          rules={[{ required: true, whitespace: true, message: t('请输入展示名称') }]}
        >
          <Input maxLength={100} showCount placeholder={t('例如：订单查询服务')}/>
        </Form.Item>
        <Form.Item name="description" label={t('说明')}>
          <Input.TextArea
            rows={2}
            maxLength={1000}
            showCount
            placeholder={t('说明这个接入能力由谁提供、承接什么业务。')}
          />
        </Form.Item>
        <Form.Item name="enabled" label={t('启用状态')} valuePropName="checked">
          <Switch checkedChildren={t('已启用')} unCheckedChildren={t('未启用')}/>
        </Form.Item>
        <Form.Item
          name="config_text"
          label={t('连接配置（JSON）')}
          extra={t('只保存管理员配置，不会展示在客户侧或发布检查文案中。')}
          rules={[{
            validator: async (_, value: string) => {
              try {
                parseConfig(value || '');
              }
              catch {
                throw new Error(t('请输入有效的 JSON 对象。'));
              }
            },
          }]}
        >
          <Input.TextArea
            className="sa-json-editor"
            rows={9}
            spellCheck={false}
            placeholder={'{\n  "endpoint": "https://example.com"\n}'}
          />
        </Form.Item>
      </Form>
    </Modal>

    <Modal
      title={t('检查行业模板升级')}
      open={!!upgradeInstallation}
      okText={upgradePreview?.status === 'clean' ? t('应用升级') : t('关闭')}
      cancelText={t('取消')}
      confirmLoading={upgradeBusy}
      destroyOnHidden
      width={760}
      onCancel={() => {
        if (upgradeBusy) return;
        setUpgradeInstallation(null);
        setUpgradePreview(null);
        setUpgradeError('');
      }}
      onOk={() => {
        if (upgradePreview?.status === 'clean') {
          void applyUpgrade();
          return;
        }
        setUpgradeInstallation(null);
        setUpgradePreview(null);
      }}
    >
      <Alert error={upgradeError}/>
      {upgradeInstallation && <div className="sa-upgrade-modal">
        <div className="sa-upgrade-target">
          <div>
            <span>{t('当前安装')}</span>
            <strong>v{upgradeInstallation.pack_version}</strong>
            <small>{upgradeInstallation.application_key}</small>
          </div>
          <ArrowRightOutlined/>
          <Input
            value={upgradeTargetVersion}
            placeholder={t('目标版本，例如 1.1.0')}
            onChange={event => setUpgradeTargetVersion(event.target.value)}
          />
          <Button
            type="primary"
            icon={<SafetyCertificateOutlined/>}
            loading={upgradeBusy}
            onClick={() => void runUpgradePreview()}
          >
            {t('预览合并')}
          </Button>
        </div>
        {upgradePreview && <>
          <div className={`sa-upgrade-verdict ${upgradePreview.status}`}>
            {upgradePreview.status === 'clean'
              ? <CheckCircleFilled/>
              : <ExclamationCircleFilled/>}
            <div>
              <strong>{t(upgradeStatusLabel[upgradePreview.status])}</strong>
              <p>{t('从 v{{v0}} 升级到 v{{v1}}', {
                v0: upgradePreview.from_version,
                v1: upgradePreview.to_version,
              })}</p>
            </div>
          </div>
          <div className="sa-upgrade-scenarios">
            {upgradePreview.scenarios.map(item => <div className={`sa-upgrade-scenario ${item.status}`} key={item.scenario_key}>
              <span>{item.status === 'clean' ? <CheckCircleFilled/> : <ExclamationCircleFilled/>}</span>
              <div>
                <strong>{item.scenario_key}</strong>
                <small>{t(upgradeStatusLabel[item.status])}</small>
                {!!item.conflicts.length && <ul>
                  {item.conflicts.map((conflict, index) => <li key={`${conflict.path}-${index}`}>
                    {conflict.path || t('整体配置')}
                  </li>)}
                </ul>}
              </div>
            </div>)}
          </div>
          {!!conflictPaths(upgradePreview).length && <div className="sa-upgrade-conflicts">
            <h4>{t('冲突路径')}</h4>
            <ul>
              {conflictPaths(upgradePreview).map(path => <li key={path}>{path}</li>)}
            </ul>
          </div>}
          <p className="sa-upgrade-note">
            {upgradePreview.status === 'clean'
              ? t('合并结果无冲突；应用后只更新草稿，不会自动发布。')
              : t('检测到冲突或阻断项，当前安装不会被修改。请先处理本地配置差异。')}
          </p>
        </>}
      </div>}
    </Modal>
  </div>;
}

function IndustryMetric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <article>
    <span>{label}</span>
    <strong>{value}</strong>
    <small>{hint}</small>
  </article>;
}

function IndustryEmpty({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className="sa-industry-empty">
    {icon}
    <strong>{title}</strong>
    <p>{detail}</p>
  </div>;
}

