import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitepress'

import { BRANCH, REPO, groups } from '../nav.mjs'

// The site is published as a GitHub Pages *project* site, so every asset URL
// needs the repository base path. The workflow injects it from
// actions/configure-pages, which keeps this working if the repository or the
// custom domain changes; the fallback only matters for local builds.
const base = process.env.DOCS_BASE || '/nexusdesk/'
const githubUrl = `https://github.com/${REPO}`
const sidebarSections = groups.map((group) => group.key)

const prefix = (locale: string, slug: string) => `${locale === 'en' ? '/en' : ''}/${slug}`

function nav(locale: 'zh' | 'en') {
  return [
    ...groups.map((group) => ({
      text: locale === 'en' ? group.en : group.zh,
      link: prefix(locale, group.pages[0].slug),
    })),
    { text: 'GitHub', link: githubUrl },
  ]
}

function sidebar(locale: 'zh' | 'en') {
  // Pages are an explicit allowlist in `nav.mjs`; a page may nest child pages
  // (for example 业务场景 → 智能客服 → 推荐问题设计取舍) and the sidebar
  // mirrors that shape.
  const pageItem = (page: any): any => ({
    text: locale === 'en' ? page.en : page.zh,
    link: prefix(locale, page.slug),
    ...(page.children?.length ? { items: page.children.map((child: any) => pageItem(child)) } : {}),
  })

  const items = groups.map((group) => ({
    text: locale === 'en' ? group.en : group.zh,
    collapsed: false,
    items: group.pages.map((page) => pageItem(page)),
  }))
  // Keyed by section so the landing page (outside these prefixes) stays clean.
  const keyed: Record<string, typeof items> = {}
  for (const key of sidebarSections) {
    keyed[locale === 'en' ? `/en/${key}/` : `/${key}/`] = items
  }
  return keyed
}

export default defineConfig({
  base,
  srcDir: '.build',
  publicDir: fileURLToPath(new URL('public', import.meta.url)),
  cleanUrls: true,
  lang: 'zh-CN',
  title: 'NexusDesk',
  description: 'NexusDesk 官方文档:部署、使用、架构与扩展开发指南',

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}logo.svg` }],
    ['meta', { name: 'theme-color', content: '#1c74c4' }],
  ],

  locales: {
    root: {
      label: '简体中文',
      lang: 'zh-CN',
      themeConfig: {
        nav: nav('zh'),
        sidebar: sidebar('zh'),
        outline: { level: [2, 3], label: '本页目录' },
        docFooter: { prev: '上一篇', next: '下一篇' },
        lastUpdatedText: '最后更新',
        darkModeSwitchLabel: '外观',
        sidebarMenuLabel: '菜单',
        returnToTopLabel: '返回顶部',
        langMenuLabel: '切换语言',
        search: {
          provider: 'local',
          options: {
            translations: {
              button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
              modal: {
                displayDetails: '显示详细列表',
                resetButtonTitle: '清除查询条件',
                noResultsText: '没有找到相关结果',
                footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
              },
            },
          },
        },
      },
    },
    en: {
      label: 'English',
      lang: 'en',
      link: '/en/',
      themeConfig: {
        nav: nav('en'),
        sidebar: sidebar('en'),
        outline: { level: [2, 3], label: 'On this page' },
        docFooter: { prev: 'Previous', next: 'Next' },
        lastUpdatedText: 'Last updated',
        darkModeSwitchLabel: 'Appearance',
        sidebarMenuLabel: 'Menu',
        returnToTopLabel: 'Return to top',
        langMenuLabel: 'Change language',
        search: { provider: 'local' },
      },
    },
  },

  themeConfig: {
    logo: '/logo.svg', // VitePress prepends base itself
    socialLinks: [{ icon: 'github', link: githubUrl }],
    // Edit links are rendered by a small theme override so the English locale
    // can point at `*.en.md` instead of the Chinese source file.
    editLink: undefined,
    footer: {
      message: 'NexusDesk 采用 Apache License 2.0 许可',
      copyright: 'Copyright © 2026 GroundedCore',
    },
  },

  markdown: {
    image: { lazyLoading: true },
  },

  sitemap: { hostname: 'https://groundedcoreai.github.io' },

  // `docs/requirement/` is internal planning material and must never be served.
  srcExclude: ['requirement/**', 'archive/**'],
})
