import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getSkills,
  getSkill,
  getSkillActivity,
  getSkillMe,
  getSkillOverview,
  getSkillPackage,
  getSkillReadiness,
  getSkillTestRuns,
  getSkillTemplates,
  getSkillVersion,
  getSkillVersions,
  type SkillCatalogQuery,
} from './api';
import {
  type SkillCatalogPage,
  type SkillDependencyOptions,
  type SkillOverview,
  type SkillPackageInfo,
  type SkillPermissions,
  type SkillReadiness,
  type SkillRecord,
  type SkillTemplateCatalog,
  type SkillTestRunPage,
  type SkillVersion,
  type SkillVersionPage,
} from './contracts';

export interface RemoteState<T> {
  data: T | null;
  error: string;
  loading: boolean;
  refresh: () => void;
}

function useRemote<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>, emptyValue: T | null = null): RemoteState<T> {
  const [data, setData] = useState<T | null>(emptyValue);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const loader = useRef(load);
  const empty = useRef(emptyValue);
  loader.current = load;
  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    if (!key) {
      setData(empty.current);
      setError('');
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError('');
    void loader.current(controller.signal)
      .then(value => {
        if (active) setData(value);
      })
      .catch(cause => {
        if (!active || controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [key, revision]);

  return { data, error, loading, refresh };
}

export function useSkillCatalog(query: SkillCatalogQuery, enabled = true): RemoteState<SkillCatalogPage> {
  const key = enabled
    ? `catalog:${query.q ?? ''}:${query.category ?? 'all'}:${query.status ?? 'all'}:${query.risk ?? 'all'}:${query.weight ?? 'all'}:${query.sort ?? 'latest'}:${query.page ?? 1}:${query.page_size ?? 8}`
    : null;
  return useRemote(
    key,
    signal => getSkills({ ...query, q: query.q?.trim() ?? '' }),
    {
      items: [],
      total: 0,
      page: 1,
      page_size: 8,
      status_facets: [],
      category_facets: [],
      risk_facets: [],
      weight_facets: [],
    },
  );
}

export function useSkillOverview(): RemoteState<SkillOverview> {
  return useRemote(
    'skills:overview',
    signal => getSkillOverview(signal),
    {
      stats: {
        total: { value: 0, change: null },
        published: { value: 0, change: null },
        in_use: { value: 0, change: null },
        rating: { value: null, change: null },
      },
      popular: [],
    },
  );
}

export function useSkillDetail(key: string | null): RemoteState<SkillRecord> {
  return useRemote(
    key ? `skill:${key}` : null,
    async signal => getSkill(key as string, signal),
    null,
  );
}

export function useSkillPackage(
  key: string | null,
  revision: number | null,
  enabled = true,
): RemoteState<SkillPackageInfo | null> {
  const packageKey = enabled && key && revision ? `package:${key}:${revision}` : null;
  return useRemote(
    packageKey,
    signal => getSkillPackage(key as string, signal),
    null,
  );
}

export function useSkillTemplates(enabled = true): RemoteState<SkillTemplateCatalog> {
  return useRemote(
    enabled ? 'templates' : null,
    signal => getSkillTemplates(signal),
    { items: [], ai_generation_enabled: null, ai_generation_reason: null },
  );
}

export function useSkillTestRuns(key: string | null, page = 1, pageSize = 20): RemoteState<SkillTestRunPage> {
  return useRemote(
    key ? `test-runs:${key}:${page}:${pageSize}` : null,
    signal => getSkillTestRuns(key as string, page, pageSize, signal),
    { items: [], total: 0, page: 1, page_size: pageSize },
  );
}

export function useSkillReadiness(key: string | null, revision: number | null, enabled = true): RemoteState<SkillReadiness> {
  const readyKey = enabled && key && revision ? `readiness:${key}:${revision}` : null;
  return useRemote(
    readyKey,
    signal => getSkillReadiness(key as string, revision as number, signal),
    { skill_id: '', draft_revision: revision ?? 0, ready: false, checks: [], next_semver: null },
  );
}

export function useSkillVersions(key: string | null, enabled = true): RemoteState<SkillVersionPage> {
  return useRemote(
    enabled && key ? `versions:${key}` : null,
    signal => getSkillVersions(key as string, 1, 50, signal),
    { items: [], total: 0, page: 1, page_size: 50 },
  );
}

export function useSkillVersion(key: string | null, version: number | null): RemoteState<SkillVersion> {
  return useRemote(
    key && version ? `version:${key}:${version}` : null,
    signal => getSkillVersion(key as string, version as number, signal),
    null,
  );
}

export function useSkillDependencyOptions(enabled = true): RemoteState<SkillDependencyOptions> {
  return useRemote(
    enabled ? 'skill-dependency-options' : null,
    signal => getSkillActivity(signal),
    {
      models: [],
      knowledgeBases: [],
      tools: [],
      errors: { models: '', knowledgeBases: '', tools: '' },
    },
  );
}

function derivePermissions(role: string, codes: string[]): SkillPermissions {
  const hasSkillCodes = codes.some(code => code.startsWith('skill.'));
  if (hasSkillCodes) {
    return {
      read: codes.includes('skill.read'),
      manage: codes.includes('skill.manage'),
      test: codes.includes('skill.test'),
      publish: codes.includes('skill.publish'),
      role,
    };
  }
  if (role === 'admin') return { read: true, manage: true, test: true, publish: true, role };
  if (role === 'operator') return { read: true, manage: false, test: true, publish: false, role };
  return { read: true, manage: false, test: false, publish: false, role };
}

export function useSkillPermissions(): RemoteState<SkillPermissions> {
  const me = useRemote(
    'skill-me',
    signal => getSkillMe(signal),
    { role: 'viewer', permissions: [] },
  );
  const role = me.data?.role ?? 'viewer';
  const codes = me.data?.permissions ?? [];
  return {
    data: derivePermissions(role, codes),
    error: me.error,
    loading: me.loading,
    refresh: me.refresh,
  };
}
