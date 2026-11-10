/**
 * Shared pickers for fields that must match a registered resource.
 *
 * Three places reference something by name instead of by id:
 *
 * - a provider executor picks a **gateway tool** (`/tools`), which the bridge
 *   dispatches over HTTP;
 * - an application capability or a scenario handler picks a **tool provider**
 *   (`kind=tool`), whose dotted key is the identity readiness checks against;
 * - a scenario object picks an **object provider** (`kind=object`), whose
 *   `config.executors` decides how facts are fetched.
 *
 * All of them used to be free-text inputs, so a typo could be saved as a broken
 * reference that only fails at conversation time. This module owns the option
 * lists and the pickers so the three stay aligned.
 */

import { useMemo } from 'react';
import { Select, Spin } from 'antd';
import type { ServiceProvider, Tool } from '../../shared/api/client';
import { t } from '../../i18n/index';

/**
 * Only gateway-hosted tools can back a reference field: builtins run in-process,
 * so neither the executor bridge nor an HTTP tool call can dispatch them.
 */
export function executableTool(tool: Tool) {
  return tool.source === 'database' || tool.source === 'configuration';
}

/** Why a listed tool cannot be used right now. Empty string means usable. */
export function toolBlockReason(tool: Tool): 'disabled' | 'unpublished' | '' {
  if (!tool.enabled) return 'disabled';
  if (tool.source === 'database' && !tool.published_version) return 'unpublished';
  return '';
}

export function executableTools(tools?: Tool[] | null): Tool[] {
  return (tools || []).filter(executableTool);
}

export function readyToolNames(items: Tool[]): Set<string> {
  return new Set(items.filter(item => !toolBlockReason(item)).map(item => item.name));
}

export interface ToolOption {
  value: string;
  disabled: boolean;
  search: string;
  label: React.ReactNode;
}

/**
 * Build dropdown options for one field.
 *
 * `current` keeps a previously saved name visible even after it disappeared
 * from the gateway, so opening the form never silently clears a reference the
 * operator cannot see.
 */
export function toolOptions(items: Tool[], current?: string): ToolOption[] {
  const options: ToolOption[] = items.map(item => {
    const block = toolBlockReason(item);
    const description = String(item.spec?.description || '').trim();
    const meta = description || item.display_name || item.relative_path || '';
    return {
      value: item.name,
      disabled: Boolean(block),
      search: [item.name, description, item.display_name || '', item.relative_path || '']
        .join(' ')
        .toLowerCase(),
      label: (
        <span className="sa-tool-option">
          <span className="sa-tool-line">
            <code>{item.name}</code>
            {block && <em>{block === 'unpublished' ? t('未发布') : t('未启用')}</em>}
          </span>
          {meta && <small title={meta}>{meta}</small>}
        </span>
      ),
    };
  });
  const name = (current || '').trim();
  if (name && !options.some(option => option.value === name)) {
    options.push({
      value: name,
      disabled: false,
      search: name.toLowerCase(),
      label: (
        <span className="sa-tool-option">
          <span className="sa-tool-line">
            <code>{name}</code>
            <em>{t('未注册')}</em>
          </span>
        </span>
      ),
    });
  }
  return options;
}

interface ToolSelectProps {
  items: Tool[];
  loading?: boolean;
  value?: string;
  onChange?: (value: string | undefined) => void;
  placeholder?: string;
}

/** Searchable select over the gateway catalog; drop it inside a Form.Item. */
export function ToolSelect({ items, loading, value, onChange, placeholder }: ToolSelectProps) {
  const options = useMemo(() => toolOptions(items, value), [items, value]);
  return (
    <Select
      allowClear
      showSearch
      loading={loading}
      value={value}
      onChange={onChange}
      popupMatchSelectWidth={360}
      popupClassName="sa-tool-dropdown"
      optionLabelProp="value"
      listHeight={320}
      placeholder={placeholder}
      options={options}
      filterOption={(input, option) => String(option?.search || '')
        .includes(input.trim().toLowerCase())}
      notFoundContent={loading ? <Spin size="small"/> : t('没有匹配的工具')}
    />
  );
}

/** How many executor roles a provider declares. Zero means it is still a placeholder. */
export function executorCount(provider: ServiceProvider): number {
  return Object.values((provider.config?.executors || {}) as Record<string, unknown>)
    .filter(Boolean).length;
}

export interface ProviderOption {
  value: string;
  disabled: boolean;
  search: string;
  label: React.ReactNode;
}

/**
 * Build options for a provider reference.
 *
 * Disabled providers are kept visible but not selectable: readiness only counts
 * enabled providers, so picking one silently produces a blocked scene.
 */
export function providerOptions(items: ServiceProvider[], current?: string): ProviderOption[] {
  const options: ProviderOption[] = items.map(item => {
    const executors = executorCount(item);
    return {
      value: item.key,
      disabled: !item.enabled,
      search: [item.key, item.name, item.description]
        .join(' ')
        .toLowerCase(),
      label: (
        <span className="sa-tool-option">
          <span className="sa-tool-line">
            <code>{item.key}</code>
            {!item.enabled && <em>{t('未启用')}</em>}
            {executors > 0
              ? <i className="on">{t('已接入 {{v0}} 个执行器', { v0: executors })}</i>
              : <i>{t('未接入执行器')}</i>}
          </span>
          {item.name && <small title={item.name}>{item.name}</small>}
        </span>
      ),
    };
  });
  const name = (current || '').trim();
  if (name && !options.some(option => option.value === name)) {
    options.push({
      value: name,
      disabled: false,
      search: name.toLowerCase(),
      label: (
        <span className="sa-tool-option">
          <span className="sa-tool-line">
            <code>{name}</code>
            <em>{t('未注册')}</em>
          </span>
        </span>
      ),
    });
  }
  return options;
}

interface ProviderSelectProps {
  items: ServiceProvider[];
  loading?: boolean;
  value?: string;
  onChange?: (value: string | undefined) => void;
  placeholder?: string;
}

/** Searchable select over registered providers; drop it inside a Form.Item. */
export function ProviderSelect({ items, loading, value, onChange, placeholder }: ProviderSelectProps) {
  const options = useMemo(() => providerOptions(items, value), [items, value]);
  return (
    <Select
      allowClear
      showSearch
      loading={loading}
      value={value}
      onChange={onChange}
      popupMatchSelectWidth={380}
      popupClassName="sa-tool-dropdown"
      optionLabelProp="value"
      listHeight={320}
      placeholder={placeholder}
      options={options}
      filterOption={(input, option) => String(option?.search || '')
        .includes(input.trim().toLowerCase())}
      notFoundContent={loading ? <Spin size="small"/> : t('没有匹配的接入能力')}
    />
  );
}
