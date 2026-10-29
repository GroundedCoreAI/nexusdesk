import { useResource } from '../../shared/components/ui';
import { t } from '../../i18n/index';

interface SampleCapability {
    capability_id: string;
    version: string;
    status: string;
    enabled: boolean;
    failure_count: number;
}

interface SampleCapabilityResponse {
    capabilities: {
        items: SampleCapability[];
    };
}

export function SampleOperationsPage() {
    const resource = useResource<SampleCapabilityResponse>('/extensions/capabilities', 5000);
    const capability = resource.data?.capabilities.items.find(
        item => item.capability_id === 'sample-operations',
    );

    return <section className="module-grid" aria-label={t('示例插件状态')}>
        <article className="module-card">
            <h2>{t('示例插件')}</h2>
            <p>{t('这是一个用于验证外部插件生命周期、工具、事件、策略和 UI 扩展的参考插件。')}</p>
            {resource.error && <p className="error">{resource.error}</p>}
            {capability && <dl>
                <dt>{t('版本')}</dt><dd className="mono">{capability.version}</dd>
                <dt>{t('运行状态')}</dt><dd>{capability.status}</dd>
                <dt>{t('启用状态')}</dt><dd>{capability.enabled ? t('已启用') : t('已停用')}</dd>
                <dt>{t('失败次数')}</dt><dd>{capability.failure_count}</dd>
            </dl>}
            {!resource.loading && !capability && <p className="hint">{t('示例插件尚未注册。')}</p>}
        </article>
    </section>;
}
