import { ref } from 'vue'

export type WorkbenchTheme = 'glass' | 'paper' | 'white'

export const workbenchThemeOptions = [
  { id: 'white', title: '纯白（默认）', shortTitle: '纯白', description: '纯白画布配冷灰侧栏与高对比黑色操作，参考 Codex 与 Antigravity 配色' },
  { id: 'glass', title: 'Liquid Glass', shortTitle: 'Liquid Glass', description: '导航、卡片与浮层使用玻璃材质，列表与输入保持实体' },
  { id: 'paper', title: '纸墨', shortTitle: '纸墨', description: '实体表面，信息密度高，适合长时间使用' },
] as const

const themeOrder: readonly WorkbenchTheme[] = ['white', 'paper', 'glass']
const key = 'studiolo:workbench-theme'

function storedTheme(): WorkbenchTheme {
  try {
    const saved = localStorage.getItem(key)
    return saved === 'paper' || saved === 'white' || saved === 'glass' ? saved : 'white'
  } catch {
    return 'white'
  }
}

export function workbenchThemeLabel(id: WorkbenchTheme | string): string {
  return workbenchThemeOptions.find(item => item.id === id)?.shortTitle ?? '纯白'
}

export function nextWorkbenchTheme(current: WorkbenchTheme): WorkbenchTheme {
  const index = themeOrder.indexOf(current)
  return themeOrder[(index + 1) % themeOrder.length] ?? 'white'
}

const theme = ref<WorkbenchTheme>(storedTheme())

export function useWorkbenchTheme() {
  function setTheme(value: WorkbenchTheme) {
    theme.value = value
    try { localStorage.setItem(key, value) } catch { /* Keep the in-session choice. */ }
  }

  return { theme, setTheme }
}
