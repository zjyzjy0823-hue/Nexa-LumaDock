<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import {
  computeHunkGaps,
  parseDiffHunks,
  splitDiffPath,
  toSplitDiffRows,
  type DiffGapSegment,
  type DiffHunk,
} from '../../services/diffHelpers'
import { highlightCode, inferLanguageFromPath, type HighlightSpan } from '../../services/syntaxHighlight'
import { useFleetStore } from '../../stores/fleet'
import type { CheckpointInfo, DiffFileEntry, SessionDiffState } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  diff: SessionDiffState | null
  checkpoints: CheckpointInfo[]
  sessionKey?: string
  selectedCheckpointId?: string
  focusFilePath?: string
  isWorktree?: boolean
  loading?: boolean
  embedded?: boolean
}>()

const emit = defineEmits<{
  refresh: []
  close: []
  revertLatest: [checkpointId: string]
  revertFiles: [paths: string[], checkpointId?: string]
  revertHunk: [filePath: string, hunkPatch: string]
  commitChanges: [message: string, paths?: string[]]
  selectCheckpoint: [checkpointId?: string]
  openFile: [filePath: string]
  askAboutFile: [filePath: string]
  commentLine: [citationText: string]
  mergeWorktree: []
}>()

const fleet = useFleetStore()
const drawerBodyRef = ref<HTMLElement | null>(null)
const diffMode = ref<'unified' | 'split'>('unified')
const commitMsg = ref('')

// 文件级展开状态、Hunk 间隙扩展窗口与行内评审输入框状态
const openFiles = reactive<Record<string, boolean>>({})
const gapWindows = reactive<Record<string, { top: number; bottom: number; all?: boolean }>>({})
const loadingContextFiles = reactive<Record<string, boolean>>({})

const activeCommentTarget = ref<{
  filePath: string
  rowKey: string
  lineNo: number
  codeText: string
} | null>(null)
const commentDraft = ref('')

const latestCheckpoint = computed(() => {
  const list = [...props.checkpoints].reverse()
  return list.find(c => !c.reverted) ?? null
})

watch(
  () => props.sessionKey,
  () => {
    activeCommentTarget.value = null
    commentDraft.value = ''
    for (const k of Object.keys(loadingContextFiles)) delete loadingContextFiles[k]
  },
)

// 监听文件列表变化初始化前 3 个默认展开，同时响应外部指定 focusFilePath 自动展开与定位
watch(
  () => [props.diff?.files, props.focusFilePath] as const,
  async ([files, focus]) => {
    if (!files?.length) return
    files.forEach((f, idx) => {
      if (openFiles[f.path] === undefined) {
        openFiles[f.path] = idx < 3
      }
    })
    if (focus) {
      openFiles[focus] = true
      await nextTick()
      const card = drawerBodyRef.value?.querySelector(`[data-diff-path="${CSS.escape(focus)}"]`)
      if (card && typeof (card as HTMLElement).scrollIntoView === 'function') {
        ;(card as HTMLElement).scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  },
  { immediate: true },
)

// 当节点完整文本回包到达时取消加载状态标记
watch(
  () => (props.sessionKey ? fleet.fileTextCacheBySession[props.sessionKey] : undefined),
  cache => {
    if (!cache) return
    for (const k of Object.keys(loadingContextFiles)) {
      if (cache[k]) delete loadingContextFiles[k]
    }
  },
  { deep: true },
)

function onFileToggle(path: string, ev: Event) {
  const el = ev.target as HTMLDetailsElement | null
  if (!el) return
  const next = Boolean(el.open)
  if (Boolean(openFiles[path]) === next) return
  openFiles[path] = next
}

function onCheckpointChange(ev: Event) {
  const val = (ev.target as HTMLSelectElement).value
  emit('selectCheckpoint', val || undefined)
}

function handleCommit() {
  const msg = commitMsg.value.trim()
  if (!msg) return
  emit('commitChanges', msg)
  commitMsg.value = ''
}

// 语言识别与单行/全文语法高亮缓存（按文件内容一次词法遍历保持多行状态准确）
const highlightedFullFileByPath = computed<Record<string, HighlightSpan[][]>>(() => {
  const sKey = props.sessionKey
  if (!sKey) return {}
  const cache = fleet.fileTextCacheBySession[sKey]
  if (!cache) return {}
  const out: Record<string, HighlightSpan[][]> = {}
  for (const file of props.diff?.files ?? []) {
    const lines = cache[file.path]
    if (lines?.length) {
      out[file.path] = highlightCode(lines.join('\n'), inferLanguageFromPath(file.path))
    }
  }
  return out
})

function getFullFileLines(path: string): string[] | undefined {
  if (!props.sessionKey) return undefined
  return fleet.fileTextCacheBySession[props.sessionKey]?.[path]
}

function highlightDiffText(filePath: string, text: string): HighlightSpan[] {
  const lang = inferLanguageFromPath(filePath)
  return highlightCode(text, lang)[0] ?? [{ kind: 'plain', text }]
}

function getContextLineSpans(filePath: string, newLineNo: number, rawText: string): HighlightSpan[] {
  const fullSpans = highlightedFullFileByPath.value[filePath]?.[newLineNo - 1]
  if (fullSpans) return fullSpans
  return highlightDiffText(filePath, rawText)
}

function gapKey(filePath: string, segId: string): string {
  return `${filePath}::${segId}`
}

function ensureContextLoaded(filePath: string) {
  const lines = getFullFileLines(filePath)
  if (lines?.length) return true
  if (props.sessionKey) {
    loadingContextFiles[filePath] = true
    fleet.requestDiffFileContext(filePath, props.sessionKey)
  }
  return false
}

function expandGap(filePath: string, seg: DiffGapSegment, dir: 'up' | 'down' | 'all') {
  ensureContextLoaded(filePath)
  const k = gapKey(filePath, seg.id)
  const total = seg.endNewLine - seg.startNewLine + 1
  const cur = gapWindows[k] ?? { top: 0, bottom: 0 }
  if (dir === 'all' || cur.top + cur.bottom + 10 >= total) {
    gapWindows[k] = { top: total, bottom: 0, all: true }
    return
  }
  if (dir === 'down') {
    gapWindows[k] = { top: cur.top + 10, bottom: cur.bottom }
  } else {
    gapWindows[k] = { top: cur.top, bottom: cur.bottom + 10 }
  }
}

interface GapRenderView {
  topLines: Array<{ oldNo: number; newNo: number; text: string }>
  bottomLines: Array<{ oldNo: number; newNo: number; text: string }>
  remainingCount: number
}

function getGapView(filePath: string, seg: DiffGapSegment | null): GapRenderView | null {
  if (!seg) return null
  const total = seg.endNewLine - seg.startNewLine + 1
  if (total <= 0) return null
  const k = gapKey(filePath, seg.id)
  const win = gapWindows[k]
  const rawLines = getFullFileLines(filePath)
  if (!win || !rawLines?.length) {
    return { topLines: [], bottomLines: [], remainingCount: total }
  }
  if (win.all || win.top + win.bottom >= total) {
    const allLines: Array<{ oldNo: number; newNo: number; text: string }> = []
    for (let n = seg.startNewLine; n <= seg.endNewLine; n += 1) {
      allLines.push({
        newNo: n,
        oldNo: n + seg.oldDelta,
        text: rawLines[n - 1] ?? '',
      })
    }
    return { topLines: allLines, bottomLines: [], remainingCount: 0 }
  }

  const topEnd = Math.min(seg.startNewLine + win.top - 1, seg.endNewLine)
  const botStart = Math.max(topEnd + 1, seg.endNewLine - win.bottom + 1)
  const topLines: Array<{ oldNo: number; newNo: number; text: string }> = []
  for (let n = seg.startNewLine; n <= topEnd; n += 1) {
    topLines.push({ newNo: n, oldNo: n + seg.oldDelta, text: rawLines[n - 1] ?? '' })
  }
  const bottomLines: Array<{ oldNo: number; newNo: number; text: string }> = []
  for (let n = botStart; n <= seg.endNewLine; n += 1) {
    bottomLines.push({ newNo: n, oldNo: n + seg.oldDelta, text: rawLines[n - 1] ?? '' })
  }
  const remainingCount = Math.max(0, botStart - topEnd - 1)
  return { topLines, bottomLines, remainingCount }
}

interface FileDiffPresentation {
  file: DiffFileEntry
  meta: ReturnType<typeof splitDiffPath>
  hunks: DiffHunk[]
  gaps: ReturnType<typeof computeHunkGaps>
}

const filePresentations = computed<FileDiffPresentation[]>(() =>
  (props.diff?.files ?? []).map(file => {
    const hunks = file.patch ? parseDiffHunks(file.patch) : []
    const fullLines = getFullFileLines(file.path)
    return {
      file,
      meta: splitDiffPath(file.path),
      hunks,
      gaps: computeHunkGaps(hunks, fullLines?.length),
    }
  }),
)

function openLineComment(filePath: string, rowKey: string, lineNo: number | undefined, codeText: string) {
  const ln = lineNo && lineNo > 0 ? lineNo : 1
  if (activeCommentTarget.value?.rowKey === rowKey) {
    activeCommentTarget.value = null
    return
  }
  activeCommentTarget.value = { filePath, rowKey, lineNo: ln, codeText }
  commentDraft.value = ''
}

function submitLineComment() {
  const target = activeCommentTarget.value
  if (!target) return
  const note = commentDraft.value.trim()
  const snippet = target.codeText.trim().slice(0, 80)
  const citation = `@${target.filePath}#L${target.lineNo}`
  const text = note
    ? `${citation}${snippet ? ` (\`${snippet}\`)` : ''} ${note}`
    : `${citation} 请检查这一行实现`
  emit('commentLine', text)
  activeCommentTarget.value = null
  commentDraft.value = ''
}

function splitLines(file: DiffFileEntry): string[] {
  return (file.patch || '').split('\n')
}

function lineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff --git')) return 'is-meta'
  if (line.startsWith('@@')) return 'is-hunk'
  if (line.startsWith('+')) return 'is-add'
  if (line.startsWith('-')) return 'is-del'
  return ''
}
</script>

<template>
  <div class="diff-drawer">
    <header class="diff-hdr">
      <div class="diff-hdr-title">
        <template v-if="!embedded">
          <OpusIcon name="branch" class="diff-hdr-ic" />
          <span>代码评审</span>
        </template>
        <span v-if="diff?.summary?.filesChanged" class="diff-sum num">
          <b class="sum-add">+{{ diff.summary.additions }}</b>
          <b class="sum-del">-{{ diff.summary.deletions }}</b>
          <span>· {{ diff.summary.filesChanged }} 文件</span>
        </span>
      </div>
      <div class="diff-hdr-actions">
        <div class="diff-mode-seg" role="group" aria-label="Diff 对比视图模式">
          <button
            type="button"
            class="diff-mode-btn"
            :class="{ 'is-active': diffMode === 'unified' }"
            @click="diffMode = 'unified'"
          >Unified</button>
          <button
            type="button"
            class="diff-mode-btn"
            :class="{ 'is-active': diffMode === 'split' }"
            @click="diffMode = 'split'"
          >并排</button>
        </div>
        <select
          v-if="checkpoints.length"
          class="diff-cp-select"
          :value="selectedCheckpointId || ''"
          aria-label="切换查看检查点 Diff"
          @change="onCheckpointChange"
        >
          <option value="">当前工作区</option>
          <option
            v-for="(cp, idx) in checkpoints"
            :key="cp.checkpointId"
            :value="cp.checkpointId"
          >
            #{{ idx + 1 }} · {{ cp.summary.filesChanged }}文件 (+{{ cp.summary.additions }}/-{{ cp.summary.deletions }}){{ cp.reverted ? ' [已回滚]' : '' }}
          </option>
        </select>
        <button
          v-if="isWorktree"
          type="button"
          class="btn btn-subtle btn-sm"
          title="将当前隔离 Worktree 改动补丁合并回主工作区"
          @click="emit('mergeWorktree')"
        >
          <OpusIcon name="branch" />
          <span>合回主工作区</span>
        </button>
        <button
          v-if="latestCheckpoint"
          type="button"
          class="btn btn-subtle btn-sm"
          title="恢复工作区至上一检查点"
          @click="emit('revertLatest', latestCheckpoint.checkpointId)"
        >
          <OpusIcon name="history" />
          <span>回滚最近</span>
        </button>
        <button
          type="button"
          class="icon-btn"
          aria-label="刷新 Git Diff"
          title="刷新工作区 Git Diff"
          @click="emit('refresh')"
        >
          <OpusIcon name="sync" />
        </button>
        <button
          v-if="!embedded"
          type="button"
          class="icon-btn"
          aria-label="关闭变更审查面板"
          title="关闭变更审查"
          @click="emit('close')"
        >
          <OpusIcon name="x" />
        </button>
      </div>
    </header>

    <div ref="drawerBodyRef" class="diff-body">
      <div v-if="!diff" class="diff-empty">
        <p class="faint">点击右上角刷新以扫描当前工作目录的 Git 变更。</p>
        <button type="button" class="btn btn-primary btn-sm" @click="emit('refresh')">扫描工作区 Diff</button>
      </div>

      <div v-else-if="diff.isGitRepo === false" class="diff-empty">
        <OpusIcon name="info" class="diff-empty-ic" />
        <p class="faint">当前会话目录尚未初始化 Git 仓库，无法生成文件 Diff 与检查点回滚。</p>
      </div>

      <div v-else-if="!diff.files.length" class="diff-empty">
        <OpusIcon name="check" class="diff-empty-ic is-clean" />
        <p class="faint">工作区干净，暂无未提交的代码变更。</p>
      </div>

      <div v-else class="diff-files">
        <form class="diff-commit-bar" @submit.prevent="handleCommit">
          <input
            v-model="commitMsg"
            type="text"
            class="input diff-commit-input"
            placeholder="输入 Commit 信息，一键提交当前全部变更…"
            aria-label="Git Commit 信息"
          />
          <button
            type="submit"
            class="btn btn-primary btn-sm"
            :disabled="!commitMsg.trim() || loading"
          >
            <OpusIcon name="check" />
            <span>提交 Git</span>
          </button>
        </form>

        <details
          v-for="{ file, meta, hunks, gaps } in filePresentations"
          :key="file.path"
          :data-diff-path="file.path"
          class="diff-file"
          :open="Boolean(openFiles[file.path])"
          @toggle="onFileToggle(file.path, $event)"
        >
          <summary class="diff-file-head">
            <span class="diff-lang-badge" :class="`is-${meta.badgeTone}`">{{ meta.badge }}</span>
            <span class="diff-file-name">{{ meta.fileName }}</span>
            <span v-if="meta.dirName" class="diff-file-dir" :title="file.path">{{ meta.dirName }}</span>
            <span class="diff-stats num">
              <span v-if="file.additions" class="sum-add">+{{ file.additions }}</span>
              <span v-if="file.deletions" class="sum-del">-{{ file.deletions }}</span>
            </span>
            <OpusIcon name="chevD" class="diff-chev" />
          </summary>

          <div class="diff-patch-wrap">
            <div class="diff-patch-bar">
              <code class="diff-patch-path">{{ file.path }}</code>
              <div class="diff-file-btns">
                <button type="button" class="btn btn-subtle btn-sm" @click="emit('openFile', file.path)">
                  <OpusIcon name="eye" />
                  <span>查看全文</span>
                </button>
                <button type="button" class="btn btn-subtle btn-sm" @click="emit('askAboutFile', file.path)">
                  <OpusIcon name="chat" />
                  <span>追问</span>
                </button>
                <button
                  type="button"
                  class="btn btn-subtle btn-sm is-warn-text"
                  title="仅还原这一个文件的修改"
                  @click="emit('revertFiles', [file.path], selectedCheckpointId || undefined)"
                >
                  <OpusIcon name="history" />
                  <span>撤销此文件</span>
                </button>
              </div>
            </div>

            <template v-if="hunks.length">
              <!-- 顶部上下文省略区间 (+N more lines) -->
              <template v-if="diffMode === 'unified' && gaps.beforeFirst">
                <template v-for="gapView in [getGapView(file.path, gaps.beforeFirst)]" :key="gaps.beforeFirst.id">
                  <template v-if="gapView">
                    <div
                      v-for="cl in gapView.topLines"
                      :key="`top-up-${cl.newNo}`"
                      class="diff-u-row is-ctx"
                    >
                      <span class="du-act">
                        <button
                          type="button"
                          class="du-plus-btn"
                          :title="`针对第 ${cl.newNo} 行向 AI 发起评审或修改意见`"
                          @click="openLineComment(file.path, `${file.path}-c-${cl.newNo}`, cl.newNo, cl.text)"
                        >+</button>
                      </span>
                      <span class="du-ln num">{{ cl.oldNo }}</span>
                      <span class="du-ln num">{{ cl.newNo }}</span>
                      <span class="du-code"><span v-for="(sp, sIdx) in getContextLineSpans(file.path, cl.newNo, cl.text)" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span><template v-if="!cl.text">&nbsp;</template></span>
                    </div>

                    <div v-if="gapView.remainingCount > 0" class="diff-gap-bar">
                      <button
                        type="button"
                        class="diff-gap-pill"
                        :title="`展开上方 ${gapView.remainingCount} 行源码`"
                        @click="expandGap(file.path, gaps.beforeFirst!, 'all')"
                      >
                        <span v-if="loadingContextFiles[file.path]">正在读取上下文…</span>
                        <span v-else>+{{ gapView.remainingCount }} more lines</span>
                      </button>
                      <button
                        v-if="gapView.remainingCount > 10"
                        type="button"
                        class="diff-gap-step"
                        title="紧邻 Hunk 向上展开 10 行"
                        @click="expandGap(file.path, gaps.beforeFirst!, 'up')"
                      >↑ +10</button>
                    </div>

                    <div
                      v-for="cl in gapView.bottomLines"
                      :key="`top-dn-${cl.newNo}`"
                      class="diff-u-row is-ctx"
                    >
                      <span class="du-act">
                        <button
                          type="button"
                          class="du-plus-btn"
                          :title="`针对第 ${cl.newNo} 行向 AI 发起评审或修改意见`"
                          @click="openLineComment(file.path, `${file.path}-c-${cl.newNo}`, cl.newNo, cl.text)"
                        >+</button>
                      </span>
                      <span class="du-ln num">{{ cl.oldNo }}</span>
                      <span class="du-ln num">{{ cl.newNo }}</span>
                      <span class="du-code"><span v-for="(sp, sIdx) in getContextLineSpans(file.path, cl.newNo, cl.text)" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span><template v-if="!cl.text">&nbsp;</template></span>
                    </div>
                  </template>
                </template>
              </template>

              <template v-for="(hunk, hIdx) in hunks" :key="`${file.path}-h-${hunk.index}`">
                <!-- Hunk 顶部控制条（带分块撤销按钮） -->
                <div class="diff-hunk-bar">
                  <code class="diff-hunk-hdr">{{ hunk.header }}</code>
                  <button
                    type="button"
                    class="diff-hunk-revert"
                    title="仅撤销此 Hunk 代码块的变更"
                    @click="emit('revertHunk', file.path, hunk.rawPatch)"
                  >
                    <OpusIcon name="history" />
                    <span>撤销此块</span>
                  </button>
                </div>

                <!-- Split 并排对比模式（含语法高亮） -->
                <div v-if="diffMode === 'split'" class="diff-split-scroll">
                  <table class="diff-split-tbl">
                    <tbody>
                      <tr v-for="(row, rIdx) in toSplitDiffRows(hunk)" :key="rIdx">
                        <td class="ds-ln num" :class="`is-${row.leftKind}`">{{ row.leftNo ?? '' }}</td>
                        <td class="ds-code" :class="`is-${row.leftKind}`"><template v-if="row.leftKind !== 'empty'"><span v-for="(sp, sIdx) in highlightDiffText(file.path, row.leftText || '')" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span></template><template v-else>&nbsp;</template></td>
                        <td class="ds-ln num ds-mid" :class="`is-${row.rightKind}`">{{ row.rightNo ?? '' }}</td>
                        <td class="ds-code" :class="`is-${row.rightKind}`"><template v-if="row.rightKind !== 'empty'"><span v-for="(sp, sIdx) in highlightDiffText(file.path, row.rightText || '')" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span></template><template v-else>&nbsp;</template></td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <!-- Unified 视图（图 1 风格：双列行号 + 全语法高亮 + 悬停 + 行评论） -->
                <div v-else class="diff-u-table">
                  <template v-for="(dl, lIdx) in hunk.lines" :key="`${hunk.index}-${lIdx}`">
                    <div
                      class="diff-u-row"
                      :class="[
                        `is-${dl.kind}`,
                        { 'is-commenting': activeCommentTarget?.rowKey === `${file.path}-h${hunk.index}-l${lIdx}` },
                      ]"
                    >
                      <span class="du-act">
                        <button
                          type="button"
                          class="du-plus-btn"
                          :title="`针对第 ${dl.newNo ?? dl.oldNo ?? 1} 行发起评审意见`"
                          @click="openLineComment(file.path, `${file.path}-h${hunk.index}-l${lIdx}`, dl.newNo ?? dl.oldNo, dl.text)"
                        >+</button>
                      </span>
                      <span class="du-ln num">{{ dl.oldNo ?? '' }}</span>
                      <span class="du-ln num">{{ dl.newNo ?? '' }}</span>
                      <span class="du-code"><span v-for="(sp, sIdx) in highlightDiffText(file.path, dl.text)" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span><template v-if="!dl.text">&nbsp;</template></span>
                    </div>

                    <form
                      v-if="activeCommentTarget?.rowKey === `${file.path}-h${hunk.index}-l${lIdx}`"
                      class="diff-inline-comment"
                      @submit.prevent="submitLineComment"
                    >
                      <span class="dic-badge num">L{{ activeCommentTarget.lineNo }}</span>
                      <input
                        v-model="commentDraft"
                        type="text"
                        class="input dic-input"
                        placeholder="写下针对该行的修改意见或疑问，回车插入对话…"
                        autofocus
                      />
                      <button type="submit" class="btn btn-primary btn-sm">加入对话</button>
                      <button type="button" class="btn btn-ghost btn-sm" @click="activeCommentTarget = null">取消</button>
                    </form>
                  </template>
                </div>

                <!-- 相邻 Hunk 间隙展开带 (+N more lines) -->
                <template v-if="diffMode === 'unified' && gaps.between[hIdx]">
                  <template v-for="gapView in [getGapView(file.path, gaps.between[hIdx])]" :key="gaps.between[hIdx]!.id">
                    <template v-if="gapView">
                      <div v-for="cl in gapView.topLines" :key="`mid-up-${cl.newNo}`" class="diff-u-row is-ctx">
                        <span class="du-act">
                          <button
                            type="button"
                            class="du-plus-btn"
                            :title="`针对第 ${cl.newNo} 行向 AI 发起评审或修改意见`"
                            @click="openLineComment(file.path, `${file.path}-c-${cl.newNo}`, cl.newNo, cl.text)"
                          >+</button>
                        </span>
                        <span class="du-ln num">{{ cl.oldNo }}</span>
                        <span class="du-ln num">{{ cl.newNo }}</span>
                        <span class="du-code"><span v-for="(sp, sIdx) in getContextLineSpans(file.path, cl.newNo, cl.text)" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span><template v-if="!cl.text">&nbsp;</template></span>
                      </div>

                      <div v-if="gapView.remainingCount > 0" class="diff-gap-bar">
                        <button
                          v-if="gapView.remainingCount > 10"
                          type="button"
                          class="diff-gap-step"
                          title="向下展开 10 行"
                          @click="expandGap(file.path, gaps.between[hIdx]!, 'down')"
                        >↓ +10</button>
                        <button
                          type="button"
                          class="diff-gap-pill"
                          :title="`展开中间全部 ${gapView.remainingCount} 行源码`"
                          @click="expandGap(file.path, gaps.between[hIdx]!, 'all')"
                        >
                          <span v-if="loadingContextFiles[file.path]">正在读取上下文…</span>
                          <span v-else>+{{ gapView.remainingCount }} more lines</span>
                        </button>
                        <button
                          v-if="gapView.remainingCount > 10"
                          type="button"
                          class="diff-gap-step"
                          title="向上展开 10 行"
                          @click="expandGap(file.path, gaps.between[hIdx]!, 'up')"
                        >↑ +10</button>
                      </div>

                      <div v-for="cl in gapView.bottomLines" :key="`mid-dn-${cl.newNo}`" class="diff-u-row is-ctx">
                        <span class="du-act">
                          <button
                            type="button"
                            class="du-plus-btn"
                            :title="`针对第 ${cl.newNo} 行向 AI 发起评审或修改意见`"
                            @click="openLineComment(file.path, `${file.path}-c-${cl.newNo}`, cl.newNo, cl.text)"
                          >+</button>
                        </span>
                        <span class="du-ln num">{{ cl.oldNo }}</span>
                        <span class="du-ln num">{{ cl.newNo }}</span>
                        <span class="du-code"><span v-for="(sp, sIdx) in getContextLineSpans(file.path, cl.newNo, cl.text)" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span><template v-if="!cl.text">&nbsp;</template></span>
                      </div>
                    </template>
                  </template>
                </template>
              </template>

              <!-- 末尾剩余文件上下文展开带 -->
              <template v-if="diffMode === 'unified' && gaps.afterLast">
                <template v-for="gapView in [getGapView(file.path, gaps.afterLast)]" :key="gaps.afterLast.id">
                  <template v-if="gapView">
                    <div v-for="cl in gapView.topLines" :key="`tail-${cl.newNo}`" class="diff-u-row is-ctx">
                      <span class="du-act">
                        <button
                          type="button"
                          class="du-plus-btn"
                          :title="`针对第 ${cl.newNo} 行向 AI 发起评审或修改意见`"
                          @click="openLineComment(file.path, `${file.path}-c-${cl.newNo}`, cl.newNo, cl.text)"
                        >+</button>
                      </span>
                      <span class="du-ln num">{{ cl.oldNo }}</span>
                      <span class="du-ln num">{{ cl.newNo }}</span>
                      <span class="du-code"><span v-for="(sp, sIdx) in getContextLineSpans(file.path, cl.newNo, cl.text)" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span><template v-if="!cl.text">&nbsp;</template></span>
                    </div>
                    <div v-if="gapView.remainingCount > 0" class="diff-gap-bar">
                      <button
                        type="button"
                        class="diff-gap-step"
                        @click="expandGap(file.path, gaps.afterLast!, 'down')"
                      >↓ +10</button>
                      <button
                        type="button"
                        class="diff-gap-pill"
                        @click="expandGap(file.path, gaps.afterLast!, 'all')"
                      >+{{ gapView.remainingCount }} more lines</button>
                    </div>
                  </template>
                </template>
              </template>
            </template>

            <pre v-else-if="file.patch" class="diff-patch"><code v-for="(line, lIdx) in splitLines(file)" :key="lIdx" class="diff-line" :class="lineClass(line)">{{ line || ' ' }}</code></pre>
            <p v-else class="diff-binary faint">二进制或空文件变更</p>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: var(--surface-1);
}
.diff-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px 6px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.diff-hdr-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
}
.diff-hdr-ic { width: 14px; height: 14px; color: var(--accent); flex: none; }
.diff-sum {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
}
.sum-add { color: var(--ok); }
.sum-del { color: var(--warn); }
.diff-hdr-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  flex: none;
}
.diff-mode-seg {
  display: inline-flex;
  padding: 1px;
  border-radius: 6px;
  border: 1px solid var(--line-strong);
  background: var(--surface-1);
}
.diff-mode-btn {
  padding: 2px 7px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-3);
  font-size: 11px;
  cursor: pointer;
}
.diff-mode-btn.is-active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.diff-cp-select {
  max-width: 155px;
  padding: 3px 6px;
  border-radius: var(--r-xs);
  border: 1px solid var(--line-strong);
  background: var(--surface-1);
  color: var(--text);
  font-size: 11px;
}
.diff-commit-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
}
.diff-commit-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 8px;
  font-size: 12px;
}
.diff-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 10px;
}
.diff-empty {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 36px 18px;
  text-align: center;
  font-size: 12.5px;
}
.diff-empty-ic { width: 24px; height: 24px; color: var(--text-3); }
.diff-empty-ic.is-clean { color: var(--ok); }
.diff-files {
  display: grid;
  gap: 10px;
}
.diff-file {
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--solid);
  overflow: hidden;
}
.diff-file-head {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 7px;
  min-block-size: 32px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  background: var(--surface-2);
}
.diff-file-head::-webkit-details-marker { display: none; }
.diff-file-head:hover { background: var(--surface-3); }
.diff-lang-badge {
  flex: none;
  min-width: 22px;
  height: 18px;
  padding: 0 3px;
  border-radius: 4px;
  display: inline-grid;
  place-items: center;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 700;
  background: var(--surface-3);
  color: var(--text-3);
}
.diff-lang-badge.is-ts { color: #0284c7; background: rgba(2, 132, 199, 0.12); }
.diff-lang-badge.is-vue { color: #16a34a; background: rgba(22, 163, 74, 0.12); }
.diff-lang-badge.is-py { color: #ca8a04; background: rgba(202, 138, 4, 0.14); }
.diff-lang-badge.is-js { color: #d97706; background: rgba(217, 119, 6, 0.14); }
.diff-lang-badge.is-style,
.diff-lang-badge.is-json { color: #9333ea; background: rgba(147, 51, 234, 0.12); }
.diff-file-name {
  font-weight: 650;
  color: var(--text);
  flex: none;
}
.diff-file-dir {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
  color: var(--text-3);
}
.diff-stats {
  display: inline-flex;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  flex: none;
}
.diff-chev {
  width: 13px;
  height: 13px;
  flex: none;
  color: var(--text-3);
  transform: rotate(-90deg);
  transition: transform 0.16s ease;
}
.diff-file[open] > .diff-file-head .diff-chev {
  transform: rotate(0deg);
}
.diff-patch-wrap {
  border-top: 1px solid var(--line);
}
.diff-patch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-1);
}
.diff-patch-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-3);
}
.diff-file-btns {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.is-warn-text { color: var(--warn); }

.diff-hunk-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 10px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--accent-soft) 55%, var(--surface-1));
  color: var(--text-3);
}
.diff-hunk-hdr {
  font-family: var(--mono);
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.diff-hunk-revert {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border: 1px solid color-mix(in srgb, var(--warn) 38%, var(--line));
  border-radius: 4px;
  background: var(--solid);
  color: var(--warn);
  font-size: 10.5px;
  cursor: pointer;
  flex: none;
}
.diff-hunk-revert:hover { background: var(--warn-soft); }
.diff-hunk-revert .i { width: 11px; height: 11px; }

/* 图 1 样式统一 Diff 行：双行号列 + 悬停蓝色 + 评论按钮 + 语法高亮保留前景 */
.diff-u-table {
  overflow-x: auto;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
}
.diff-u-row {
  display: flex;
  align-items: stretch;
  min-width: 100%;
  width: max-content;
}
.diff-u-row:hover {
  background-color: color-mix(in srgb, var(--surface-2) 60%, transparent);
}
.diff-u-row.is-add {
  background-color: var(--diff-add-bg, rgba(22, 163, 74, 0.12));
}
.diff-u-row.is-del {
  background-color: var(--diff-del-bg, rgba(220, 38, 38, 0.11));
}
.du-act {
  width: 24px;
  flex: none;
  display: grid;
  place-items: center;
}
.du-plus-btn {
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  display: grid;
  place-items: center;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.diff-u-row:hover .du-plus-btn,
.diff-u-row:focus-within .du-plus-btn,
.diff-u-row.is-commenting .du-plus-btn {
  opacity: 1;
}
.du-plus-btn:hover { transform: scale(1.1); }
.du-ln {
  width: 34px;
  flex: none;
  padding: 0 5px;
  text-align: right;
  font-size: 11px;
  color: var(--text-3);
  user-select: none;
}
.diff-u-row.is-add .du-ln {
  background-color: var(--diff-add-gutter, rgba(22, 163, 74, 0.22));
}
.diff-u-row.is-del .du-ln {
  background-color: var(--diff-del-gutter, rgba(220, 38, 38, 0.20));
}
.du-code {
  flex: 1;
  padding: 0 12px 0 8px;
  white-space: pre;
  color: var(--text);
}
.diff-u-row.is-del .du-code {
  opacity: 0.86;
}

.diff-inline-comment {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px 6px 26px;
  background: color-mix(in srgb, var(--accent-soft) 45%, var(--surface-1));
  border-top: 1px solid var(--accent-line);
  border-bottom: 1px solid var(--accent-line);
}
.dic-badge {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--accent);
  color: #fff;
  font-size: 10.5px;
  font-weight: 600;
  flex: none;
}
.dic-input {
  flex: 1;
  min-width: 0;
  height: 26px;
  padding: 0 8px;
  font-family: var(--font-sans, inherit);
  font-size: 12px;
}

/* Hunk 间隙展开分隔条 (+N more lines) */
.diff-gap-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--diff-gap-bg, var(--surface-1));
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.diff-gap-pill,
.diff-gap-step {
  padding: 2px 9px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--solid);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
}
.diff-gap-pill:hover,
.diff-gap-step:hover {
  border-color: var(--accent-line);
  color: var(--accent);
  background: var(--accent-soft);
}

/* Split 并排对比模式同样保留语法高亮 */
.diff-split-scroll {
  overflow: auto;
  max-height: 440px;
}
.diff-split-tbl {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.5;
  table-layout: fixed;
}
.ds-ln {
  width: 36px;
  padding: 0 6px;
  text-align: right;
  font-size: 11px;
  color: var(--text-3);
  user-select: none;
  border-right: 1px solid var(--line);
}
.ds-ln.ds-mid {
  border-left: 1px solid var(--line-strong);
}
.ds-code {
  padding: 0 8px;
  white-space: pre-wrap;
  word-break: break-word;
  vertical-align: top;
  color: var(--text);
}
.ds-ln.is-add { background: var(--diff-add-gutter, rgba(22, 163, 74, 0.2)); }
.ds-code.is-add { background: var(--diff-add-bg, rgba(22, 163, 74, 0.12)); }
.ds-ln.is-del { background: var(--diff-del-gutter, rgba(220, 38, 38, 0.2)); }
.ds-code.is-del { background: var(--diff-del-bg, rgba(220, 38, 38, 0.11)); opacity: 0.86; }
.ds-ln.is-empty,
.ds-code.is-empty {
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
}

.diff-patch {
  margin: 0;
  padding: 6px 0;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.45;
  overflow-x: auto;
}
.diff-line {
  display: block;
  padding: 0 10px;
  white-space: pre;
}
.diff-line.is-add { background: var(--diff-add-bg); color: var(--ok); }
.diff-line.is-del { background: var(--diff-del-bg); color: var(--warn); }
.diff-line.is-hunk { background: var(--accent-soft); color: var(--accent); }
.diff-line.is-meta { color: var(--text-3); }
.diff-binary { margin: 0; padding: 10px; font-size: 12px; }

/* 复用全站双主题语义语法高亮变量 */
.tok-keyword { color: var(--tok-keyword, #9333ea); font-weight: 500; }
.tok-string { color: var(--tok-string, #15803d); }
.tok-number { color: var(--tok-number, #b45309); }
.tok-comment { color: var(--tok-comment, #64748b); font-style: italic; }
.tok-type { color: var(--tok-type, #0369a1); }
.tok-operator { color: var(--tok-operator, #475569); }
.tok-punct { color: var(--tok-punct, #64748b); }
.tok-tag { color: var(--tok-tag, #be123c); }
.tok-attr { color: var(--tok-attr, #0f766e); }
.tok-property { color: var(--tok-property, #1d4ed8); }
.tok-diffAdd { color: var(--tok-diffAdd, var(--ok)); }
.tok-diffDel { color: var(--tok-diffDel, var(--warn)); }
.tok-diffMeta { color: var(--tok-diffMeta, var(--accent)); font-weight: 600; }
</style>
