import type { ThemeConfig } from 'antd'

// Central palette so every page restyles consistently from one place instead
// of ad-hoc hex codes scattered across components. Semantic accents (source
// node amber, unconfigured-edge warning, open-edge gray) stay separate from
// colorPrimary on purpose -- they mean something specific on the topology
// canvas and shouldn't drift if the brand color ever changes.
export const palette = {
  primary: '#2E56F2',
  sidebarBg: '#0F1A2E',
  sidebarBorder: 'rgba(255,255,255,0.08)',
  layoutBg: '#F4F6FB',
  sourceAccent: '#F59E0B',
  sourceBg: '#FFFBEB',
  warningAccent: '#FA541C',
  mutedEdge: '#BFBFBF',
}

export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: palette.primary,
    colorLink: palette.primary,
    borderRadius: 8,
    colorBgLayout: palette.layoutBg,
  },
  components: {
    Menu: {
      darkItemBg: palette.sidebarBg,
      darkSubMenuItemBg: palette.sidebarBg,
    },
    Layout: {
      siderBg: palette.sidebarBg,
      bodyBg: palette.layoutBg,
    },
  },
}
