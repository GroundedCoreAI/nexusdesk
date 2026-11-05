// Navigation manifest — the single place that decides what the site shows.
//
// Every entry names a source file under the repository `docs/` directory. The
// doc-sync script validates that each source exists, maps it into `.build/`
// for the Chinese locale and into `.build/en/` for English, and the VitePress
// config builds nav/sidebar from this same list.
//
// Anything not listed here never reaches the published site. That is
// deliberate: `docs/requirement/` holds internal planning and review material
// and must stay off the public site, so the allowlist is explicit rather than
// "include everything under docs/".

export const REPO = 'GroundedCoreAI/nexusdesk';
export const BRANCH = 'integration';

export const groups = [
  {
    key: 'getting-started',
    zh: '入门',
    en: 'Getting started',
    pages: [
      {
        slug: 'getting-started/quickstart',
        source: 'docs/getting-started/quickstart.md',
        zh: '快速开始',
        en: 'Quickstart',
      },
    ],
  },
  {
    key: 'guides',
    zh: '使用指南',
    en: 'User guide',
    pages: [
      { slug: 'guides/platform', source: 'docs/guides/platform.md', zh: '平台使用', en: 'Platform guide' },
      {
        slug: 'guides/knowledge-workspace',
        source: 'docs/guides/knowledge-workspace.md',
        zh: '知识库工作台',
        en: 'Knowledge workspace',
      },
      {
        slug: 'guides/industry-examples',
        source: 'docs/guides/industry-examples.md',
        zh: '行业案例',
        en: 'Industry examples',
      },
      { slug: 'guides/open-platform', source: 'docs/guides/open-platform.md', zh: '开放平台', en: 'Open platform' },
      {
        slug: 'guides/open-platform-identity',
        source: 'docs/guides/open-platform-identity.md',
        zh: '开放平台身份',
        en: 'Open platform identity',
      },
      { slug: 'guides/access-control', source: 'docs/guides/access-control.md', zh: '访问控制', en: 'Access control' },
      {
        slug: 'guides/model-gateway-governance',
        source: 'docs/guides/model-gateway-governance.md',
        zh: '模型网关治理',
        en: 'Model gateway governance',
      },
    ],
  },
  {
    key: 'architecture',
    zh: '架构',
    en: 'Architecture',
    pages: [
      { slug: 'architecture/overview', source: 'docs/architecture/overview.md', zh: '架构总览', en: 'Architecture overview' },
      { slug: 'architecture/runtime', source: 'docs/architecture/runtime.md', zh: 'Agent Runtime', en: 'Agent Runtime' },
      {
        slug: 'architecture/streaming-design',
        source: 'docs/architecture/streaming-design.md',
        zh: '流式输出设计',
        en: 'Streaming design',
      },
      {
        slug: 'architecture/agent-execution-platform-v2',
        source: 'docs/architecture/agent-execution-platform-v2.md',
        zh: 'Agent 执行平台 v2',
        en: 'Agent execution platform v2',
      },
    ],
  },
  {
    key: 'operations',
    zh: '部署与运维',
    en: 'Deployment & operations',
    pages: [
      { slug: 'operations/middleware', source: 'docs/operations/middleware.md', zh: '中间件说明', en: 'Middleware' },
      {
        slug: 'operations/database-migrations',
        source: 'docs/operations/database-migrations.md',
        zh: '数据库迁移',
        en: 'Database migrations',
      },
      { slug: 'operations/local-admin', source: 'docs/operations/local-admin.md', zh: '本地管理员', en: 'Local admin' },
    ],
  },
  {
    key: 'reference',
    zh: '参考',
    en: 'Reference',
    pages: [{ slug: 'reference/api', source: 'docs/reference/api.md', zh: 'API 说明', en: 'API reference' }],
  },
  {
    key: 'development',
    zh: '开发者指南',
    en: 'Developer guide',
    pages: [
      {
        slug: 'development/local-development',
        source: 'docs/development/local-development.md',
        zh: '本地开发',
        en: 'Local development',
      },
      {
        slug: 'development/module-development',
        source: 'docs/development/module-development.md',
        zh: '模块开发',
        en: 'Module development',
      },
      {
        slug: 'development/internationalization',
        source: 'docs/development/internationalization.md',
        zh: '国际化',
        en: 'Internationalization',
      },
      {
        slug: 'development/ui-design-system',
        source: 'docs/development/ui-design-system.md',
        zh: 'UI 设计系统',
        en: 'UI design system',
      },
    ],
  },
];

export const allPages = groups.flatMap((group) => group.pages);
