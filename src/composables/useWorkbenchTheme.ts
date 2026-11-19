import { computed, ref } from 'vue'
import {
  DEFAULT_THEME_ID,
  THEME_LIST,
  getThemeDefinition,
  type ThemeId,
} from '../theme/registry'

export type WorkbenchTheme = ThemeId
export type ChatBubbleStyle = 'minimal' | 'claude' | 'lobe' | 'antd' | 'timeline'

export const workbenchThemeOptions = THEME_LIST

export const chatBubbleStyleOptions = [
  { id: 'minimal', title: '极简无框（默认）', shortTitle: '极简无框', badge: 'assistant-ui', description: 'Agent 回复无外框无底色像原生文档，用户为柔和浅灰胶囊' },
  { id: 'claude', title: '温润描边', shortTitle: '温润描边', badge: 'Claude', description: '用户气泡采用 1px 细描边柔光胶囊，思考与工具带温润左竖线' },
  { id: 'lobe', title: '现代轻卡片', shortTitle: '轻卡片', badge: 'LobeChat', description: '双方保留对称 14px 圆角轻卡片，层次分明无厚重阴影' },
  { id: 'antd', title: '结构化边框', shortTitle: '结构边框', badge: 'Ant Design X', description: '双方采用 1px 细描边结构化卡片，工具与正文分区清晰' },
  { id: 'timeline', title: '时间轴工作流', shortTitle: '时间轴', badge: 'Cursor', description: '用户为全宽指令条，Agent 沿左侧连续时间轴线串联展开' },
] as const

const themeOrder: readonly WorkbenchTheme[] = ['white', 'paper', 'glass']
const bubbleOrder: readonly ChatBubbleStyle[] = ['minimal', 'claude', 'lobe', 'antd', 'timeline']
const key = 'studiolo:workbench-theme'
const bubbleKey = 'studiolo:chat-bubble-style'
const reducedTransparencyKey = 'studiolo:reduced-transparency'

function readStoredThemeRaw(): string {
  try {
    return localStorage.getItem(key) ?? DEFAULT_THEME_ID
  } catch {
    return DEFAULT_THEME_ID
  }
}

function readStoredBubbleStyle(): ChatBubbleStyle {
  try {
    const saved = localStorage.getItem(bubbleKey) as ChatBubbleStyle | null
    return saved && bubbleOrder.includes(saved) ? saved : 'minimal'
  } catch {
    return 'minimal'
  }
}

function readStoredReducedTransparency(): boolean {
  try {
    const saved = localStorage.getItem(reducedTransparencyKey)
    if (saved !== null) return saved === 'true'
  } catch {
    // 忽略存储受限
  }
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    return window.matchMedia('(prefers-reduced-transparency: reduce)').matches
  }
  return false
}

export function workbenchThemeLabel(id: WorkbenchTheme | string): string {
  return getThemeDefinition(id).definition.shortTitle
}

export function chatBubbleStyleLabel(id: ChatBubbleStyle | string): string {
  return chatBubbleStyleOptions.find(item => item.id === id)?.shortTitle ?? '极简无框'
}

export function nextWorkbenchTheme(current: WorkbenchTheme): WorkbenchTheme {
  const index = themeOrder.indexOf(current)
  return themeOrder[(index + 1) % themeOrder.length] ?? DEFAULT_THEME_ID
}

// 保留原始 themeId（允许未来版本的主题 ID 在回退到默认主题渲染时不丢失本地存储值）
const rawThemeId = ref<string>(readStoredThemeRaw())
const theme = computed<WorkbenchTheme>(() => getThemeDefinition(rawThemeId.value).resolvedId)
const bubbleStyle = ref<ChatBubbleStyle>(readStoredBubbleStyle())
const reducedTransparency = ref<boolean>(readStoredReducedTransparency())

export function useWorkbenchTheme() {
  function setTheme(value: WorkbenchTheme) {
    rawThemeId.value = value
    try { localStorage.setItem(key, value) } catch { /* 保持当次会话选择 */ }
  }

  function setBubbleStyle(value: ChatBubbleStyle) {
    bubbleStyle.value = value
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.bubbleStyle = value
    }
    try { localStorage.setItem(bubbleKey, value) } catch { /* 保持当次会话选择 */ }
  }

  function setReducedTransparency(value: boolean) {
    reducedTransparency.value = value
    try { localStorage.setItem(reducedTransparencyKey, String(value)) } catch { /* 保持当次会话选择 */ }
  }

  return {
    theme,
    rawThemeId,
    setTheme,
    bubbleStyle,
    setBubbleStyle,
    reducedTransparency,
    setReducedTransparency,
  }
}
