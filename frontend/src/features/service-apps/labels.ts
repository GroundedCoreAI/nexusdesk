import { t } from '../../i18n/index';

/**
 * Service-app copy is routed through one helper while the shared dictionaries
 * are owned by the i18n workstream. New v2 terms can be added there without
 * touching every page component.
 */
export function say(key: string, options?: Record<string, unknown>) {
    return t(key, options);
}

export function statusLabel(status: string) {
    if (status === 'draft') return say('草稿');
    if (status === 'review') return say('待发布');
    if (status === 'published') return say('已发布');
    if (status === 'offline') return say('已下线');
    return status;
}

export function skillTypeLabel(type: string) {
    if (type === 'knowledge') return say('知识检索');
    if (type === 'query') return say('业务查询');
    if (type === 'action') return say('业务办理');
    if (type === 'handoff') return say('转人工');
    return type;
}

export function connectionKindLabel(kind: string) {
    if (kind === 'http') return 'HTTP';
    if (kind === 'internal') return say('平台内置');
    if (kind === 'human_queue') return say('人工队列');
    return kind;
}

export function authKindLabel(kind: string) {
    if (kind === 'none') return say('未认证');
    if (kind === 'bearer') return 'Bearer';
    if (kind === 'api_key') return 'API Key';
    if (kind === 'custom') return say('自定义');
    return kind;
}
