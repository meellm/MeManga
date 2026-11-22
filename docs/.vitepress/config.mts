import { defineConfig } from 'vitepress'

const repo = 'https://github.com/meellm/MeManga'

export default defineConfig({
  lang: 'en-US',
  title: 'MeManga',
  description:
    'Documentation for MeManga, a desktop app and command-line tool that tracks manga series and downloads new chapters.',

  // Served as a GitHub Pages project site.
  base: '/MeManga/',
  cleanUrls: true,

  // These documents are still read on GitHub and linked from the app and the
  // package metadata. They stay where they are until their content has been
  // moved into the site.
  srcExclude: [
    // The index of this folder for people reading it on GitHub.
    'README.md',
    'Guide.md',
    'SUPPORTED_SOURCES.md',
    'ACCESSIBILITY.md',
    // Generated; shown as part of reference/cli.md, reference/config.md,
    // reference/sources.md and reference/supported-websites.md.
    'reference/cli-commands.md',
    'reference/config-keys.md',
    'reference/source-list.md',
    'reference/supported-websites-list.md'
  ],

  themeConfig: {
    nav: [
      { text: 'Docs', link: '/guide/', activeMatch: '^/guide/$' },
      { text: 'Install', link: '/guide/install' },
      { text: 'Desktop app', link: '/desktop/library', activeMatch: '^/desktop/' },
      { text: 'Releases', link: `${repo}/releases` },
      { text: 'Changelog', link: `${repo}/blob/main/CHANGELOG.md` }
    ],

    sidebar: [
      {
        text: 'Getting started',
        items: [
          { text: 'Docs overview', link: '/guide/' },
          { text: 'Download and install', link: '/guide/install' },
          { text: 'First steps', link: '/guide/first-steps' },
          { text: 'Supported websites', link: '/reference/supported-websites' }
        ]
      },
      {
        text: 'Desktop app',
        items: [
          { text: 'Library and downloads', link: '/desktop/library' },
          { text: 'Reader', link: '/desktop/reader' },
          { text: 'Keyboard', link: '/desktop/keyboard' },
          { text: 'Settings', link: '/desktop/settings' }
        ]
      },
      {
        text: 'Command line',
        items: [
          { text: 'Use the command line', link: '/guide/cli' },
          { text: 'Command reference', link: '/reference/cli' },
          { text: 'Use MeManga in scripts', link: '/reference/scripting' }
        ]
      },
      {
        text: 'How-to guides',
        items: [
          { text: 'Use a backup source', link: '/guide/backup-sources' },
          { text: 'Check on a schedule', link: '/guide/schedule' },
          { text: 'Send chapters to a Kindle', link: '/guide/kindle' },
          { text: 'Run a command after each download', link: '/guide/post-processing' },
          { text: 'Run MeManga in Docker', link: '/guide/docker' },
          { text: 'Troubleshooting', link: '/guide/troubleshooting' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'Settings reference', link: '/reference/config' },
          { text: 'Data files and backups', link: '/reference/state' },
          { text: 'Sources', link: '/reference/sources' },
          { text: 'Network connections', link: '/reference/network' },
          { text: 'Python API', link: '/reference/python-api' }
        ]
      },
      {
        text: 'Developers',
        items: [
          { text: 'Set up for development', link: '/developer/contributing' },
          { text: 'Architecture', link: '/developer/architecture' },
          { text: 'Write a scraper', link: '/developer/scrapers' },
          { text: 'Build and release', link: '/developer/build-release' }
        ]
      }
    ],

    socialLinks: [{ icon: 'github', link: repo }],

    search: { provider: 'local' },

    footer: {
      message: 'Released under the MIT License.'
    }
  }
})
