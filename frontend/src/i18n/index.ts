import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhCN from './locales/zh-CN.json';
import zhTW from './locales/zh-TW.json';
import en from './locales/en.json';
import hi from './locales/hi.json';

export type Locale = 'zh-CN' | 'zh-TW' | 'en' | 'hi';
export const LOCALE_KEY = 'agent-platform-language';
export function resolveLocale(value: string): Locale | null {
  if (/^zh-(TW|HK|MO|Hant)(-|$)/i.test(value)) return 'zh-TW';
  if (/^zh($|-)/i.test(value)) return 'zh-CN';
  if (/^en($|-)/i.test(value)) return 'en';
  if (/^hi($|-)/i.test(value)) return 'hi';
  return null;
}
export function detectBrowserLocale(): Locale {
  const browserLanguages = [...(navigator.languages ?? []), navigator.language].filter(Boolean);
  return browserLanguages.map(resolveLocale).find((value): value is Locale => value !== null) ?? 'zh-CN';
}
function initialLocale(): Locale {
  try { const saved=localStorage.getItem(LOCALE_KEY); if(saved && ['zh-CN','zh-TW','en','hi'].includes(saved)) return saved as Locale; } catch { /* Storage can be disabled. */ }
  return detectBrowserLocale();
}
void i18n.use(initReactI18next).init({
  lng:initialLocale(), fallbackLng:'zh-CN', supportedLngs:['zh-CN','zh-TW','en','hi'],
  resources:{'zh-CN':{translation:zhCN},'zh-TW':{translation:zhTW},en:{translation:en},hi:{translation:hi}},
  keySeparator:false, nsSeparator:false, initAsync:false,
  interpolation:{escapeValue:false}, react:{useSuspense:false},
});
export function t(key:string, options?:Record<string,unknown>):string {return i18n.t(key, options) as string;}
export function locale():Locale {return i18n.language as Locale;}
export function changeLanguage(value:Locale) {void i18n.changeLanguage(value);}
function updateDocument() {
  document.documentElement.lang=locale();document.title='nexusdesk · '+t('智能客服平台');
}
i18n.on('languageChanged',()=>{try{localStorage.setItem(LOCALE_KEY,locale());}catch{/* Preference remains for this session. */}updateDocument();});
updateDocument();
export const number=(value:number,options?:Intl.NumberFormatOptions)=>new Intl.NumberFormat(locale(),options).format(value);
export function dateTime(value:string) { const date=new Date(value); return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(locale(),{dateStyle:'medium',timeStyle:'medium',hour12:false}).format(date); }
/**
 * A strict-schema rejection arrives as `422 · <JSON array of {loc,msg,type}>`.
 * Flattening that to one generic sentence hid *which* field failed and implied
 * every 422 was a missing required field, which is simply not true (extra
 * inputs, enum mismatches and cross-field value errors are 422s too).
 * These helpers recover the contract paths and translate the framework text,
 * while leaving any unrecognised server message verbatim for bug reports.
 */
const VALIDATION_MESSAGE_KEYS:Record<string,string>={
  'Field required':'此项为必填',
  'String should have at least 1 character':'不能为空',
  'Input should be a valid integer':'需要填写整数',
  'Input should be a valid number':'需要填写数字',
  'Input should be a valid string':'需要填写文本',
  'Input should be a valid boolean':'需要填写布尔值',
  'Input should be a valid UUID':'需要填写有效的 UUID',
  'Extra inputs are not permitted':'不支持此字段，请删除',
  'Value error, legacy React fields are only valid for the react engine':'当前 Engine 不支持旧版 React 字段，请清除模型方案或切回 React Engine',
  'Value error, react configuration is only valid for the react engine':'当前 Engine 不支持旧版 React 字段，请清除模型方案或切回 React Engine',
};
const VALIDATION_MESSAGE_PATTERNS:Array<[RegExp,string]>=[
  [/^String should have at most (\d+) characters?$/,'文本长度不能超过 {{v0}} 个字符'],
  [/^String should have at least (\d+) characters?$/,'文本长度至少 {{v0}} 个字符'],
  [/^Input should be greater than or equal to (-?\d+(?:\.\d+)?)$/,'数值不能小于 {{v0}}'],
  [/^Input should be less than or equal to (-?\d+(?:\.\d+)?)$/,'数值不能大于 {{v0}}'],
  [/^Input should be '[^']*'(?:, '[^']*')*(?: or '[^']*')?$/,'取值必须是允许值之一'],
  [/^Input should be (?:a valid|an instance of)/,'取值格式不正确'],
];
function localizeValidationMessage(msg:string):string {
  const exact=VALIDATION_MESSAGE_KEYS[msg];
  if(exact&&i18n.exists(exact))return t(exact);
  for(const [pattern,key] of VALIDATION_MESSAGE_PATTERNS){
    const match=pattern.exec(msg);
    // `v0` is only meaningful for the numeric/length families; the enum and
    // generic families take no placeholder, and i18next ignores the extra one.
    if(match&&i18n.exists(key))return t(key,{v0:match[1]});
  }
  return msg;
}
/** Field-level, localised lines for a structured 422; empty for any other body. */
export function validationFieldErrors(message:string):string[] {
  const raw=/^422 · ([\s\S]*)$/.exec(message||'')?.[1];
  if(!raw)return [];
  let parsed:unknown;
  try{parsed=JSON.parse(raw);}catch{return [];}
  if(!Array.isArray(parsed))return [];
  return parsed.flatMap(item=>{
    const location=(item as {loc?:unknown}).loc;
    if(!Array.isArray(location))return [];
    const path=location.filter(segment=>typeof segment==='string'&&segment!=='body'&&segment!=='config').join('.');
    if(!path)return [];
    return [t('字段 {{v0}}：{{v1}}',{v0:path,v1:localizeValidationMessage(String((item as {msg?:unknown}).msg??''))})];
  });
}
export function errorText(message:string) {
  const code=message.match(/^(?:\d{3} · )?([a-z][a-z0-9_]+)$/)?.[1];
  const known:Record<string,string>={
    tool_host_not_allowed:"服务地址不在服务器允许的主机列表中，请检查地址或联系管理员。",
    tool_revision_conflict_or_archived:"配置已修改或归档，请刷新后重试。",
    tool_revision_conflict_or_disabled:"配置已修改或停用，请刷新并检查启用状态。",
    invalid_tool_configuration:"工具配置无效，请检查地址、请求头和参数格式。",
    tool_name_exists:"调用标识已存在，请使用其他标识。",
    published_tools_archive_instead:"已有发布历史，请使用归档保留历史记录。",
    tool_has_agent_references:"仍有 Agent 引用，请先移除引用。",
    duplicate_paths_cannot_export_openapi:"存在重复接口路径，请调整后再导出 OpenAPI。",
    invalid_openapi_document:"OpenAPI 文档无效或超出解析限制，请检查文件。",

    tool_credential_reentry_required:'接口地址或鉴权请求头已改变，请重新输入密钥后保存。',
    tool_credential_key_unavailable:'无法读取密钥加密文件，请检查服务端密钥库配置。',
    agent_model_required:'请先选择已发布的 Chat 配置方案；没有可选方案时，请前往模型网关配置并发布。',
    model_not_configured:'尚未配置对话模型，请在模型网关发布 Chat 配置方案并绑定到 Agent。',
    agent_not_found:'该智能体已不存在，请关闭弹窗并刷新列表。',
    agent_archived:'此 Agent 已归档，请返回列表恢复后编辑。',
    agent_not_published:'请先保存并发布 Agent',
    database_unavailable:'无法连接后端或读取权限：',
    agent_missing_or_revision_conflict:'智能体已被修改或恢复，请关闭弹窗并刷新列表后重新操作。',
    // Phase 3 execution domain errors (03-technical-design.md §7.3). The code is
    // the contract; the sentence below only explains it and stays free of any
    // internal snapshot, probe or policy detail.
    execution_phase3_disabled:'Phase 3 执行能力尚未启用，无法预览。',
    execution_engine_unavailable:'所选 Engine 未注册或已停用，无法预览或发布。',
    execution_configuration_invalid:'执行配置不合法，请检查标记的字段。',
    execution_policy_unavailable:'能力策略源暂不可用，请稍后重试。',
    agent_revision_conflict:'智能体已被修改或恢复，请关闭弹窗并刷新列表后重新操作。',
    draft_revision_conflict:'智能体已被修改或恢复，请关闭弹窗并刷新列表后重新操作。',
    model_resource_disabled:'模型方案不可用，请检查模型网关配置',
    model_resource_not_found:'模型方案不可用，请检查模型网关配置',
    profile_version_not_found:'模型方案不可用，请检查模型网关配置',
    ticket_revision_conflict:'工单已被修改，请加载最新版本后重试',
    forbidden:'当前角色没有执行此操作的权限',
    unauthorized:'访问凭据无效，请重新配置',
    judge_demo_profile:'Judge 方案是演示模型，无法返回评分 JSON，请改选真实 Chat 方案。',
    judge_response_not_json:'Judge 模型没有返回 JSON，请更换支持结构化输出的 Chat 方案。',
    judge_response_invalid:'Judge 返回的 JSON 不符合评分结构，请重试或更换方案。',
    judge_tool_calls_forbidden:'Judge 方案开启了工具调用，评分不允许调用工具。',
    insufficient_permission:t('当前角色没有执行此操作的权限'),
    member_not_found:t('成员不存在或已被删除。'),
    member_revision_conflict:t('成员信息已更新，请刷新后重试。'),
    last_admin_protected:t('不能停用或降级最后一名管理员。'),
    cannot_modify_self:t('不能修改自己的角色或启停状态。'),
    local_username_exists:t('登录账号已存在，请更换。'),
    invalid_local_username:t('登录账号格式不正确。'),
    local_credential_not_configured:t('该成员没有本地登录账号，无法重置密码。'),
    independent_admin_protected:t('应急管理员受保护，不能修改角色、停用或关联企业身份。'),
    cannot_reset_own_password:t('请通过账户安全修改自己的密码。'),
    member_session_not_found:t('会话不存在或已失效。'),
    identity_session_required:t('当前凭据不支持成员会话管理。'),
  };
  if(code)return `${t(known[code]||'请求失败，请重试或联系管理员')} (${message})`;
  if(/^422 ·/.test(message)){
    const fields=validationFieldErrors(message);
    // Structured rejections name the exact field and the reason. Only a 422
    // whose body is not a pydantic detail list falls back to the old sentence.
    return fields.length?`${t('请检查以下字段的必填项与输入格式')}\n${fields.join('\n')}`:`${t('请检查必填项和输入格式')} (422)`;
  }
  return i18n.exists(message)?t(message):message;
}
export default i18n;
