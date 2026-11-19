import { ref } from 'vue'

export type WorkbenchTheme = 'glass' | 'paper' | 'white'
export type ChatBubbleStyle = 'minimal' | 'claude' | 'lobe' | 'antd' | 'timeline'

export const workbenchThemeOptions = [
  { id: 'white', title: '纯白（默认）', shortTitle: '纯白', description: '纯白画布配冷灰侧栏与高对比黑色操作，参考 Codex 与 Antigravity 配色' },
  { id: 'glass', title: 'Liquid Glass', shortTitle: 'Liquid Glass', description: '导航、卡片与浮层使用玻璃材质，列表与输入保持实体' },
  { id: 'paper', title: '纸墨', shortTitle: '纸墨', description: '实体表面，信息密度高，适合长时间使用' },
] as const

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

function storedTheme(): WorkbenchTheme {
  try {
    const saved = localStorage.getItem(key)
    return saved === 'paper' || saved === 'white' || saved === 'glass' ? saved : 'white'
  } catch {
    return 'white'
  }
}

function storedBubbleStyle(): ChatBubbleStyle {
  try {
    const saved = localStorage.getItem(bubbleKey) as ChatBubbleStyle | null
    return saved && bubbleOrder.includes(saved) ? saved : 'minimal'
  } catch {
    return 'minimal'
  }
}

export function workbenchThemeLabel(id: WorkbenchTheme | string): string {
  return workbenchThemeOptions.find(item => item.id === id)?.shortTitle ?? '纯白'
}

export function chatBubbleStyleLabel(id: ChatBubbleStyle | string): string {
  return chatBubbleStyleOptions.find(item => item.id === id)?.shortTitle ?? '极简无框'
}

export function nextWorkbenchTheme(current: WorkbenchTheme): WorkbenchTheme {
  const index = themeOrder.indexOf(current)
  return themeOrder[(index + 1) % themeOrder.length] ?? 'white'
}

const theme = ref<WorkbenchTheme>(storedTheme())
const bubbleStyle = ref<ChatBubbleStyle>(storedBubbleStyle())

export function useWorkbenchTheme() {
  function setTheme(value: WorkbenchTheme) {
    theme.value = value
    try { localStorage.setItem(key, value) } catch { /* Keep the in-session choice. */ }
  }

  function setBubbleStyle(value: ChatBubbleStyle) {
    bubbleStyle.value = value
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.bubbleStyle = value
    }
    try { localStorage.setItem(bubbleKey, value) } catch { /* Keep the in-session choice. */ }
  }

  return { theme, setTheme, bubbleStyle, setBubbleStyle }
}
