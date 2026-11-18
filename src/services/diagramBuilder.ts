/**
 * 零依赖轻量 Mermaid 图表解析与矢量布局生成器：
 * 支持 `flowchart` / `graph` (TD/TB/LR/RL) 与 `sequenceDiagram`，
 * 输出声明式 SVG 图元数据供 Vue 模板渲染（绝不使用 v-html 或动态执行）。
 */

export interface DiagramSvgNode {
  id: string
  label: string
  x: number
  y: number
  width: number
  height: number
  shape: 'rect' | 'round' | 'diamond'
}

export interface DiagramSvgEdge {
  d: string
  label?: string
  labelX?: number
  labelY?: number
  dashed?: boolean
}

export interface SequenceLifeline {
  id: string
  label: string
  x: number
  topY: number
  bottomY: number
}

export interface SequenceMessage {
  fromX: number
  toX: number
  y: number
  label: string
  dashed?: boolean
  selfLoop?: boolean
}

export interface DiagramRenderModel {
  kind: 'flowchart' | 'sequence'
  width: number
  height: number
  nodes: DiagramSvgNode[]
  edges: DiagramSvgEdge[]
  lifelines?: SequenceLifeline[]
  messages?: SequenceMessage[]
}

function parseNodeToken(raw: string): { id: string; label: string; shape: 'rect' | 'round' | 'diamond' } {
  const token = raw.trim()
  const diamond = /^([A-Za-z0-9_.-]+)\{\s*(.+?)\s*\}$/.exec(token)
  if (diamond) return { id: diamond[1], label: stripQuotes(diamond[2]), shape: 'diamond' }
  const round = /^([A-Za-z0-9_.-]+)\(\s*(.+?)\s*\)$/.exec(token)
  if (round) return { id: round[1], label: stripQuotes(round[2]), shape: 'round' }
  const stadium = /^([A-Za-z0-9_.-]+)\(\[\s*(.+?)\s*\]\)$/.exec(token)
  if (stadium) return { id: stadium[1], label: stripQuotes(stadium[2]), shape: 'round' }
  const rect = /^([A-Za-z0-9_.-]+)\[\s*(.+?)\s*\]$/.exec(token)
  if (rect) return { id: rect[1], label: stripQuotes(rect[2]), shape: 'rect' }
  const cleanId = token.replace(/[^A-Za-z0-9_.-]/g, '') || token
  return { id: cleanId, label: cleanId, shape: 'rect' }
}

function stripQuotes(text: string): string {
  const t = text.trim()
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return t.slice(1, -1)
  }
  return t
}

function estimateNodeWidth(label: string): number {
  let units = 0
  for (const ch of label) {
    units += /[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch) ? 14 : 8
  }
  return Math.max(88, Math.min(240, units + 28))
}

function parseFlowchainParts(stmt: string): {
  nodes: string[]
  links: Array<{ label?: string; dashed: boolean }>
} {
  const nodes: string[] = []
  const links: Array<{ label?: string; dashed: boolean }> = []
  let buf = ''
  let depthSquare = 0
  let depthRound = 0
  let depthCurly = 0
  let quote: '"' | "'" | null = null
  let i = 0

  const flushNode = () => {
    const trimmed = buf.trim()
    if (trimmed) nodes.push(trimmed)
    buf = ''
  }

  while (i < stmt.length) {
    const ch = stmt[i]
    if (quote) {
      buf += ch
      if (ch === quote && stmt[i - 1] !== '\\') quote = null
      i++
      continue
    }
    if (ch === '"' || ch === "'") {
      quote = ch
      buf += ch
      i++
      continue
    }
    if (ch === '[') { depthSquare++; buf += ch; i++; continue }
    if (ch === ']' && depthSquare > 0) { depthSquare--; buf += ch; i++; continue }
    if (ch === '(') { depthRound++; buf += ch; i++; continue }
    if (ch === ')' && depthRound > 0) { depthRound--; buf += ch; i++; continue }
    if (ch === '{') { depthCurly++; buf += ch; i++; continue }
    if (ch === '}' && depthCurly > 0) { depthCurly--; buf += ch; i++; continue }

    if (depthSquare === 0 && depthRound === 0 && depthCurly === 0) {
      const rest = stmt.slice(i)
      const arrowPipe = /^(-\.->|-->|==>)(\s*\|([^|]+)\|)?/.exec(rest)
      if (arrowPipe) {
        flushNode()
        links.push({
          label: arrowPipe[3] ? stripQuotes(arrowPipe[3]) : undefined,
          dashed: arrowPipe[1].includes('.'),
        })
        i += arrowPipe[0].length
        continue
      }
      const arrowText = /^(--|-\.)\s+([^->]+?)\s+(-->|->)/.exec(rest)
      if (arrowText) {
        flushNode()
        links.push({
          label: stripQuotes(arrowText[2]),
          dashed: arrowText[1].includes('.'),
        })
        i += arrowText[0].length
        continue
      }
    }

    buf += ch
    i++
  }
  flushNode()
  return { nodes, links }
}

function parseFlowchart(lines: string[]): DiagramRenderModel | null {
  const header = lines[0]?.trim() || ''
  const dirMatch = /^(?:flowchart|graph)\s+(TD|TB|BT|LR|RL)\b/i.exec(header)
  const dir = (dirMatch?.[1] || 'TD').toUpperCase()
  const horizontal = dir === 'LR' || dir === 'RL'

  const nodeMap = new Map<string, { id: string; label: string; shape: 'rect' | 'round' | 'diamond' }>()
  const edgesRaw: { from: string; to: string; label?: string; dashed: boolean }[] = []

  const ensureNode = (raw: string) => {
    const parsed = parseNodeToken(raw)
    const existing = nodeMap.get(parsed.id)
    if (!existing) {
      nodeMap.set(parsed.id, parsed)
    } else if (parsed.label !== parsed.id) {
      nodeMap.set(parsed.id, parsed)
    }
    return parsed.id
  }

  for (const rawLine of lines.slice(1)) {
    const cleanLine = rawLine.replace(/%%.*$/, '').trim()
    if (!cleanLine) continue
    for (const stmt of cleanLine.split(';').map(s => s.trim()).filter(Boolean)) {
      if (stmt.startsWith('subgraph ') || stmt === 'end' || stmt.startsWith('classDef ') || stmt.startsWith('style ')) {
        continue
      }

      const chain = parseFlowchainParts(stmt)
      if (chain.nodes.length >= 2 && chain.links.length === chain.nodes.length - 1) {
        const ids = chain.nodes.map(ensureNode)
        for (let k = 0; k < chain.links.length; k++) {
          edgesRaw.push({
            from: ids[k],
            to: ids[k + 1],
            label: chain.links[k].label,
            dashed: chain.links[k].dashed,
          })
        }
        continue
      }

      // 单独节点声明
      if (/^[A-Za-z0-9_.-]+(?:\[.+?\]|\(.+?\)|\{.+?\})$/.test(stmt)) {
        ensureNode(stmt)
      }
    }
  }

  if (nodeMap.size === 0) return null

  // 按 BFS/最长路径分配拓扑层级，防止环图死循环
  const inDegree = new Map<string, number>()
  const adj = new Map<string, string[]>()
  for (const id of nodeMap.keys()) {
    inDegree.set(id, 0)
    adj.set(id, [])
  }
  for (const e of edgesRaw) {
    if (e.from !== e.to) {
      adj.get(e.from)?.push(e.to)
      inDegree.set(e.to, (inDegree.get(e.to) || 0) + 1)
    }
  }

  const rank = new Map<string, number>()
  const queue: string[] = []
  for (const [id, deg] of inDegree.entries()) {
    if (deg === 0) {
      rank.set(id, 0)
      queue.push(id)
    }
  }
  if (queue.length === 0) {
    const first = Array.from(nodeMap.keys())[0]
    rank.set(first, 0)
    queue.push(first)
  }

  const visitedCount = new Map<string, number>()
  while (queue.length > 0) {
    const u = queue.shift()!
    const uRank = rank.get(u) || 0
    for (const v of adj.get(u) || []) {
      const seen = (visitedCount.get(v) || 0) + 1
      visitedCount.set(v, seen)
      if (seen > nodeMap.size * 2) continue
      const candidate = uRank + 1
      if ((rank.get(v) ?? -1) < candidate) {
        rank.set(v, candidate)
        queue.push(v)
      }
    }
  }
  for (const id of nodeMap.keys()) {
    if (!rank.has(id)) rank.set(id, 0)
  }

  const layers = new Map<number, string[]>()
  for (const [id, r] of rank.entries()) {
    const bucket = layers.get(r) || []
    bucket.push(id)
    layers.set(r, bucket)
  }
  const maxLayer = Math.max(0, ...layers.keys())

  const pad = 28
  const nodeH = 40
  const layerGap = horizontal ? 64 : 52
  const siblingGap = 24

  const positioned = new Map<string, DiagramSvgNode>()
  let maxX = 0
  let maxY = 0

  if (horizontal) {
    let curX = pad
    for (let l = 0; l <= maxLayer; l++) {
      const ids = layers.get(l) || []
      const colW = Math.max(96, ...ids.map((id) => estimateNodeWidth(nodeMap.get(id)!.label)))
      let curY = pad
      for (const id of ids) {
        const meta = nodeMap.get(id)!
        const w = estimateNodeWidth(meta.label)
        const x = curX + (colW - w) / 2
        positioned.set(id, { id, label: meta.label, shape: meta.shape, x, y: curY, width: w, height: nodeH })
        maxX = Math.max(maxX, x + w)
        maxY = Math.max(maxY, curY + nodeH)
        curY += nodeH + siblingGap
      }
      curX += colW + layerGap
    }
  } else {
    // 计算最宽行以居中对齐
    let widestRow = 0
    for (let l = 0; l <= maxLayer; l++) {
      const ids = layers.get(l) || []
      const rowW = ids.reduce((s, id) => s + estimateNodeWidth(nodeMap.get(id)!.label), 0) + Math.max(0, ids.length - 1) * siblingGap
      widestRow = Math.max(widestRow, rowW)
    }
    let curY = pad
    for (let l = 0; l <= maxLayer; l++) {
      const ids = layers.get(l) || []
      const rowW = ids.reduce((s, id) => s + estimateNodeWidth(nodeMap.get(id)!.label), 0) + Math.max(0, ids.length - 1) * siblingGap
      let curX = pad + Math.max(0, (widestRow - rowW) / 2)
      for (const id of ids) {
        const meta = nodeMap.get(id)!
        const w = estimateNodeWidth(meta.label)
        positioned.set(id, { id, label: meta.label, shape: meta.shape, x: curX, y: curY, width: w, height: nodeH })
        maxX = Math.max(maxX, curX + w)
        maxY = Math.max(maxY, curY + nodeH)
        curX += w + siblingGap
      }
      curY += nodeH + layerGap
    }
  }

  const edges: DiagramSvgEdge[] = []
  for (const e of edgesRaw) {
    const fromN = positioned.get(e.from)
    const toN = positioned.get(e.to)
    if (!fromN || !toN) continue
    if (horizontal) {
      const x1 = fromN.x + fromN.width
      const y1 = fromN.y + fromN.height / 2
      const x2 = toN.x
      const y2 = toN.y + toN.height / 2
      const mx = (x1 + x2) / 2
      edges.push({
        d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`,
        label: e.label,
        labelX: mx,
        labelY: (y1 + y2) / 2 - 6,
        dashed: e.dashed,
      })
    } else {
      const x1 = fromN.x + fromN.width / 2
      const y1 = fromN.y + fromN.height
      const x2 = toN.x + toN.width / 2
      const y2 = toN.y
      const my = (y1 + y2) / 2
      edges.push({
        d: `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`,
        label: e.label,
        labelX: (x1 + x2) / 2,
        labelY: my - 4,
        dashed: e.dashed,
      })
    }
  }

  return {
    kind: 'flowchart',
    width: Math.max(260, Math.ceil(maxX + pad)),
    height: Math.max(120, Math.ceil(maxY + pad)),
    nodes: Array.from(positioned.values()),
    edges,
  }
}

function parseSequence(lines: string[]): DiagramRenderModel | null {
  const actors = new Map<string, string>()
  const messagesRaw: { from: string; to: string; label: string; dashed: boolean }[] = []

  const ensureActor = (id: string, label?: string) => {
    const clean = id.trim()
    if (!clean) return ''
    if (!actors.has(clean)) actors.set(clean, label?.trim() || clean)
    else if (label?.trim()) actors.set(clean, label.trim())
    return clean
  }

  for (const raw of lines.slice(1)) {
    const line = raw.replace(/%%.*$/, '').trim()
    if (!line) continue
    const partMatch = /^(?:participant|actor)\s+([A-Za-z0-9_.-]+)(?:\s+as\s+(.+))?$/i.exec(line)
    if (partMatch) {
      ensureActor(partMatch[1], partMatch[2])
      continue
    }
    const msgMatch = /^([A-Za-z0-9_.-]+)\s*(->>|-->>|->|-->)\s*([A-Za-z0-9_.-]+)\s*:\s*(.*)$/.exec(line)
    if (msgMatch) {
      const from = ensureActor(msgMatch[1])
      const to = ensureActor(msgMatch[3])
      messagesRaw.push({
        from,
        to,
        label: msgMatch[4].trim(),
        dashed: msgMatch[2].startsWith('--'),
      })
    }
  }

  if (actors.size === 0 || messagesRaw.length === 0) return null

  const actorList = Array.from(actors.entries())
  const padX = 28
  const colStep = 148
  const topY = 58
  const rowStep = 42
  const bottomY = topY + messagesRaw.length * rowStep + 26

  const xByActor = new Map<string, number>()
  const lifelines: SequenceLifeline[] = actorList.map(([id, label], idx) => {
    const x = padX + 55 + idx * colStep
    xByActor.set(id, x)
    return { id, label, x, topY, bottomY }
  })

  const messages: SequenceMessage[] = messagesRaw.map((m, idx) => {
    const fromX = xByActor.get(m.from) ?? padX + 55
    const toX = xByActor.get(m.to) ?? padX + 55
    return {
      fromX,
      toX,
      y: topY + 28 + idx * rowStep,
      label: m.label,
      dashed: m.dashed,
      selfLoop: m.from === m.to,
    }
  })

  return {
    kind: 'sequence',
    width: Math.max(320, padX * 2 + Math.max(1, actorList.length - 1) * colStep + 110),
    height: bottomY + 24,
    nodes: [],
    edges: [],
    lifelines,
    messages,
  }
}

/** 解析 Mermaid 源码并返回结构化 SVG 渲染模型；不支持的图表类型返回 null。 */
export function parseMermaidDiagram(source: string): DiagramRenderModel | null {
  const lines = String(source || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((l) => l.trimEnd())
    .filter((l) => l.trim().length > 0)
  if (lines.length === 0) return null
  const first = lines[0].trim().toLowerCase()
  if (first.startsWith('flowchart') || first.startsWith('graph ')) {
    return parseFlowchart(lines)
  }
  if (first.startsWith('sequencediagram')) {
    return parseSequence(lines)
  }
  return null
}
