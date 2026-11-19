<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { highlightCode, inferLanguageFromPath } from '../../services/syntaxHighlight'
import type { FileBlameLine, FilePreviewState } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  preview: FilePreviewState | null
}>()

const emit = defineEmits<{
  close: []
  refresh: [path: string]
  citeLines: [citation: string]
  askAboutFile: [path: string]
  saveFile: [path: string, content: string]
  requestBlame: [path: string]
  openExternal: [path: string]
}>()

const selStart = ref<number | null>(null)
const selEnd = ref<number | null>(null)
const copied = ref(false)
const editMode = ref(false)
const editDraft = ref('')
const showBlame = ref(false)
const bodyRef = ref<HTMLElement | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.preview?.path,
  () => {
    editMode.value = false
    showBlame.value = false
    editDraft.value = props.preview?.content ?? ''
  },
)

const blameMap = computed(() => {
  const map = new Map<number, FileBlameLine>()
  for (const row of props.preview?.blame ?? []) {
    map.set(row.line, row)
  }
  return map
})

function formatBlameDate(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function toggleEditMode() {
  if (!props.preview || props.preview.isBinary || props.preview.truncated) return
  if (!editMode.value) {
    editDraft.value = props.preview.content
    editMode.value = true
  } else {
    editMode.value = false
  }
}

function handleSaveFile() {
  if (!props.preview || props.preview.saving) return
  emit('saveFile', props.preview.path, editDraft.value)
  editMode.value = false
}

function handleEditorKeydown(ev: KeyboardEvent) {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') {
    ev.preventDefault()
    handleSaveFile()
  } else if (ev.key === 'Escape') {
    ev.preventDefault()
    editMode.value = false
  }
}

function toggleBlameView() {
  if (!props.preview || props.preview.isBinary) return
  showBlame.value = !showBlame.value
  if (showBlame.value && !props.preview.blame?.length && !props.preview.blameLoading) {
    emit('requestBlame', props.preview.path)
  }
}

watch(
  () => [props.preview?.path, props.preview?.highlightLine, props.preview?.loading] as const,
  async ([, hl, loading]) => {
    if (typeof hl === 'number' && hl > 0) {
      selStart.value = hl
      selEnd.value = hl
      if (!loading) {
        await nextTick()
        const target = bodyRef.value?.querySelector(`.fv-line[data-line="${hl}"]`)
        if (target && typeof (target as HTMLElement).scrollIntoView === 'function') {
          ;(target as HTMLElement).scrollIntoView({ block: 'center' })
        }
      }
    } else {
      selStart.value = null
      selEnd.value = null
    }
  },
  { immediate: true },
)

const lang = computed(() => {
  if (!props.preview) return 'plain'
  return props.preview.language || inferLanguageFromPath(props.preview.path)
})

const highlightedLines = computed(() => {
  if (!props.preview || props.preview.isBinary || !props.preview.content) return []
  return highlightCode(props.preview.content, lang.value)
})

const selectedRange = computed<{ start: number; end: number } | null>(() => {
  if (selStart.value === null) return null
  const a = selStart.value
  const b = selEnd.value ?? a
  return { start: Math.min(a, b), end: Math.max(a, b) }
})

const sizeText = computed(() => {
  const bytes = props.preview?.sizeBytes ?? 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
})

function selectLine(lineNo: number, ev: MouseEvent) {
  if (ev.shiftKey && selStart.value !== null) {
    selEnd.value = lineNo
  } else if (selStart.value === lineNo && selEnd.value === lineNo) {
    selStart.value = null
    selEnd.value = null
  } else {
    selStart.value = lineNo
    selEnd.value = lineNo
  }
}

function isLineSelected(lineNo: number): boolean {
  if (!selectedRange.value) return false
  return lineNo >= selectedRange.value.start && lineNo <= selectedRange.value.end
}

function citeSelection() {
  if (!props.preview) return
  if (selectedRange.value) {
    const { start, end } = selectedRange.value
    const refStr = start === end ? `@${props.preview.path}#L${start}` : `@${props.preview.path}#L${start}-L${end}`
    emit('citeLines', refStr)
    return
  }
  emit('citeLines', `@${props.preview.path}`)
}

const isImagePreview = computed(() =>
  Boolean(props.preview?.mime?.startsWith('image/') && props.preview?.base64Data),
)

const imageDataUrl = computed(() =>
  isImagePreview.value && props.preview
    ? `data:${props.preview.mime};base64,${props.preview.base64Data}`
    : '',
)

const canDownloadFile = computed(() =>
  Boolean(props.preview && (props.preview.base64Data || (!props.preview.isBinary && props.preview.content !== undefined))),
)

function downloadCurrentFile() {
  const p = props.preview
  if (!p) return
  const fileName = p.path.replace(/\\/g, '/').split('/').pop() || 'download'
  let href = ''
  let revokeNeeded = false
  if (p.base64Data) {
    href = `data:${p.mime || 'application/octet-stream'};base64,${p.base64Data}`
  } else {
    const blob = new Blob([p.content || ''], { type: `${p.mime || 'text/plain'};charset=utf-8` })
    href = URL.createObjectURL(blob)
    revokeNeeded = true
  }
  const a = document.createElement('a')
  a.href = href
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  if (revokeNeeded) {
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  }
}

async function copyContent() {
  if (!props.preview?.content || !navigator.clipboard?.writeText) return
  let payload = props.preview.content
  if (selectedRange.value) {
    const rawLines = props.preview.content.replace(/\r\n/g, '\n').split('\n')
    payload = rawLines.slice(selectedRange.value.start - 1, selectedRange.value.end).join('\n')
  }
  try {
    await navigator.clipboard.writeText(payload)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copied.value = false
      copyTimer = null
    }, 1500)
  } catch {
    // 剪贴板权限受限时静默忽略
  }
}

onUnmounted(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <section class="fv-drawer" aria-label="代码文件只读预览">
    <header class="fv-hdr">
      <div class="fv-title-wrap">
        <OpusIcon name="file" class="fv-hdr-ic" />
        <code class="fv-path" :title="preview?.path">{{ preview?.path || '未选择文件' }}</code>
        <span v-if="preview" class="fv-meta num">
          {{ lang !== 'plain' ? lang.toUpperCase() : 'TEXT' }} · {{ preview.lineCount }} 行 · {{ sizeText }}
        </span>
      </div>
      <div class="fv-actions">
        <button
          v-if="preview && !preview.isBinary && !editMode"
          type="button"
          class="btn btn-subtle btn-sm"
          :class="{ 'is-active-btn': showBlame }"
          title="切换显示每行 Git Blame 提交信息"
          @click="toggleBlameView"
        >
          <OpusIcon name="history" />
          <span>{{ preview.blameLoading ? '加载…' : 'Blame' }}</span>
        </button>
        <button
          v-if="preview && !preview.isBinary && !preview.truncated"
          type="button"
          class="btn btn-subtle btn-sm"
          :class="{ 'is-active-btn': editMode }"
          :title="editMode ? '退出编辑' : '快速编辑此文件 (Ctrl+S 保存)'"
          @click="toggleEditMode"
        >
          <OpusIcon name="pencil" />
          <span>{{ editMode ? '取消' : '编辑' }}</span>
        </button>
        <button
          v-if="preview && editMode"
          type="button"
          class="btn btn-primary btn-sm"
          :disabled="preview.saving"
          @click="handleSaveFile"
        >
          <OpusIcon name="check" />
          <span>{{ preview.saving ? '保存中…' : '保存' }}</span>
        </button>
        <button
          v-if="preview && !editMode"
          type="button"
          class="btn btn-subtle btn-sm"
          title="将文件或选中行号插入到输入框"
          @click="citeSelection"
        >
          <OpusIcon name="braces" />
          <span>{{ selectedRange ? `引用 L${selectedRange.start}${selectedRange.end !== selectedRange.start ? `-${selectedRange.end}` : ''}` : '引用' }}</span>
        </button>
        <button
          v-if="preview && !editMode"
          type="button"
          class="btn btn-subtle btn-sm"
          title="让 AI 分析此文件"
          @click="emit('askAboutFile', preview.path)"
        >
          <OpusIcon name="chat" />
          <span>追问</span>
        </button>
        <button
          v-if="canDownloadFile"
          type="button"
          class="btn btn-subtle btn-sm"
          aria-label="下载此文件"
          title="将此文件下载到本地浏览器"
          @click="downloadCurrentFile"
        >
          <OpusIcon name="download" />
          <span>下载</span>
        </button>
        <button
          v-if="preview && !preview.isBinary"
          type="button"
          class="icon-btn"
          aria-label="复制文件内容"
          :title="selectedRange ? '复制选中行' : '复制全文'"
          @click="copyContent"
        >
          <OpusIcon :name="copied ? 'check' : 'copy'" />
        </button>
        <button
          v-if="preview"
          type="button"
          class="icon-btn"
          aria-label="在外部编辑器打开"
          title="在宿主机编辑器或文件管理器中打开"
          @click="emit('openExternal', preview.path)"
        >
          <OpusIcon name="external" />
        </button>
        <button
          v-if="preview"
          type="button"
          class="icon-btn"
          aria-label="刷新文件预览"
          title="刷新文件内容"
          @click="emit('refresh', preview.path)"
        >
          <OpusIcon name="sync" />
        </button>
        <button
          type="button"
          class="icon-btn"
          aria-label="关闭文件预览"
          title="关闭文件预览"
          @click="emit('close')"
        >
          <OpusIcon name="x" />
        </button>
      </div>
    </header>

    <div ref="bodyRef" class="fv-body">
      <div v-if="!preview" class="fv-empty faint">
        点击对话中的文件路径、Diff 条目或工具参数即可在此只读预览（按住 Shift 点击行号可选中行范围）。
      </div>
      <div v-else-if="preview.loading && !preview.content" class="fv-empty faint">
        正在从远程节点安全读取文件…
      </div>
      <div v-else-if="preview.error" class="fv-empty fv-err">
        <OpusIcon name="alert" />
        <span>{{ preview.error }}</span>
      </div>
      <div v-else-if="isImagePreview" class="fv-image-stage">
        <img :src="imageDataUrl" :alt="preview.path" class="fv-image-preview" />
        <div class="fv-image-bar">
          <span class="faint">{{ preview.mime }} · {{ sizeText }}</span>
          <button type="button" class="btn btn-primary btn-sm" @click="downloadCurrentFile">
            <OpusIcon name="download" />
            <span>下载图片</span>
          </button>
        </div>
      </div>
      <div v-else-if="preview.isBinary" class="fv-empty faint">
        <OpusIcon name="info" />
        <span>二进制文件（{{ sizeText }}），已跳过文本渲染。</span>
        <button v-if="canDownloadFile" type="button" class="btn btn-primary btn-sm" @click="downloadCurrentFile">
          <OpusIcon name="download" />
          <span>下载文件</span>
        </button>
      </div>
      <template v-else>
        <div v-if="preview.truncated" class="fv-trunc-banner">
          文件超过预览阈值，仅展示前 256 KB 内容（不可直接编辑）。
        </div>
        <textarea
          v-if="editMode"
          v-model="editDraft"
          class="fv-editor"
          spellcheck="false"
          aria-label="编辑文件内容"
          @keydown="handleEditorKeydown"
        />
        <div v-else class="fv-code" role="region" aria-label="代码内容（点击行号可引用行范围）">
          <div
            v-for="(spans, idx) in highlightedLines"
            :key="idx"
            :data-line="idx + 1"
            class="fv-line"
            :class="{ 'is-sel': isLineSelected(idx + 1) }"
          >
            <span v-if="showBlame" class="fv-blame num" :title="blameMap.get(idx + 1) ? `${blameMap.get(idx + 1)!.sha} · ${blameMap.get(idx + 1)!.author}` : ''">
              <template v-if="blameMap.get(idx + 1)">
                {{ blameMap.get(idx + 1)!.author.slice(0, 8) }} · {{ formatBlameDate(blameMap.get(idx + 1)!.time) }}
              </template>
            </span>
            <button
              type="button"
              class="fv-ln num"
              :title="`选中第 ${idx + 1} 行（按住 Shift 可框选范围）`"
              @click="selectLine(idx + 1, $event)"
            >
              {{ idx + 1 }}
            </button>
            <span class="fv-lc"><template v-if="spans.length"><span v-for="(sp, sIdx) in spans" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span></template><template v-else>&nbsp;</template></span>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.fv-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  background: var(--surface-1);
}
.fv-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.fv-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.fv-hdr-ic { width: 14px; height: 14px; color: var(--accent); flex: none; }
.fv-path {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fv-meta {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}
.fv-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.fv-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.fv-empty {
  padding: 28px 18px;
  text-align: center;
  font-size: 12.5px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.fv-err { color: var(--warn); }
.fv-trunc-banner {
  padding: 6px 12px;
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  color: var(--warn);
  font-size: 11.5px;
  border-bottom: 1px solid var(--line);
}
.fv-code {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  padding: 8px 0;
}
.fv-editor {
  flex: 1;
  width: 100%;
  min-height: 260px;
  padding: 12px 14px;
  border: 0;
  outline: none;
  resize: none;
  background: var(--solid);
  color: var(--text);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
  font-size: 12px;
  line-height: 1.55;
  tab-size: 2;
}
.fv-blame {
  flex: none;
  width: 112px;
  padding: 0 8px;
  font-size: 10.5px;
  color: var(--text-3);
  border-right: 1px solid var(--line);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: none;
}
.is-active-btn {
  border-color: var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}
.fv-line {
  display: flex;
  align-items: stretch;
  padding-right: 14px;
}
.fv-line:hover { background: var(--surface-2); }
.fv-line.is-sel { background: var(--accent-soft); }
.fv-ln {
  flex: none;
  width: 48px;
  padding: 0 10px 0 8px;
  border: 0;
  background: transparent;
  color: var(--text-3);
  font-family: inherit;
  font-size: 11px;
  text-align: right;
  cursor: pointer;
  user-select: none;
}
.fv-ln:hover { color: var(--accent); }
.fv-lc {
  flex: 1;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text);
}
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
.fv-image-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  min-height: 220px;
}
.fv-image-preview {
  max-width: 100%;
  max-height: 62dvh;
  border-radius: 10px;
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  object-fit: contain;
}
.fv-image-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
</style>
