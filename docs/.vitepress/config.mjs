import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: 'Mneme',
  description: 'Local-document RAG with Graph RAG — Named after Mnemosyne, the Greek goddess of memory',

  // Base URL for GitHub Pages user site (root)
  base: '/',

  // Enable clean URLs (no .html suffix)
  cleanUrls: true,

  // Last updated timestamp
  lastUpdated: true,

  // Markdown settings
  markdown: {
    lineNumbers: true,
  },

  // Internationalization
  locales: {
    root: {
      label: 'English',
      lang: 'en',
      link: '/',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/' },
          { text: 'Guide', link: '/guide/getting-started' },
          { text: 'Features', link: '/features/hybrid-retrieval' },
          { text: 'Blog', link: '/blog/mneme-rag-engineering' },
          { text: 'Reference', link: '/reference/configuration' },
        ],
        sidebar: {
          '/guide/': [
            {
              text: 'Guide',
              items: [
                { text: 'Getting Started', link: '/guide/getting-started' },
                { text: 'Configuration', link: '/guide/configuration' },
                { text: 'TUI Commands', link: '/guide/tui-commands' },
              ],
            },
          ],
          '/features/': [
            {
              text: 'Features',
              items: [
                { text: 'Hybrid Retrieval', link: '/features/hybrid-retrieval' },
                { text: 'Graph RAG', link: '/features/graph-rag' },
                { text: 'Query Decomposition', link: '/features/query-decomposition' },
                { text: 'Safety', link: '/features/safety' },
              ],
            },
          ],
          '/blog/': [
            {
              text: 'Blog',
              items: [
                { text: 'RAG Engineering (EN)', link: '/blog/mneme-rag-engineering' },
                { text: 'RAG Engineering (中文)', link: '/blog/mneme-rag-engineering-zh' },
              ],
            },
          ],
          '/reference/': [
            {
              text: 'Reference',
              items: [
                { text: 'Configuration', link: '/reference/configuration' },
                { text: 'Supported Files', link: '/reference/supported-files' },
                { text: 'Changelog', link: '/reference/changelog' },
              ],
            },
          ],
        },
        editLink: {
          pattern: 'https://github.com/realhenrylan/mneme/edit/main/docs/:path',
          text: 'Edit this page on GitHub',
        },
        docFooter: {
          prev: 'Previous page',
          next: 'Next page',
        },
        outline: {
          label: 'On this page',
        },
        lastUpdated: {
          text: 'Updated at',
        },
      },
    },
    zh: {
      label: '简体中文',
      lang: 'zh-CN',
      link: '/zh/',
      themeConfig: {
        nav: [
          { text: '首页', link: '/zh/' },
          { text: '指南', link: '/zh/guide/getting-started' },
          { text: '功能', link: '/zh/features/hybrid-retrieval' },
          { text: '博客', link: '/zh/blog/mneme-rag-engineering' },
          { text: '参考', link: '/zh/reference/configuration' },
        ],
        sidebar: {
          '/zh/guide/': [
            {
              text: '指南',
              items: [
                { text: '快速开始', link: '/zh/guide/getting-started' },
                { text: '配置', link: '/zh/guide/configuration' },
                { text: 'TUI 命令', link: '/zh/guide/tui-commands' },
              ],
            },
          ],
          '/zh/features/': [
            {
              text: '功能',
              items: [
                { text: '混合检索', link: '/zh/features/hybrid-retrieval' },
                { text: 'Graph RAG', link: '/zh/features/graph-rag' },
                { text: '查询拆解', link: '/zh/features/query-decomposition' },
                { text: '安全设计', link: '/zh/features/safety' },
              ],
            },
          ],
          '/zh/blog/': [
            {
              text: '博客',
              items: [
                { text: 'RAG 工程实践 (中文)', link: '/zh/blog/mneme-rag-engineering-zh' },
                { text: 'RAG Engineering (EN)', link: '/zh/blog/mneme-rag-engineering' },
              ],
            },
          ],
          '/zh/reference/': [
            {
              text: '参考',
              items: [
                { text: '配置参考', link: '/zh/reference/configuration' },
                { text: '支持的文件类型', link: '/zh/reference/supported-files' },
                { text: '更新日志', link: '/zh/reference/changelog' },
              ],
            },
          ],
        },
        editLink: {
          pattern: 'https://github.com/realhenrylan/mneme/edit/main/docs/:path',
          text: '在 GitHub 上编辑此页',
        },
        docFooter: {
          prev: '上一页',
          next: '下一页',
        },
        outline: {
          label: '本页目录',
        },
        lastUpdated: {
          text: '最后更新于',
        },
      },
    },
  },

  // Theme configuration (shared across locales)
  themeConfig: {
    logo: '/mneme-logo.svg',
    siteTitle: false,

    socialLinks: [
      { icon: 'github', link: 'https://github.com/realhenrylan/mneme' },
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 Henry Lan',
    },

    search: {
      provider: 'local',
      options: {
        locales: {
          zh: {
            translations: {
              button: {
                buttonText: '搜索',
                buttonAriaLabel: '搜索',
              },
              modal: {
                noResultsText: '无法找到相关结果',
                resetButtonTitle: '清除查询条件',
                footer: {
                  selectText: '选择',
                  navigateText: '切换',
                  closeText: '关闭',
                },
              },
            },
          },
        },
      },
    },
  },

  // Head tags
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/mneme-logo.svg' }],
    ['meta', { name: 'theme-color', content: '#a78bfa' }],
  ],
})
