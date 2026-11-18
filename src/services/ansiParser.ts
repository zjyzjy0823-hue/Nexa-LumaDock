/**
 * ANSI SGR 终端转义序列解析器：将 ESC[...m 输出转换为安全的样式化文本片段，
 * 同时剥离非 SGR 控制序列以保持工具执行输出可读性。
 */

export interface AnsiSpan {
  text: string
  fg?: string
  bg?: string
  bold?: boolean
  dim?: boolean
  italic?: boolean
  underline?: boolean
}

const FG_STANDARD: Record<number, string> = {
  30: '#334155',
  31: '#dc2626',
  32: '#16a34a',
  33: '#ca8a04',
  34: '#2563eb',
  35: '#9333ea',
  36: '#0891b2',
  37: '#e2e8f0',
  90: '#64748b',
  91: '#f87171',
  92: '#4ade80',
  93: '#facc15',
  94: '#60a5fa',
  95: '#c084fc',
  96: '#22d3ee',
  97: '#ffffff',
}

const BG_STANDARD: Record<number, string> = {
  40: '#0f172a',
  41: '#7f1d1d',
  42: '#14532d',
  43: '#713f12',
  44: '#1e3a8a',
  45: '#581c87',
  46: '#164e63',
  47: '#e2e8f0',
  100: '#334155',
  101: '#b91c1c',
  102: '#15803d',
  103: '#a16207',
  104: '#1d4ed8',
  105: '#7e22ce',
  106: '#0e7490',
  107: '#f8fafc',
}

function ansi256ToHex(code: number): string | undefined {
  if (!Number.isFinite(code) || code < 0 || code > 255) return undefined
  if (code < 8) return FG_STANDARD[30 + code]
  if (code < 16) return FG_STANDARD[90 + (code - 8)]
  if (code < 232) {
    const idx = code - 16
    const r = Math.floor(idx / 36)
    const g = Math.floor((idx % 36) / 6)
    const b = idx % 6
    const scale = (v: number) => (v === 0 ? 0 : 55 + v * 40)
    return `rgb(${scale(r)}, ${scale(g)}, ${scale(b)})`
  }
  const gray = 8 + (code - 232) * 10
  return `rgb(${gray}, ${gray}, ${gray})`
}

interface AnsiStyleState {
  fg?: string
  bg?: string
  bold: boolean
  dim: boolean
  italic: boolean
  underline: boolean
}

function applySgrCodes(state: AnsiStyleState, paramsRaw: string): void {
  const parts = paramsRaw
    ? paramsRaw.split(';').map((s) => (s === '' ? 0 : Number.parseInt(s, 10)))
    : [0]

  let i = 0
  while (i < parts.length) {
    const c = Number.isNaN(parts[i]) ? 0 : parts[i]
    if (c === 0) {
      state.fg = undefined
      state.bg = undefined
      state.bold = false
      state.dim = false
      state.italic = false
      state.underline = false
    } else if (c === 1) {
      state.bold = true
    } else if (c === 2) {
      state.dim = true
    } else if (c === 3) {
      state.italic = true
    } else if (c === 4) {
      state.underline = true
    } else if (c === 22) {
      state.bold = false
      state.dim = false
    } else if (c === 23) {
      state.italic = false
    } else if (c === 24) {
      state.underline = false
    } else if (c === 39) {
      state.fg = undefined
    } else if (c === 49) {
      state.bg = undefined
    } else if (FG_STANDARD[c]) {
      state.fg = FG_STANDARD[c]
    } else if (BG_STANDARD[c]) {
      state.bg = BG_STANDARD[c]
    } else if ((c === 38 || c === 48) && i + 1 < parts.length) {
      const mode = parts[i + 1]
      const isFg = c === 38
      if (mode === 5 && i + 2 < parts.length) {
        const hex = ansi256ToHex(parts[i + 2])
        if (isFg) state.fg = hex
        else state.bg = hex
        i += 2
      } else if (mode === 2 && i + 4 < parts.length) {
        const r = Math.max(0, Math.min(255, parts[i + 2] || 0))
        const g = Math.max(0, Math.min(255, parts[i + 3] || 0))
        const b = Math.max(0, Math.min(255, parts[i + 4] || 0))
        const color = `rgb(${r}, ${g}, ${b})`
        if (isFg) state.fg = color
        else state.bg = color
        i += 4
      }
    }
    i++
  }
}

/** 快速检测字符串中是否包含 ANSI SGR 转义序列。 */
export function hasAnsiSequences(text: string): boolean {
  return /[\u001b\u009b]\[[0-9;?]*[A-Za-z]/.test(text)
}

/** 解析包含 ANSI 转义序列的文本为可声明式渲染的 Span 数组。 */
export function parseAnsiText(input: string): AnsiSpan[] {
  const src = String(input ?? '')
  if (!src) return []

  const spans: AnsiSpan[] = []
  const state: AnsiStyleState = {
    bold: false,
    dim: false,
    italic: false,
    underline: false,
  }

  // eslint-disable-next-line no-control-regex
  const re = /\u001b\[([0-9;?]*)([A-Za-z])|\u009b([0-9;?]*)([A-Za-z])/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  const emitChunk = (chunk: string) => {
    if (!chunk) return
    const next: AnsiSpan = {
      text: chunk,
      ...(state.fg ? { fg: state.fg } : {}),
      ...(state.bg ? { bg: state.bg } : {}),
      ...(state.bold ? { bold: true } : {}),
      ...(state.dim ? { dim: true } : {}),
      ...(state.italic ? { italic: true } : {}),
      ...(state.underline ? { underline: true } : {}),
    }
    const prev = spans[spans.length - 1]
    if (
      prev &&
      prev.fg === next.fg &&
      prev.bg === next.bg &&
      Boolean(prev.bold) === Boolean(next.bold) &&
      Boolean(prev.dim) === Boolean(next.dim) &&
      Boolean(prev.italic) === Boolean(next.italic) &&
      Boolean(prev.underline) === Boolean(next.underline)
    ) {
      prev.text += chunk
    } else {
      spans.push(next)
    }
  }

  while ((match = re.exec(src)) !== null) {
    if (match.index > lastIndex) {
      emitChunk(src.slice(lastIndex, match.index))
    }
    const params = match[1] ?? match[3] ?? ''
    const cmd = match[2] ?? match[4] ?? ''
    if (cmd === 'm') {
      applySgrCodes(state, params)
    }
    lastIndex = re.lastIndex
  }

  if (lastIndex < src.length) {
    emitChunk(src.slice(lastIndex))
  }
  return spans
}
