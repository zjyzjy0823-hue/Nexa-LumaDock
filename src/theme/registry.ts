/**
 * Studiolo Theme Engine 注册表与统一解析器（桌面 / 手机 Web / 后续 Android 共用）。
 *
 * 设计原则：
 * 1. 严格向后兼容 Sync v3 `appearance` 既有字段（light/dark/auto、blur、transparency、accent、background），
 *    新 `themeId` 留在设备侧而不向旧 v3 严格契约注入未知字段。
 * 2. 未知 `themeId` 安全回退至默认主题 `white`，同时保留原始 `requestedThemeId` 供未来版本识别。
 * 3. 当平台不支持 backdrop-filter、开启 reducedTransparency 或低性能模式时，自动将 Liquid Glass 降级为高对比实体表面。
 */

export type ThemeId = 'white' | 'paper' | 'glass'
export type ColorMode = 'light' | 'dark'
export type LegacyAppearanceTheme = 'light' | 'dark' | 'auto'
export type LegacyPrimaryTheme = 'light' | 'dark' | 'system'
export type SurfaceRole = 'nav' | 'card' | 'overlay' | 'popover' | 'list' | 'input' | 'prose'

export interface ThemePaletteSample {
  bg: string
  solid: string
  text: string
  mutedText: string
  accent: string
  accentInk: string
}

export interface ThemeDefinition {
  id: ThemeId
  version: 1
  title: string
  shortTitle: string
  description: string
  supportsMaterial: boolean
  /** 仅允许在指定 surface role 上启用玻璃材质；list / input / prose 始终保持实体高对比 */
  materialRoles: readonly SurfaceRole[]
  solidRoles: readonly SurfaceRole[]
  themeColor: Record<ColorMode, string>
  palette: Record<ColorMode, ThemePaletteSample>
}

export const DEFAULT_THEME_ID: ThemeId = 'white'

export const THEME_REGISTRY: Readonly<Record<ThemeId, ThemeDefinition>> = Object.freeze({
  white: {
    id: 'white',
    version: 1,
    title: '纯白（默认）',
    shortTitle: '纯白',
    description: '纯白画布配冷灰侧栏与高对比黑色操作，清晰克制',
    supportsMaterial: false,
    materialRoles: [],
    solidRoles: ['nav', 'card', 'overlay', 'popover', 'list', 'input', 'prose'],
    themeColor: { light: '#fdfdfe', dark: '#0d1117' },
    palette: {
      light: {
        bg: '#fdfdfe',
        solid: '#ffffff',
        text: '#111827',
        mutedText: '#4b5563',
        accent: '#111827',
        accentInk: '#ffffff',
      },
      dark: {
        bg: '#0d1117',
        solid: '#161b22',
        text: '#f3f4f6',
        mutedText: '#9ca3af',
        accent: '#e5e7eb',
        accentInk: '#0d1117',
      },
    },
  },
  paper: {
    id: 'paper',
    version: 1,
    title: '纸墨',
    shortTitle: '纸墨',
    description: '温润纸感实体表面，信息密度高，适合长时间专注阅读',
    supportsMaterial: false,
    materialRoles: [],
    solidRoles: ['nav', 'card', 'overlay', 'popover', 'list', 'input', 'prose'],
    themeColor: { light: '#f3f2ee', dark: '#151412' },
    palette: {
      light: {
        bg: '#f3f2ee',
        solid: '#fbfaf7',
        text: '#1c1917',
        mutedText: '#57534e',
        accent: '#292524',
        accentInk: '#fafaf9',
      },
      dark: {
        bg: '#151412',
        solid: '#1f1d1a',
        text: '#f5f5f4',
        mutedText: '#a8a29e',
        accent: '#e7e5e4',
        accentInk: '#151412',
      },
    },
  },
  glass: {
    id: 'glass',
    version: 1,
    title: 'Liquid Glass',
    shortTitle: 'Liquid Glass',
    description: '导航、状态卡与浮层使用可选玻璃材质，长列表与输入区始终保持高对比实体表面',
    supportsMaterial: true,
    materialRoles: ['nav', 'card', 'overlay', 'popover'],
    solidRoles: ['list', 'input', 'prose'],
    themeColor: { light: '#eef2ff', dark: '#0d1022' },
    palette: {
      light: {
        bg: '#eef2ff',
        solid: '#ffffff',
        text: '#0f172a',
        mutedText: '#475569',
        accent: '#2563eb',
        accentInk: '#ffffff',
      },
      dark: {
        bg: '#0d1022',
        solid: '#151a30',
        text: '#f8fafc',
        mutedText: '#94a3b8',
        accent: '#60a5fa',
        accentInk: '#0b1120',
      },
    },
  },
})

export const THEME_LIST: readonly ThemeDefinition[] = Object.freeze([
  THEME_REGISTRY.white,
  THEME_REGISTRY.paper,
  THEME_REGISTRY.glass,
])

export function isRegisteredThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(THEME_REGISTRY, value)
}

export function getThemeDefinition(requestedThemeId: unknown): {
  definition: ThemeDefinition
  resolvedId: ThemeId
  requestedId: string
  fellBack: boolean
} {
  if (isRegisteredThemeId(requestedThemeId)) {
    return {
      definition: THEME_REGISTRY[requestedThemeId],
      resolvedId: requestedThemeId,
      requestedId: requestedThemeId,
      fellBack: false,
    }
  }
  const requested = typeof requestedThemeId === 'string' && requestedThemeId.trim() ? requestedThemeId.trim() : DEFAULT_THEME_ID
  return {
    definition: THEME_REGISTRY[DEFAULT_THEME_ID],
    resolvedId: DEFAULT_THEME_ID,
    requestedId: requested,
    fellBack: requested !== DEFAULT_THEME_ID,
  }
}

/** 兼容映射旧 Sync v3 `appearance.theme` 与主偏好 `theme`，不引入非法枚举。 */
export function resolveColorMode(input: {
  appearanceTheme?: LegacyAppearanceTheme | string | null
  primaryTheme?: LegacyPrimaryTheme | string | null
  systemPrefersDark: boolean
}): ColorMode {
  if (input.appearanceTheme === 'light' || input.appearanceTheme === 'dark') {
    return input.appearanceTheme
  }
  if (input.appearanceTheme === 'auto') {
    return input.systemPrefersDark ? 'dark' : 'light'
  }
  if (input.primaryTheme === 'light' || input.primaryTheme === 'dark') {
    return input.primaryTheme
  }
  return input.systemPrefersDark ? 'dark' : 'light'
}

export interface ThemeResolveInput {
  requestedThemeId: string
  appearanceTheme?: LegacyAppearanceTheme | string | null
  primaryTheme?: LegacyPrimaryTheme | string | null
  systemPrefersDark: boolean
  blurPx?: number
  transparencyPercent?: number
  reducedMotion?: boolean
  reducedTransparency?: boolean
  lowPowerMode?: boolean
  supportsBackdropFilter?: boolean
  bubbleStyle?: string
}

export interface ResolvedThemeState {
  requestedThemeId: string
  themeId: ThemeId
  fellBack: boolean
  colorMode: ColorMode
  materialActive: boolean
  degraded: boolean
  effectiveBlurPx: number
  effectiveOpacity: number
  reducedMotion: boolean
  reducedTransparency: boolean
  themeColor: string
  dataset: Record<string, string>
  cssVars: Record<string, string>
}

export function resolveThemeState(input: ThemeResolveInput): ResolvedThemeState {
  const { definition, resolvedId, requestedId, fellBack } = getThemeDefinition(input.requestedThemeId)
  const colorMode = resolveColorMode({
    appearanceTheme: input.appearanceTheme,
    primaryTheme: input.primaryTheme,
    systemPrefersDark: input.systemPrefersDark,
  })

  const rawBlur = typeof input.blurPx === 'number' && Number.isFinite(input.blurPx)
    ? Math.max(0, Math.min(32, Math.round(input.blurPx)))
    : 26
  const rawTransparency = typeof input.transparencyPercent === 'number' && Number.isFinite(input.transparencyPercent)
    ? Math.max(20, Math.min(95, Math.round(input.transparencyPercent)))
    : 72

  const reducedMotion = Boolean(input.reducedMotion)
  const reducedTransparency = Boolean(input.reducedTransparency)
  const lowPowerMode = Boolean(input.lowPowerMode)
  const supportsBackdrop = input.supportsBackdropFilter ?? true

  const materialRequested = definition.supportsMaterial && rawBlur > 0
  const degraded = materialRequested && (reducedTransparency || lowPowerMode || !supportsBackdrop)
  const materialActive = materialRequested && !degraded
  const effectiveBlurPx = materialActive ? rawBlur : 0
  const effectiveOpacity = materialActive ? Number((rawTransparency / 100).toFixed(2)) : 1

  const dataset: Record<string, string> = {
    theme: resolvedId,
    workbenchTheme: resolvedId,
    mode: colorMode,
    workbenchMode: colorMode,
    blur: materialActive ? 'on' : 'off',
    workbenchBlur: materialActive ? 'on' : 'off',
    material: materialActive ? 'glass' : 'solid',
    reducedTransparency: reducedTransparency || degraded ? 'on' : 'off',
    motion: reducedMotion ? 'reduced' : 'full',
  }
  if (input.bubbleStyle) {
    dataset.bubbleStyle = input.bubbleStyle
  }

  const cssVars: Record<string, string> = {
    '--workbench-blur': `${effectiveBlurPx}px`,
    '--studiolo-surface-opacity': String(effectiveOpacity),
    '--studiolo-theme-version': String(definition.version),
  }

  return {
    requestedThemeId: requestedId,
    themeId: resolvedId,
    fellBack,
    colorMode,
    materialActive,
    degraded,
    effectiveBlurPx,
    effectiveOpacity,
    reducedMotion,
    reducedTransparency: reducedTransparency || degraded,
    themeColor: definition.themeColor[colorMode],
    dataset,
    cssVars,
  }
}

export function applyThemeToRoot(root: HTMLElement, state: ResolvedThemeState): void {
  for (const [k, v] of Object.entries(state.dataset)) {
    root.dataset[k] = v
  }
  for (const [prop, value] of Object.entries(state.cssVars)) {
    root.style.setProperty(prop, value)
  }
}

/** 计算两种 #RRGGBB 色彩的 WCAG 2.1 对比度比值，用于验收 ≥ 4.5:1。 */
export function contrastRatio(hexA: string, hexB: string): number {
  const lum = (hex: string) => {
    const clean = hex.replace('#', '')
    const r = parseInt(clean.slice(0, 2), 16) / 255
    const g = parseInt(clean.slice(2, 4), 16) / 255
    const b = parseInt(clean.slice(4, 6), 16) / 255
    const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
  }
  const l1 = lum(hexA)
  const l2 = lum(hexB)
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return Number(((lighter + 0.05) / (darker + 0.05)).toFixed(2))
}
