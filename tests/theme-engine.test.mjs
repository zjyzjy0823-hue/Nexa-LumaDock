import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_THEME_ID,
  THEME_LIST,
  THEME_REGISTRY,
  contrastRatio,
  getThemeDefinition,
  resolveColorMode,
  resolveThemeState,
} from '../src/theme/registry.ts'

test('Theme Registry 完整登记 white/paper/glass，未知 themeId 安全回退默认主题并保留原值', () => {
  assert.equal(DEFAULT_THEME_ID, 'white')
  assert.deepEqual(
    THEME_LIST.map(t => t.id),
    ['white', 'paper', 'glass'],
  )

  const unknown = getThemeDefinition('future-oled-v2')
  assert.equal(unknown.resolvedId, 'white')
  assert.equal(unknown.requestedId, 'future-oled-v2')
  assert.equal(unknown.fellBack, true)

  // Liquid Glass 仅在 nav/card/overlay/popover 启用材质，长列表与输入区强制实体
  assert.equal(THEME_REGISTRY.glass.supportsMaterial, true)
  assert.ok(THEME_REGISTRY.glass.solidRoles.includes('list'))
  assert.ok(THEME_REGISTRY.glass.solidRoles.includes('input'))
  assert.ok(THEME_REGISTRY.glass.solidRoles.includes('prose'))
})

test('Sync v3 旧 appearance.theme 与主偏好 theme 严格兼容映射', () => {
  assert.equal(resolveColorMode({ appearanceTheme: 'dark', primaryTheme: 'light', systemPrefersDark: false }), 'dark')
  assert.equal(resolveColorMode({ appearanceTheme: 'light', primaryTheme: 'dark', systemPrefersDark: true }), 'light')
  assert.equal(resolveColorMode({ appearanceTheme: 'auto', primaryTheme: 'light', systemPrefersDark: true }), 'dark')
  assert.equal(resolveColorMode({ appearanceTheme: null, primaryTheme: 'dark', systemPrefersDark: false }), 'dark')
  assert.equal(resolveColorMode({ appearanceTheme: null, primaryTheme: 'system', systemPrefersDark: true }), 'dark')
})

test('Liquid Glass 在不支持 backdrop-filter、减少透明或低性能模式下自动降级为实体无模糊表面', () => {
  const activeGlass = resolveThemeState({
    requestedThemeId: 'glass',
    appearanceTheme: 'light',
    systemPrefersDark: false,
    blurPx: 24,
    transparencyPercent: 70,
    supportsBackdropFilter: true,
    reducedTransparency: false,
    lowPowerMode: false,
  })
  assert.equal(activeGlass.materialActive, true)
  assert.equal(activeGlass.degraded, false)
  assert.equal(activeGlass.effectiveBlurPx, 24)
  assert.equal(activeGlass.dataset.material, 'glass')

  const degradedNoBackdrop = resolveThemeState({
    requestedThemeId: 'glass',
    appearanceTheme: 'light',
    systemPrefersDark: false,
    blurPx: 24,
    supportsBackdropFilter: false,
  })
  assert.equal(degradedNoBackdrop.materialActive, false)
  assert.equal(degradedNoBackdrop.degraded, true)
  assert.equal(degradedNoBackdrop.effectiveBlurPx, 0)
  assert.equal(degradedNoBackdrop.effectiveOpacity, 1)
  assert.equal(degradedNoBackdrop.dataset.material, 'solid')

  const degradedReducedTransparency = resolveThemeState({
    requestedThemeId: 'glass',
    appearanceTheme: 'dark',
    systemPrefersDark: true,
    blurPx: 20,
    reducedTransparency: true,
  })
  assert.equal(degradedReducedTransparency.materialActive, false)
  assert.equal(degradedReducedTransparency.degraded, true)
  assert.equal(degradedReducedTransparency.dataset.reducedTransparency, 'on')
})

test('三套主题在浅色与深色模式下主文字与辅助文字对比度均满足 WCAG AA (>= 4.5:1)', () => {
  for (const def of THEME_LIST) {
    for (const mode of ['light', 'dark']) {
      const p = def.palette[mode]
      assert.ok(
        contrastRatio(p.text, p.solid) >= 4.5,
        `${def.id}/${mode} 正文对比度不足: ${contrastRatio(p.text, p.solid)}`,
      )
      assert.ok(
        contrastRatio(p.text, p.bg) >= 4.5,
        `${def.id}/${mode} 画布正文对比度不足: ${contrastRatio(p.text, p.bg)}`,
      )
      assert.ok(
        contrastRatio(p.mutedText, p.solid) >= 4.5,
        `${def.id}/${mode} 辅助文字对比度不足: ${contrastRatio(p.mutedText, p.solid)}`,
      )
      assert.ok(
        contrastRatio(p.accentInk, p.accent) >= 4.5,
        `${def.id}/${mode} 强调按钮对比度不足: ${contrastRatio(p.accentInk, p.accent)}`,
      )
    }
  }
})
