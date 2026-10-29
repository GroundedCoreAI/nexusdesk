import { useEffect, useState } from 'react';
import {
    disableCapability,
    enableCapability,
    retryCapability,
    rollbackCapabilityConfig,
    saveCapabilityConfig,
    type CapabilityConfigPage,
    type CapabilityConfigVersion,
    type CapabilityObservability,
    type CapabilityStatusItem,
} from '../../shared/api/client';
import { Alert, Badge, Empty, Panel, useAccess, useAction, useResource, time } from '../../shared/components/ui';
import { t } from '../../i18n/index';

function capabilityLabel(id: string) {
    return {
        approval: t('审批'),
        'customer-service': t('客户服务'),
        knowledge: t('知识库'),
        memory: t('客户记忆'),
    }[id] || id;
}

function configText(config: CapabilityConfigVersion | null) {
    return config ? JSON.stringify(config.config, null, 2) : '{}';
}

export function ExtensionsPage() {
    const { admin } = useAccess();
    const status = useResource<CapabilityObservability>('/extensions/capabilities', 5000);
    const [selectedId, setSelectedId] = useState('');
    const selected = status.data?.capabilities.items.find(item => item.capability_id === selectedId) || null;
    const config = useResource<CapabilityConfigVersion>(
        selected?.config_version ? `/extensions/capabilities/${selectedId}/config` : null,
    );
    const versions = useResource<CapabilityConfigPage>(
        selectedId ? `/extensions/capabilities/${selectedId}/config/versions` : null,
    );
    const [draft, setDraft] = useState('{}');
    const action = useAction();

    useEffect(() => {
        if (config.data) setDraft(configText(config.data));
        else if (!config.loading && selectedId) setDraft('{}');
    }, [config.data, config.loading, selectedId]);

    if (!admin) {
        return <Panel title={t('插件平台')}><Empty>{t('仅管理员可管理插件')}</Empty></Panel>;
    }

    async function toggleCapability(item: CapabilityStatusItem) {
        await action.run(async () => {
            if (item.enabled) await disableCapability(item.capability_id);
            else await enableCapability(item.capability_id);
            status.refresh();
        }, item.enabled ? t('插件已停用') : t('插件已启用'));
    }

    async function recoverCapability(item: CapabilityStatusItem) {
        await action.run(async () => {
            await retryCapability(item.capability_id);
            status.refresh();
        }, t('插件已恢复'));
    }

    async function saveConfig() {
        await action.run(async () => {
            const value: unknown = JSON.parse(draft);
            if (!value || typeof value !== 'object' || Array.isArray(value)) {
                throw new Error(t('配置必须是 JSON 对象'));
            }
            await saveCapabilityConfig(selectedId, value as Record<string, unknown>);
            config.refresh();
            versions.refresh();
            status.refresh();
        }, t('插件配置已保存'));
    }

    async function rollback(version: number) {
        await action.run(async () => {
            await rollbackCapabilityConfig(selectedId, version);
            config.refresh();
            versions.refresh();
            status.refresh();
        }, t('插件配置已回滚'));
    }

    return <div className="extensions-page">
        <Alert error={action.error || status.error || config.error || versions.error} notice={action.notice} />
        <Panel title={t('插件平台')} action={<span className="hint">{t('状态自动刷新')}</span>}>
            <p className="hint">{t('插件配置在平台范围生效，修改和回滚都会留下审计记录。')}</p>
            <table>
                <thead><tr>
                    <th>{t('插件')}</th><th>{t('版本')}</th><th>{t('状态')}</th>
                    <th>{t('配置版本')}</th><th>{t('操作')}</th>
                </tr></thead>
                <tbody>{status.data?.capabilities.items.map(item => <tr key={item.capability_id}>
                    <td><button className="text-button" onClick={() => setSelectedId(item.capability_id)}>{capabilityLabel(item.capability_id)}</button><br /><span className="mono muted">{item.capability_id}</span></td>
                    <td><span className="mono">{item.version}</span></td>
                    <td><Badge value={item.status}/></td>
                    <td>{item.config_version ?? '—'}</td>
                    <td>{item.status === 'degraded'
                        ? <button onClick={() => void recoverCapability(item)} disabled={action.busy}>{t('重试')}</button>
                        : <button onClick={() => void toggleCapability(item)} disabled={action.busy}>{item.enabled ? t('停用') : t('启用')}</button>}</td>
                </tr>)}</tbody>
            </table>
        </Panel>
        {selected && <div className="split">
            <Panel title={`${capabilityLabel(selected.capability_id)} · ${t('运行配置')}`}>
                <p className="hint">{t('当前版本')}: <span className="mono">{selected.config_version ?? t('尚未配置')}</span></p>
                <textarea
                    aria-label={t('插件配置 JSON')}
                    rows={16}
                    value={draft}
                    onChange={event => setDraft(event.target.value)}
                    spellCheck={false}
                />
                <div className="row-actions">
                    <button onClick={() => void saveConfig()} disabled={action.busy}>{t('保存配置')}</button>
                    <button onClick={() => setDraft(configText(config.data))} disabled={action.busy}>{t('重置')}</button>
                </div>
            </Panel>
            <Panel title={t('配置版本历史')}>
                {versions.data?.items.length ? <table>
                    <thead><tr><th>{t('版本')}</th><th>{t('操作者')}</th><th>{t('时间')}</th><th>{t('来源')}</th><th>{t('操作')}</th></tr></thead>
                    <tbody>{[...(versions.data.items)].reverse().map(version => <tr key={version.version}>
                        <td className="mono">{version.version}</td>
                        <td>{version.created_by}</td>
                        <td>{time(version.created_at)}</td>
                        <td>{version.rollback_of ? `${t('回滚自')} ${version.rollback_of}` : t('直接发布')}</td>
                        <td><button onClick={() => void rollback(version.version)} disabled={action.busy || version.version === selected.config_version}>{t('回滚')}</button></td>
                    </tr>)}</tbody>
                </table> : <Empty>{t('暂无配置版本')}</Empty>}
            </Panel>
        </div>}
    </div>;
}
