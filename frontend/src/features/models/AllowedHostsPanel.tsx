import { useCallback, useEffect, useState } from 'react';
import { Popconfirm } from 'antd';
import { t } from '../../i18n/index';
import { api, post } from '../../shared/api/client';
import { Alert, Field, Panel, useAction } from '../../shared/components/ui';

interface ManagedHost {
    host: string;
    created_by: string;
    created_at: string;
}

interface AllowedHosts {
    enabled: boolean;
    deployment: string[];
    managed: ManagedHost[];
}

/**
 * Admin view of the two additive egress lists. The deployment list comes from
 * the environment and is read-only here; the managed list is stored per tenant
 * and every change is audited by the backend.
 */
export function AllowedHostsPanel() {
    const action = useAction();
    const [data, setData] = useState<AllowedHosts | null>(null);
    const [loadError, setLoadError] = useState('');
    const [host, setHost] = useState('');

    const load = useCallback(async () => {
        try {
            setData(await api<AllowedHosts>('/model-gateway/allowed-hosts'));
            setLoadError('');
        }
        catch (error) {
            setLoadError(error instanceof Error ? error.message : String(error));
        }
    }, []);

    useEffect(() => { void load(); }, [load]);

    const add = () => void action.run(async () => {
        await post('/model-gateway/allowed-hosts', { host: host.trim() });
        setHost('');
        await load();
    }, t('白名单已更新'));

    const remove = (value: string) => void action.run(async () => {
        await api(`/model-gateway/allowed-hosts/${encodeURIComponent(value)}`, { method: 'DELETE' });
        await load();
    }, t('白名单已更新'));

    return <Panel title={t('出站主机')}>
    <Alert error={loadError || action.error} notice={action.notice}/>
    {data && <>
      {!data.enabled && <p role="status" className="hint">{t('界面维护未启用，请部署方设置 AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS=true。')}</p>}
      <h3>{t('部署白名单（环境变量维护，只读）')}</h3>
      <div className="gateway-tags">{data.deployment.map(item => <span key={item}>{item}</span>)}</div>
      {data.deployment.includes('*') && <p className="hint">{t('部署白名单已允许全部主机（*）。')}</p>}
      <h3>{t('应用白名单（界面维护）')}</h3>
      {data.managed.length > 0
        ? <div className="table-scroll"><table className="gateway-resource-table"><thead><tr><th>{t('主机')}</th><th>{t('创建人')}</th><th>{t('操作')}</th></tr></thead><tbody>{data.managed.map(row => <tr key={row.host}><td>{row.host}</td><td>{row.created_by}</td><td><Popconfirm title={t('删除该主机？使用它的渠道将无法再保存、检测或调用。')} onConfirm={() => remove(row.host)}><button className="text-button" disabled={!data.enabled || action.busy}>{t('删除')}</button></Popconfirm></td></tr>)}</tbody></table></div>
        : <p className="empty">{t('暂无记录')}</p>}
      <div className="gateway-fields">
        <Field label={t('主机地址')}><input value={host} disabled={!data.enabled} onChange={e => setHost(e.target.value)} placeholder="www.example.com" autoComplete="off"/></Field>
        <p className="hint">{t('仅支持公网 HTTPS 域名，例如 www.example.com。')}</p>
        <div className="actions"><button type="button" disabled={!data.enabled || action.busy || !host.trim()} onClick={add}>{t('添加主机')}</button></div>
      </div>
    </>}
  </Panel>;
}
