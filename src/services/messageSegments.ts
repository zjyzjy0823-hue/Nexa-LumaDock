/**
 * 参考 hermes-mobile (HostMediaExtractor.kt / HostMediaAttachments.kt / MessageSegment.kt / FullBleedAgentMessage.kt)
 * 实现的正文内联媒体与文件分段器：
 * 1. 解析并剥离正文中的 `MEDIA:<path>`、`@file:<path>`、`@image:<path>` 指令，记录其在剥离后正文中的字符偏移量 `contentOffset`。
 * 2. 自动识别正文中提及已知附件路径/文件名（或首段「见上/如下」导语）的位置并计算 `contentOffset`。
 * 3. 通过 `snapToBlockEnd` 将插入点对齐到当前段落行尾，且自动越过未闭合的 ``` 代码围栏，
 *    将单段长文切分为交错的 `Text` 与 `Media` 片段，使图片、音视频与文件卡片自然穿插在文章段落之间。
 */

import type { ArtifactRef, ChatMessage, MessageMediaItem, ToolCallBadge } from '../types/fleet'
import { groupMessageParts, type GroupedMessagePart } from './chatHelpers.ts'

export interface InlineMediaAttachment {
  id: string
  fileName: string
  mime: string
  url?: string
  filePath?: string
  sizeBytes?: number
  artifact?: ArtifactRef
  contentOffset?: number
}

export type MessageSegment =
  | { type: 'text'; text: string }
  | { type: 'media'; attachment: InlineMediaAttachment }

export type TurnRenderItem =
  | { type: 'thought'; id: string; text: string; isLast: boolean }
  | { type: 'tool-group'; id: string; group: Extract<GroupedMessagePart, { type: 'tool-group' }> }
  | { type: 'tool'; id: string; callId: string; tool: ToolCallBadge }
  | { type: 'text'; id: string; text: string; isLast: boolean }
  | { type: 'media'; id: string; attachment: InlineMediaAttachment }

export type WorkLogStep = Extract<TurnRenderItem, { type: 'thought' | 'tool' }>
export type WorkLogProgress = { type: 'thought' | 'text' } | { type: 'tool'; tool: ToolCallBadge }

export interface WorkLogRenderItem {
  type: 'work-log'
  id: string
  steps: WorkLogStep[]
  isLast: boolean
  progress?: WorkLogProgress
}

type ThreadRenderItem = WorkLogRenderItem | Extract<TurnRenderItem, { type: 'text' | 'media' }>

export interface ExtractedHostMedia {
  match: string
  path: string
  offset: number
}

const MEDIA_TAG_RE =
  /[`"']?(?:MEDIA|@file|@image):\s*(?:"([^"]+)"|'([^']+)'|`([^`]+)`|((?:~|\/|[A-Za-z]:[/\\]|\.{1,2}[/\\])[^\s`"')]*))[`"']?/gi

export function inferMimeFromPath(filePath: string): string {
  const ext = filePath.replace(/\\/g, '/').split('.').pop()?.toLowerCase() || ''
  switch (ext) {
    case 'png':
      return 'image/png'
    case 'jpg':
    case 'jpeg':
      return 'image/jpeg'
    case 'gif':
      return 'image/gif'
    case 'webp':
      return 'image/webp'
    case 'bmp':
      return 'image/bmp'
    case 'svg':
      return 'image/svg+xml'
    case 'mp4':
    case 'm4v':
      return 'video/mp4'
    case 'webm':
      return 'video/webm'
    case 'mov':
      return 'video/quicktime'
    case 'mp3':
      return 'audio/mpeg'
    case 'wav':
      return 'audio/wav'
    case 'ogg':
      return 'audio/ogg'
    case 'pdf':
      return 'application/pdf'
    case 'zip':
      return 'application/zip'
    case 'json':
      return 'application/json'
    case 'csv':
      return 'text/csv'
    case 'md':
      return 'text/markdown'
    default:
      return 'application/octet-stream'
  }
}

export function cleanBaseFileName(rawPathOrName?: string): string {
  const s = (rawPathOrName || '').trim()
  if (!s) return 'attachment'
  return s.replace(/\\/g, '/').split('/').pop() || s
}

/**
 * 从正文中提取所有 `MEDIA:<path>` / `@file:<path>` / `@image:<path>` 指令及其在剥离后正文中的字符偏移量
 * （同 hermes-mobile HostMediaExtractor.extract）。
 */
export function extractHostMediaDirectives(text: string): ExtractedHostMedia[] {
  if (!/(?:MEDIA|@file|@image):/i.test(text)) return []
  const strippedTotal = stripHostMediaDirectives(text).length
  const items: ExtractedHostMedia[] = []
  let kept = ''
  let cursor = 0
  MEDIA_TAG_RE.lastIndex = 0

  let m: RegExpExecArray | null
  while ((m = MEDIA_TAG_RE.exec(text)) !== null) {
    kept += text.slice(cursor, m.index)
    cursor = m.index + m[0].length
    const rawPath = (m[1] || m[2] || m[3] || m[4] || '').trim()
    if (!rawPath) continue
    const offset = Math.min(stripHostMediaDirectives(kept).length, strippedTotal)
    items.push({
      match: m[0],
      path: rawPath,
      offset,
    })
  }
  return items
}

/**
 * 剥离正文中的 `MEDIA:<path>` / `@file:<path>` / `@image:<path>` 指令文本（同 hermes-mobile HostMediaExtractor.strip）。
 */
export function stripHostMediaDirectives(text: string): string {
  if (!/(?:MEDIA|@file|@image):/i.test(text)) return text
  MEDIA_TAG_RE.lastIndex = 0
  return text
    .replace(MEDIA_TAG_RE, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function lineEnd(content: string, from: number): number {
  const idx = content.indexOf('\n', from)
  return idx < 0 ? content.length : idx
}

function fenceOpenBefore(content: string, pos: number): boolean {
  let open = false
  const lines = content.slice(0, pos).split('\n')
  for (const line of lines) {
    const trimmed = line.trimStart()
    if (trimmed.startsWith('```') || trimmed.startsWith('~~~')) {
      open = !open
    }
  }
  return open
}

/**
 * 将偏移量吸附到当前行尾；若处于未闭合的代码块围栏内，则自动延后到闭合围栏行尾（同 hermes-mobile snapToBlockEnd）。
 */
export function snapToBlockEnd(content: string, offset: number): number {
  let pos = Math.max(0, Math.min(offset, content.length))
  pos = lineEnd(content, pos)
  while (fenceOpenBefore(content, pos)) {
    const next = pos + 1
    if (next > content.length) return content.length
    pos = lineEnd(content, next)
  }
  return pos
}

/**
 * 在正文中定位某附件被引用的位置（支持完整路径、文件名或首段「见上/如下」导语）。
 */
export function findAttachmentOffsetInText(
  content: string,
  att: Pick<InlineMediaAttachment, 'filePath' | 'fileName' | 'contentOffset'>,
): number | undefined {
  if (typeof att.contentOffset === 'number' && att.contentOffset >= 0) {
    return att.contentOffset
  }
  if (!content.trim()) return undefined

  const candidates: string[] = []
  if (att.filePath?.trim()) {
    candidates.push(att.filePath.trim())
    candidates.push(att.filePath.trim().replace(/\\/g, '/'))
  }
  const baseName = cleanBaseFileName(att.fileName || att.filePath)
  if (baseName && baseName.length >= 3 && baseName !== 'attachment' && !/^media-\d+\./i.test(baseName)) {
    candidates.push(baseName)
  }

  for (const cand of candidates) {
    const idx = content.indexOf(cand)
    if (idx >= 0) {
      return idx + cand.length
    }
  }

  // 若正文首段明确写有「图已发出（见上）」「如下所示」「见下图」等导语，则将图片/附件插在首段导语下方
  const leadMatch = /(?:图已发出|文件已生成|已保存至|如下所示|见下图|见上图|见上|见下|如下[：:])/.exec(content)
  if (leadMatch && leadMatch.index < 120) {
    return leadMatch.index + leadMatch[0].length
  }

  return undefined
}

/**
 * 将正文与附件列表按引用位置切分为交错的 `MessageSegment[]`（同 hermes-mobile splitByMedia）。
 * 返回拆分后的片段列表，以及已被内联消费的附件 ID 集合。
 */
export function splitTextByInlineMedia(
  rawText: string,
  availableAttachments: InlineMediaAttachment[],
  options?: { allowTrailingUnmatched?: boolean; alreadyConsumed?: Set<string> },
): { segments: MessageSegment[]; consumedIds: Set<string> } {
  const directives = extractHostMediaDirectives(rawText)
  const content = directives.length ? stripHostMediaDirectives(rawText) : rawText
  const consumedIds = new Set<string>(options?.alreadyConsumed ?? [])

  // 将正文中的 MEDIA:<path> / @file:<path> / @image:<path> 指令转化为内联附件
  const directiveAttachments: InlineMediaAttachment[] = directives.map((d, idx) => {
    const baseName = cleanBaseFileName(d.path)
    const matched = availableAttachments.find(
      a =>
        !consumedIds.has(a.id) &&
        ((a.filePath && a.filePath.replace(/\\/g, '/').toLowerCase() === d.path.replace(/\\/g, '/').toLowerCase()) ||
          cleanBaseFileName(a.fileName).toLowerCase() === baseName.toLowerCase()),
    )
    if (matched) {
      consumedIds.add(matched.id)
      return {
        ...matched,
        contentOffset: d.offset,
      }
    }
    const id = `host-media-${idx}-${d.offset}`
    consumedIds.add(id)
    return {
      id,
      fileName: baseName,
      filePath: d.path,
      mime: inferMimeFromPath(d.path),
      contentOffset: d.offset,
    }
  })

  const positioned: InlineMediaAttachment[] = [...directiveAttachments]
  const trailing: InlineMediaAttachment[] = []

  for (const att of availableAttachments) {
    if (consumedIds.has(att.id)) continue
    const offset = findAttachmentOffsetInText(content, att)
    if (offset !== undefined) {
      consumedIds.add(att.id)
      positioned.push({ ...att, contentOffset: offset })
    } else if (options?.allowTrailingUnmatched) {
      consumedIds.add(att.id)
      trailing.push(att)
    }
  }

  if (!positioned.length && !trailing.length) {
    return {
      segments: content.trim() ? [{ type: 'text', text: content }] : [],
      consumedIds,
    }
  }

  positioned.sort((a, b) => (a.contentOffset ?? 0) - (b.contentOffset ?? 0))

  const out: MessageSegment[] = []
  const addText = (chunk: string) => {
    const trimmed = chunk.replace(/^\n+|\n+$/g, '')
    if (trimmed.trim()) {
      out.push({ type: 'text', text: trimmed })
    }
  }

  let cursor = 0
  for (const att of positioned) {
    const pos = Math.max(cursor, snapToBlockEnd(content, att.contentOffset ?? 0))
    addText(content.slice(cursor, pos))
    out.push({ type: 'media', attachment: att })
    cursor = pos
  }
  addText(content.slice(cursor))
  for (const att of trailing) {
    out.push({ type: 'media', attachment: att })
  }

  return { segments: out, consumedIds }
}

/**
 * 汇总消息中所有可内联展示的媒体与文件附件（去重）。
 */
export function collectMessageInlineAttachments(
  msg: {
    text?: string
    media?: MessageMediaItem[]
    toolCalls?: ToolCallBadge[]
    artifacts?: ArtifactRef[]
  },
  imagePreviewByArtifactId: Record<string, string> = {},
): InlineMediaAttachment[] {
  const out: InlineMediaAttachment[] = []
  const seenKeys = new Set<string>()
  const seenNames = new Set<string>()

  // 从 read / view 工具调用中收集读取过的文件路径，供缺少 filePath 的媒体项（如 OpenCode "Image 1 (JPEG, 40 KB)"）关联合并
  const readToolPaths: string[] = []
  for (const tc of msg.toolCalls ?? []) {
    if (!tc.input || typeof tc.input !== 'object') continue
    const rec = tc.input as Record<string, unknown>
    const rawPath = rec.filePath ?? rec.path ?? rec.file ?? rec.target_file ?? rec.filename
    if (typeof rawPath === 'string' && rawPath.trim() && !rawPath.includes('://')) {
      readToolPaths.push(rawPath.trim())
    }
  }
  let readPathCursor = 0

  for (const item of [...(msg.media ?? []), ...(msg.toolCalls?.flatMap(t => t.media ?? []) ?? [])]) {
    if (!item?.url) continue
    const key = item.url
    if (seenKeys.has(key)) continue
    seenKeys.add(key)

    let resolvedPath = item.filePath?.trim()
    const rawName = (item.fileName || '').trim()
    const isGenericLabel = !rawName || /^(?:image\s+\d+|media-\d+|attachment)/i.test(rawName)

    if (!resolvedPath && readToolPaths.length > 0) {
      const isImg = (item.mime || '').startsWith('image/') || item.url.startsWith('data:image/')
      const matchedReadPath =
        (isImg
          ? readToolPaths.find(p => /\.(?:png|jpe?g|gif|webp|bmp|svg)$/i.test(p))
          : undefined) ?? readToolPaths[Math.min(readPathCursor, readToolPaths.length - 1)]
      if (matchedReadPath) {
        resolvedPath = matchedReadPath
        readPathCursor += 1
      }
    }

    const name =
      isGenericLabel && resolvedPath
        ? cleanBaseFileName(resolvedPath)
        : cleanBaseFileName(rawName || resolvedPath)
    seenNames.add(name.toLowerCase())
    out.push({
      id: item.id || `media-${out.length}`,
      fileName: name,
      mime: item.mime || inferMimeFromPath(name || resolvedPath || ''),
      url: item.url,
      filePath: resolvedPath,
      sizeBytes: item.sizeBytes,
    })
  }

  for (const art of msg.artifacts ?? []) {
    const key = `art:${art.artifactId}`
    if (seenKeys.has(key)) continue
    seenKeys.add(key)
    const name = cleanBaseFileName(art.fileName)
    seenNames.add(name.toLowerCase())
    out.push({
      id: key,
      fileName: name,
      mime: art.mime || inferMimeFromPath(art.fileName),
      url: imagePreviewByArtifactId[art.artifactId],
      sizeBytes: art.plaintextSize,
      artifact: art,
    })
  }

  // 若 Agent 通过 write / edit / create 工具生成了文件并在文章正文中点名引用了该文件路径，也作为可内联预览/下载卡片穿插到对应段落
  const fullText = msg.text || ''
  if (fullText && msg.toolCalls?.length) {
    for (const tc of msg.toolCalls) {
      if (tc.status === 'error' || !tc.input || typeof tc.input !== 'object') continue
      const toolName = (tc.name || '').toLowerCase()
      const isWriteOrFile =
        toolName.includes('write') ||
        toolName.includes('create') ||
        toolName.includes('save') ||
        toolName.includes('export')
      if (!isWriteOrFile) continue
      const rec = tc.input as Record<string, unknown>
      const rawPath = rec.filePath ?? rec.path ?? rec.file ?? rec.target_file ?? rec.filename
      if (typeof rawPath !== 'string' || !rawPath.trim() || rawPath.includes('://')) continue
      const cleanPath = rawPath.trim()
      const baseName = cleanBaseFileName(cleanPath)
      if (seenNames.has(baseName.toLowerCase())) continue
      if (fullText.includes(cleanPath) || fullText.includes(baseName)) {
        seenNames.add(baseName.toLowerCase())
        out.push({
          id: `tc-file-${tc.callId || tc.id}`,
          fileName: baseName,
          filePath: cleanPath,
          mime: inferMimeFromPath(cleanPath),
        })
      }
    }
  }

  return out
}

/**
 * 将单条消息的 `groupMessageParts(msg)` 与内联附件融合为有序渲染序列：
 * 被正文引用的图片/文件直接穿插在正文对应段落之后，未被引用到的附件紧随末尾展示。
 */
export function buildTurnRenderItems(
  msg: ChatMessage,
  imagePreviewByArtifactId: Record<string, string> = {},
): TurnRenderItem[] {
  const parts = groupMessageParts(msg)
  const allAttachments = collectMessageInlineAttachments(msg, imagePreviewByArtifactId)
  const consumed = new Set<string>()
  const out: TurnRenderItem[] = []

  const lastTextPartIdx = parts.reduce((acc, p, idx) => (p.type === 'text' && p.text?.trim() ? idx : acc), -1)

  parts.forEach((part, pIdx) => {
    const isLast = pIdx === parts.length - 1
    if (part.type === 'thought') {
      out.push({ type: 'thought', id: `${msg.id}-p-${pIdx}`, text: part.text, isLast })
      return
    }
    if (part.type === 'tool-group') {
      out.push({ type: 'tool-group', id: `${msg.id}-p-${pIdx}`, group: part })
      return
    }
    if (part.type === 'tool') {
      out.push({ type: 'tool', id: `${msg.id}-p-${pIdx}`, callId: part.callId, tool: part.tool })
      return
    }
    if (part.type === 'text' && part.text) {
      const isFinalTextPart = pIdx === lastTextPartIdx
      const { segments, consumedIds } = splitTextByInlineMedia(part.text, allAttachments, {
        allowTrailingUnmatched: isFinalTextPart,
        alreadyConsumed: consumed,
      })
      for (const id of consumedIds) consumed.add(id)
      segments.forEach((seg, sIdx) => {
        if (seg.type === 'text') {
          out.push({
            type: 'text',
            id: `${msg.id}-p-${pIdx}-s-${sIdx}`,
            text: seg.text,
            isLast: isLast && sIdx === segments.length - 1,
          })
        } else {
          out.push({
            type: 'media',
            id: `${msg.id}-p-${pIdx}-m-${seg.attachment.id}`,
            attachment: seg.attachment,
          })
        }
      })
    }
  })

  // 若消息没有 text part（仅有工具或纯附件），把剩余未消费附件追加展示
  for (const att of allAttachments) {
    if (!consumed.has(att.id)) {
      consumed.add(att.id)
      out.push({
        type: 'media',
        id: `${msg.id}-trail-${att.id}`,
        attachment: att,
      })
    }
  }

  return out
}

// Keep user-visible prose and attachments in place when a provider emits them between steps.
export function buildThreadRenderItems(
  msg: ChatMessage,
  imagePreviewByArtifactId: Record<string, string> = {},
): ThreadRenderItem[] {
  const out: ThreadRenderItem[] = []
  const items = buildTurnRenderItems(msg, imagePreviewByArtifactId)
  for (const [index, item] of items.entries()) {
    if (item.type === 'text' || item.type === 'media') {
      out.push(item)
      continue
    }
    const steps: WorkLogStep[] = item.type === 'tool-group'
      ? item.group.tools.map(tool => ({ type: 'tool', id: `${msg.id}-tool-${tool.callId || tool.id}`, callId: tool.callId || tool.id, tool }))
      : item.type === 'tool'
        ? [{ ...item, id: `${msg.id}-tool-${item.callId}` }]
        : [item]
    const previous = out.at(-1)
    const isLast = index === items.length - 1
    if (previous?.type === 'work-log') {
      previous.steps.push(...steps)
      previous.isLast = isLast
    } else {
      out.push({ type: 'work-log', id: `${item.id}-work`, steps, isLast })
    }
  }

  if (msg.streaming) {
    const logs = out.filter(item => item.type === 'work-log')
    const latestLog = logs.at(-1)
    const progress = msg.liveProgress
    if (latestLog && progress?.type === 'tool') {
      for (const log of logs) {
        const step = log.steps.find(step => step.type === 'tool' && step.callId === progress.callId)
        if (step?.type !== 'tool') continue
        log.progress = { type: 'tool', tool: step.tool }
        return out
      }
    }
    if (latestLog) {
      const lastStep = latestLog.steps.at(-1)
      if (progress?.type === 'thought' || progress?.type === 'text') latestLog.progress = progress
      else if (msg.parts?.at(-1)?.type === 'text' || out.at(-1)?.type === 'text') latestLog.progress = { type: 'text' }
      else if (lastStep) latestLog.progress = lastStep
    }
  }
  return out
}
