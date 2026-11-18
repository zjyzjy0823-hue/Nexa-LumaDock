/**
 * 代码 Diff 解析、Split 并排对比行对齐与工具当步局部 Diff 提取工具（纯前端无副作用）。
 */

export type DiffLineKind = 'ctx' | 'add' | 'del'

export interface DiffLineItem {
  kind: DiffLineKind
  text: string
  oldNo?: number
  newNo?: number
}

export interface DiffHunk {
  index: number
  header: string
  oldStart: number
  oldCount: number
  newStart: number
  newCount: number
  rawPatch: string
  lines: DiffLineItem[]
}

export interface DiffGapSegment {
  id: string
  /** 新文件中缺失区间的起止 1-based 行号（闭区间） */
  startNewLine: number
  endNewLine: number
  /** 将新行号换算为旧行号的偏移（oldNo = newNo + oldDelta） */
  oldDelta: number
}

export interface DiffFilePathMeta {
  fileName: string
  dirName: string
  badge: string
  badgeTone: 'ts' | 'vue' | 'py' | 'js' | 'style' | 'json' | 'doc' | 'sh' | 'plain'
}

export interface SplitDiffRow {
  leftNo?: number
  leftText?: string
  leftKind?: 'ctx' | 'del' | 'empty'
  rightNo?: number
  rightText?: string
  rightKind?: 'ctx' | 'add' | 'empty'
}

const HUNK_HEADER_RE = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/

/** 拆分文件名为名/目录及语言徽章信息，复刻 IDE 评审摘要展示。 */
export function splitDiffPath(fullPath: string): DiffFilePathMeta {
  const normalized = String(fullPath || '').replace(/\\/g, '/')
  const lastSlash = normalized.lastIndexOf('/')
  const fileName = lastSlash >= 0 ? normalized.slice(lastSlash + 1) : normalized
  const dirName = lastSlash > 0 ? normalized.slice(0, lastSlash) : ''
  const ext = fileName.includes('.') ? fileName.slice(fileName.lastIndexOf('.') + 1).toLowerCase() : ''

  if (ext === 'ts' || ext === 'tsx' || ext === 'mts') return { fileName, dirName, badge: 'TS', badgeTone: 'ts' }
  if (ext === 'vue') return { fileName, dirName, badge: 'V', badgeTone: 'vue' }
  if (ext === 'py') return { fileName, dirName, badge: 'PY', badgeTone: 'py' }
  if (ext === 'js' || ext === 'jsx' || ext === 'mjs') return { fileName, dirName, badge: 'JS', badgeTone: 'js' }
  if (ext === 'css' || ext === 'scss' || ext === 'less') return { fileName, dirName, badge: '{}', badgeTone: 'style' }
  if (ext === 'json' || ext === 'yaml' || ext === 'yml' || ext === 'toml') return { fileName, dirName, badge: '{}', badgeTone: 'json' }
  if (ext === 'md' || ext === 'txt') return { fileName, dirName, badge: 'MD', badgeTone: 'doc' }
  if (ext === 'sh' || ext === 'ps1' || ext === 'bash') return { fileName, dirName, badge: '$_', badgeTone: 'sh' }
  return { fileName, dirName, badge: ext ? ext.slice(0, 3).toUpperCase() : '·', badgeTone: 'plain' }
}

/** 将 Unified Patch 拆分为可独立撤销的 Hunk 列表并计算旧/新行号。 */
export function parseDiffHunks(patch: string): DiffHunk[] {
  const rawLines = String(patch || '').replace(/\r\n/g, '\n').split('\n')
  const hunks: DiffHunk[] = []
  let current: {
    header: string
    oldStart: number
    oldCount: number
    newStart: number
    newCount: number
    rawLines: string[]
    oldLine: number
    newLine: number
    lines: DiffLineItem[]
  } | null = null

  const flush = () => {
    if (!current) return
    hunks.push({
      index: hunks.length,
      header: current.header,
      oldStart: current.oldStart,
      oldCount: current.oldCount,
      newStart: current.newStart,
      newCount: current.newCount,
      rawPatch: current.rawLines.join('\n'),
      lines: current.lines,
    })
    current = null
  }

  for (const line of rawLines) {
    const hm = HUNK_HEADER_RE.exec(line)
    if (hm) {
      flush()
      const oldStart = Number.parseInt(hm[1], 10) || 1
      const oldCount = hm[2] !== undefined ? Number.parseInt(hm[2], 10) : 1
      const newStart = Number.parseInt(hm[3], 10) || 1
      const newCount = hm[4] !== undefined ? Number.parseInt(hm[4], 10) : 1
      current = {
        header: line,
        oldStart,
        oldCount,
        newStart,
        newCount,
        rawLines: [line],
        oldLine: oldStart,
        newLine: newStart,
        lines: [],
      }
      continue
    }
    if (!current) continue
    if (line.startsWith('\\')) {
      current.rawLines.push(line)
      continue
    }
    if (line.startsWith('+')) {
      current.rawLines.push(line)
      current.lines.push({ kind: 'add', text: line.slice(1), newNo: current.newLine })
      current.newLine += 1
    } else if (line.startsWith('-')) {
      current.rawLines.push(line)
      current.lines.push({ kind: 'del', text: line.slice(1), oldNo: current.oldLine })
      current.oldLine += 1
    } else if (line.startsWith(' ')) {
      current.rawLines.push(line)
      current.lines.push({
        kind: 'ctx',
        text: line.slice(1),
        oldNo: current.oldLine,
        newNo: current.newLine,
      })
      current.oldLine += 1
      current.newLine += 1
    }
  }
  flush()
  return hunks
}

/** 将单个 Hunk 转换为左旧右新并排对比（Split Diff）对齐行。 */
export function toSplitDiffRows(hunk: DiffHunk): SplitDiffRow[] {
  const rows: SplitDiffRow[] = []
  let i = 0
  const lines = hunk.lines

  while (i < lines.length) {
    if (lines[i].kind === 'ctx') {
      rows.push({
        leftNo: lines[i].oldNo,
        leftText: lines[i].text,
        leftKind: 'ctx',
        rightNo: lines[i].newNo,
        rightText: lines[i].text,
        rightKind: 'ctx',
      })
      i += 1
      continue
    }

    const dels: DiffLineItem[] = []
    const adds: DiffLineItem[] = []
    while (i < lines.length && lines[i].kind === 'del') {
      dels.push(lines[i])
      i += 1
    }
    while (i < lines.length && lines[i].kind === 'add') {
      adds.push(lines[i])
      i += 1
    }
    const maxLen = Math.max(dels.length, adds.length)
    for (let k = 0; k < maxLen; k += 1) {
      const d = dels[k]
      const a = adds[k]
      rows.push({
        leftNo: d?.oldNo,
        leftText: d ? d.text : '',
        leftKind: d ? 'del' : 'empty',
        rightNo: a?.newNo,
        rightText: a ? a.text : '',
        rightKind: a ? 'add' : 'empty',
      })
    }
  }
  return rows
}

/** 计算 Hunk 前后及相邻 Hunk 之间被折叠省略的代码行区间（用于按需展开 `+N more lines`）。 */
export function computeHunkGaps(hunks: DiffHunk[], totalNewLines?: number): {
  beforeFirst: DiffGapSegment | null
  between: Array<DiffGapSegment | null>
  afterLast: DiffGapSegment | null
} {
  if (!hunks.length) {
    return { beforeFirst: null, between: [], afterLast: null }
  }
  const first = hunks[0]
  const beforeFirst: DiffGapSegment | null =
    first.newStart > 1
      ? {
          id: `gap-top-${first.newStart}`,
          startNewLine: 1,
          endNewLine: first.newStart - 1,
          oldDelta: first.oldStart - first.newStart,
        }
      : null

  const between: Array<DiffGapSegment | null> = []
  for (let i = 0; i < hunks.length - 1; i += 1) {
    const cur = hunks[i]
    const nxt = hunks[i + 1]
    const curEndNew = cur.newStart + Math.max(cur.newCount, 0) - 1
    if (nxt.newStart > curEndNew + 1) {
      between.push({
        id: `gap-${i}-${curEndNew + 1}-${nxt.newStart - 1}`,
        startNewLine: curEndNew + 1,
        endNewLine: nxt.newStart - 1,
        oldDelta: nxt.oldStart - nxt.newStart,
      })
    } else {
      between.push(null)
    }
  }

  const last = hunks[hunks.length - 1]
  const lastEndNew = last.newStart + Math.max(last.newCount, 0) - 1
  const lastEndOld = last.oldStart + Math.max(last.oldCount, 0) - 1
  const afterLast: DiffGapSegment | null =
    typeof totalNewLines === 'number' && totalNewLines > lastEndNew
      ? {
          id: `gap-tail-${lastEndNew + 1}-${totalNewLines}`,
          startNewLine: lastEndNew + 1,
          endNewLine: totalNewLines,
          oldDelta: lastEndOld - lastEndNew,
        }
      : null

  return { beforeFirst, between, afterLast }
}

export interface ToolMiniDiff {
  filePath: string
  lines: Array<{ kind: DiffLineKind; text: string }>
  truncated?: boolean
}

/** 从 edit / write 类工具输入参数中提取当次调用的局部变更视图。 */
export function extractToolMiniDiff(toolName: string, input: unknown): ToolMiniDiff | null {
  if (!input || typeof input !== 'object') return null
  const lower = toolName.toLowerCase()
  if (!/(edit|write|patch|replace)/.test(lower)) return null

  const rec = input as Record<string, unknown>
  const filePath = String(rec.filePath ?? rec.path ?? rec.file ?? rec.target_file ?? '').trim()
  const oldStr = rec.oldString ?? rec.old_string ?? rec.oldText ?? rec.TargetContent
  const newStr = rec.newString ?? rec.new_string ?? rec.newText ?? rec.ReplacementContent ?? rec.content

  if (typeof oldStr === 'string' && typeof newStr === 'string') {
    const out: Array<{ kind: DiffLineKind; text: string }> = []
    const oldLines = oldStr.replace(/\r\n/g, '\n').split('\n')
    const newLines = newStr.replace(/\r\n/g, '\n').split('\n')
    for (const l of oldLines.slice(0, 60)) out.push({ kind: 'del', text: l })
    for (const l of newLines.slice(0, 60)) out.push({ kind: 'add', text: l })
    return {
      filePath,
      lines: out,
      truncated: oldLines.length > 60 || newLines.length > 60,
    }
  }

  if (typeof rec.content === 'string' && /(write|create)/.test(lower)) {
    const newLines = rec.content.replace(/\r\n/g, '\n').split('\n')
    return {
      filePath,
      lines: newLines.slice(0, 50).map(text => ({ kind: 'add', text })),
      truncated: newLines.length > 50,
    }
  }

  return null
}
