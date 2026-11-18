/**
 * 纯 TypeScript 轻量 Markdown AST 解析器（零 innerHTML / v-html，彻底免疫 XSS，并兼容流式未闭合代码块）。
 */

export type MarkdownInline =
  | { type: 'text'; text: string }
  | { type: 'bold'; text: string }
  | { type: 'italic'; text: string }
  | { type: 'strike'; text: string }
  | { type: 'code'; text: string }
  | { type: 'link'; text: string; href: string }

export type MarkdownBlock =
  | { type: 'heading'; level: 1 | 2 | 3 | 4; inlines: MarkdownInline[] }
  | { type: 'paragraph'; lines: MarkdownInline[][] }
  | { type: 'code'; lang: string; code: string; streamingOpen?: boolean }
  | { type: 'blockquote'; lines: MarkdownInline[][] }
  | { type: 'list'; ordered: boolean; items: MarkdownInline[][] }
  | { type: 'table'; headers: MarkdownInline[][]; rows: MarkdownInline[][][] }
  | { type: 'hr' }

/**
 * 严格校检外链协议，仅放行 http / https / mailto，拒绝 javascript: / data: 等危险 URI。
 */
export function isSafeMarkdownHref(rawUrl: string): string | null {
  const trimmed = rawUrl.trim()
  if (!trimmed) return null
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:' || parsed.protocol === 'mailto:') {
      return parsed.href
    }
  } catch {
    return null
  }
  return null
}

const INLINE_PATTERN =
  /(`[^`]+`)|(\[([^\]]+)\]\(([^)\s]+)\))|(\*\*([^*]+)\*\*)|(__([^_]+)__)|(~~([^~]+)~~)|(\*([^*]+)\*)|(https?:\/\/[^\s<>()]+)/g

export function parseMarkdownInlines(text: string): MarkdownInline[] {
  if (!text) return []
  const out: MarkdownInline[] = []
  let lastIdx = 0
  INLINE_PATTERN.lastIndex = 0

  let match: RegExpExecArray | null
  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > lastIdx) {
      out.push({ type: 'text', text: text.slice(lastIdx, match.index) })
    }
    if (match[1]) {
      out.push({ type: 'code', text: match[1].slice(1, -1) })
    } else if (match[2]) {
      const safe = isSafeMarkdownHref(match[4])
      if (safe) out.push({ type: 'link', text: match[3], href: safe })
      else out.push({ type: 'text', text: match[0] })
    } else if (match[5]) {
      out.push({ type: 'bold', text: match[6] })
    } else if (match[7]) {
      out.push({ type: 'bold', text: match[8] })
    } else if (match[9]) {
      out.push({ type: 'strike', text: match[10] })
    } else if (match[11]) {
      out.push({ type: 'italic', text: match[12] })
    } else if (match[13]) {
      let url = match[13]
      let tail = ''
      while (/[.,;:!?)]$/.test(url)) {
        tail = url.slice(-1) + tail
        url = url.slice(0, -1)
      }
      const safe = isSafeMarkdownHref(url)
      if (safe) out.push({ type: 'link', text: url, href: safe })
      else out.push({ type: 'text', text: url })
      if (tail) out.push({ type: 'text', text: tail })
    }
    lastIdx = INLINE_PATTERN.lastIndex
  }
  if (lastIdx < text.length) {
    out.push({ type: 'text', text: text.slice(lastIdx) })
  }
  return out
}

function splitTableCells(row: string): string[] {
  const clean = row.trim().replace(/^\|/, '').replace(/\|$/, '')
  return clean.split('|').map(cell => cell.trim())
}

function isTableDivider(line: string): boolean {
  const trimmed = line.trim()
  if (!trimmed.includes('|') || !trimmed.includes('-')) return false
  const cells = splitTableCells(trimmed)
  return cells.length > 0 && cells.every(c => /^:?-{2,}:?$/.test(c))
}

function isBlockStart(lines: string[], idx: number): boolean {
  const line = lines[idx] ?? ''
  const trimmed = line.trim()
  if (!trimmed) return true
  if (/^(```|~~~)/.test(trimmed)) return true
  if (/^#{1,4}\s+/.test(trimmed)) return true
  if (/^>\s?/.test(trimmed)) return true
  if (/^([-*_])\1{2,}$/.test(trimmed)) return true
  if (/^[-*+]\s+/.test(trimmed)) return true
  if (/^\d+\.\s+/.test(trimmed)) return true
  if (trimmed.includes('|') && idx + 1 < lines.length && isTableDivider(lines[idx + 1])) return true
  return false
}

export function parseMarkdownBlocks(rawText: string): MarkdownBlock[] {
  const normalized = rawText.replace(/\r\n?/g, '\n')
  if (!normalized.trim()) return []
  const lines = normalized.split('\n')
  const blocks: MarkdownBlock[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    // 1. 围栏代码块（支持流式输出期间尚未闭合的尾块）
    const fenceMatch = trimmed.match(/^(```|~~~)\s*([^\s`~]*)/)
    if (fenceMatch) {
      const marker = fenceMatch[1]
      const lang = fenceMatch[2] || ''
      const codeLines: string[] = []
      i += 1
      let closed = false
      while (i < lines.length) {
        if (lines[i].trim().startsWith(marker) && lines[i].trim().slice(marker.length).trim() === '') {
          closed = true
          i += 1
          break
        }
        codeLines.push(lines[i])
        i += 1
      }
      blocks.push({
        type: 'code',
        lang,
        code: codeLines.join('\n'),
        streamingOpen: !closed,
      })
      continue
    }

    // 2. 分割线
    if (/^([-*_])\1{2,}$/.test(trimmed)) {
      blocks.push({ type: 'hr' })
      i += 1
      continue
    }

    // 3. 标题（H1-H4）
    const headMatch = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (headMatch) {
      blocks.push({
        type: 'heading',
        level: headMatch[1].length as 1 | 2 | 3 | 4,
        inlines: parseMarkdownInlines(headMatch[2]),
      })
      i += 1
      continue
    }

    // 4. 表格（含表头分割行）
    if (trimmed.includes('|') && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      const headers = splitTableCells(trimmed).map(parseMarkdownInlines)
      i += 2
      const rows: MarkdownInline[][][] = []
      while (i < lines.length && lines[i].trim().includes('|') && lines[i].trim()) {
        const cells = splitTableCells(lines[i]).slice(0, headers.length)
        while (cells.length < headers.length) cells.push('')
        rows.push(cells.map(parseMarkdownInlines))
        i += 1
      }
      blocks.push({ type: 'table', headers, rows })
      continue
    }

    // 5. 引用块
    if (/^>\s?/.test(trimmed)) {
      const quoteLines: MarkdownInline[][] = []
      while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
        quoteLines.push(parseMarkdownInlines(lines[i].trim().replace(/^>\s?/, '')))
        i += 1
      }
      blocks.push({ type: 'blockquote', lines: quoteLines })
      continue
    }

    // 6. 有序 / 无序列表
    const ulMatch = trimmed.match(/^[-*+]\s+(.+)$/)
    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/)
    if (ulMatch || olMatch) {
      const ordered = Boolean(olMatch)
      const pattern = ordered ? /^\d+\.\s+(.+)$/ : /^[-*+]\s+(.+)$/
      const items: MarkdownInline[][] = []
      while (i < lines.length) {
        const itemMatch = lines[i].trim().match(pattern)
        if (!itemMatch) break
        items.push(parseMarkdownInlines(itemMatch[1]))
        i += 1
      }
      blocks.push({ type: 'list', ordered, items })
      continue
    }

    // 7. 普通段落（合并连续非空普通文本行，保留单行换行）
    const paraLines: MarkdownInline[][] = []
    while (i < lines.length && !isBlockStart(lines, i)) {
      paraLines.push(parseMarkdownInlines(lines[i]))
      i += 1
    }
    if (paraLines.length) {
      blocks.push({ type: 'paragraph', lines: paraLines })
    } else {
      paraLines.push(parseMarkdownInlines(line))
      blocks.push({ type: 'paragraph', lines: paraLines })
      i += 1
    }
  }

  return blocks
}
