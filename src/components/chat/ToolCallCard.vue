<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { hasAnsiSequences, parseAnsiText } from '../../services/ansiParser'
import { describeToolCall } from '../../services/chatHelpers'
import { extractToolMiniDiff } from '../../services/diffHelpers'
import { useFleetStore } from '../../stores/fleet'
import type { MessageMediaItem, ToolCallBadge } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  tool: ToolCallBadge
  reveal?: { stepId: string }
}>()

const emit = defineEmits<{
  openFile: [filePath: string]
  openSubagent: [sessionId: string]
}>()

const fleet = useFleetStore()

const isOpen = ref(false)
const copiedTarget = ref<'input' | 'output' | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.reveal, reveal => {
  if (reveal) isOpen.value = true
}, { immediate: true })

function onToggle(ev: Event) {
  isOpen.value = (ev.currentTarget as HTMLDetailsElement).open
}

const description = computed(() => describeToolCall(props.tool))
const targetFilePath = computed(() => description.value.filePath)

const formattedInput = computed(() => {
  if (props.tool.input === undefined || props.tool.input === null) return ''
  if (typeof props.tool.input === 'string') return props.tool.input
  try {
    return JSON.stringify(props.tool.input, null, 2)
  } catch {
    return String(props.tool.input)
  }
})

const miniDiff = computed(() => extractToolMiniDiff(props.tool.name, props.tool.input))

const ansiOutputSpans = computed(() => {
  const out = props.tool.output || ''
  if (!out || !hasAnsiSequences(out)) return null
  return parseAnsiText(out)
})

const durationText = computed(() => {
  const ms = props.tool.durationMs
  if (ms === undefined || !Number.isFinite(ms) || ms < 0) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
})

function triggerDownloadUrl(url: string, fileName: string) {
  const cleanName = (fileName || 'download').replace(/\\/g, '/').split('/').pop() || 'download'
  const a = document.createElement('a')
  a.href = url
  a.download = cleanName
  a.target = '_blank'
  a.rel = 'noopener noreferrer'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function handleDownloadToolFile(item?: MessageMediaItem) {
  if (item?.url) {
    triggerDownloadUrl(item.url, item.fileName)
    return
  }
  if (props.tool.media?.length && props.tool.media[0].url) {
    triggerDownloadUrl(props.tool.media[0].url, props.tool.media[0].fileName)
    return
  }
  if (targetFilePath.value) {
    fleet.downloadWorkspaceFile(targetFilePath.value)
  }
}

async function copyBlock(kind: 'input' | 'output', text: string) {
  if (!text || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
    copiedTarget.value = kind
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copiedTarget.value = null
      copyTimer = null
    }, 1500)
  } catch {
    // 剪贴板写入被权限策略拦截时静默降级
  }
}

onUnmounted(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <details class="tool-card" :class="`is-${tool.status || 'completed'}`" :open="isOpen" @toggle.self="onToggle">
    <summary class="tool-card-head">
      <OpusIcon :name="description.icon" class="tool-kind-ic" />
      <span class="tool-card-label" :class="{ 'chat-progress-shimmer': tool.status === 'running' }">{{ description.label }}</span>
      <OpusIcon name="chevR" class="tool-chev" />
    </summary>

    <div v-if="isOpen" class="tool-card-body">
      <div class="tool-meta">
        <code>{{ tool.name }}</code><span v-if="durationText" class="num"> · {{ durationText }}</span>
      </div>
      <div v-if="tool.subagentSessionId || targetFilePath || tool.media?.length" class="tool-actions">
        <button v-if="tool.subagentSessionId" type="button" class="tool-pill-btn is-accent"
          @click="emit('openSubagent', tool.subagentSessionId)">打开子代理会话</button>
        <button v-if="targetFilePath" type="button" class="tool-pill-btn" :title="targetFilePath"
          @click="emit('openFile', targetFilePath)">查看文件</button>
        <button v-if="targetFilePath || tool.media?.length" type="button" class="tool-pill-btn"
          @click="handleDownloadToolFile()">下载</button>
      </div>

      <div v-if="miniDiff" class="tool-section">
        <div class="tool-sec-bar">
          <span>当步文件变更 · {{ miniDiff.filePath }}</span>
          <span v-if="miniDiff.truncated" class="faint">已截断展示</span>
        </div>
        <pre class="tool-pre tool-pre--diff"><span
          v-for="(dl, dIdx) in miniDiff.lines"
          :key="dIdx"
          class="tool-dline"
          :class="`is-${dl.kind}`"
        >{{ dl.kind === 'add' ? '+ ' : dl.kind === 'del' ? '- ' : '  ' }}{{ dl.text }}</span></pre>
      </div>

      <div v-if="formattedInput" class="tool-section">
        <div class="tool-sec-bar">
          <span>输入参数</span>
          <button
            type="button"
            class="tool-copy-btn"
            :class="{ 'is-copied': copiedTarget === 'input' }"
            :aria-label="`复制 ${tool.name} 输入参数`"
            @click.stop="copyBlock('input', formattedInput)"
          >
            <OpusIcon :name="copiedTarget === 'input' ? 'check' : 'copy'" class="tool-copy-ic" />
            <span>{{ copiedTarget === 'input' ? '已复制' : '复制' }}</span>
          </button>
        </div>
        <pre class="tool-pre">{{ formattedInput }}</pre>
      </div>

      <div v-if="tool.output" class="tool-section">
        <div class="tool-sec-bar">
          <span>执行输出</span>
          <button
            type="button"
            class="tool-copy-btn"
            :class="{ 'is-copied': copiedTarget === 'output' }"
            :aria-label="`复制 ${tool.name} 执行输出`"
            @click.stop="copyBlock('output', tool.output)"
          >
            <OpusIcon :name="copiedTarget === 'output' ? 'check' : 'copy'" class="tool-copy-ic" />
            <span>{{ copiedTarget === 'output' ? '已复制' : '复制' }}</span>
          </button>
        </div>
        <pre v-if="ansiOutputSpans" class="tool-pre tool-pre--out"><span
          v-for="(sp, aIdx) in ansiOutputSpans"
          :key="aIdx"
          :style="{
            color: sp.fg,
            backgroundColor: sp.bg,
            fontWeight: sp.bold ? 600 : undefined,
            opacity: sp.dim ? 0.72 : undefined,
            fontStyle: sp.italic ? 'italic' : undefined,
            textDecoration: sp.underline ? 'underline' : undefined,
          }"
        >{{ sp.text }}</span></pre>
        <pre v-else class="tool-pre tool-pre--out">{{ tool.output }}</pre>
      </div>

      <div v-if="tool.media?.length" class="tool-section">
        <div class="tool-sec-bar">
          <span>工具产物 / 媒体 ({{ tool.media.length }})</span>
        </div>
        <div class="tool-media-list">
          <div v-for="m in tool.media" :key="m.id" class="tool-media-item">
            <img
              v-if="m.mime.startsWith('image/') || m.url.startsWith('data:image/')"
              :src="m.url"
              :alt="m.fileName"
              class="tool-media-img"
            />
            <div class="tool-media-foot">
              <span class="tool-media-name" :title="m.fileName">{{ m.fileName }}</span>
              <button type="button" class="tool-copy-btn" @click.stop="handleDownloadToolFile(m)">下载</button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="tool.error && tool.error.trim() !== tool.output?.trim()" class="tool-err">
        <OpusIcon name="alert" />
        <span>{{ tool.error }}</span>
      </div>

      <p v-if="tool.detail && !tool.output && !tool.error" class="tool-detail">{{ tool.detail }}</p>
      <p v-if="!miniDiff && !formattedInput && !tool.output && !tool.error && !tool.detail && !tool.media?.length" class="tool-empty">
        {{ tool.status === 'running' ? '正在等待工具返回结果…' : '工具已完成，无额外控制台输出。' }}
      </p>
    </div>
  </details>
</template>

<style scoped>
.tool-card {
  min-width: 0;
  font-size: 13px;
}
.tool-card-head {
  list-style: none;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  min-block-size: 28px;
  padding-block: 4px;
  cursor: pointer;
  user-select: none;
  color: var(--text);
}
.tool-card-head::-webkit-details-marker { display: none; }
.tool-card-head:hover .tool-chev { color: var(--text); }
.tool-card-head:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.tool-chev {
  width: 11px;
  height: 11px;
  flex: none;
  color: var(--text-3);
  rotate: 0deg;
}
.tool-card[open] > .tool-card-head .tool-chev {
  rotate: 90deg;
}
.tool-kind-ic {
  width: 14px;
  height: 14px;
  flex: none;
  color: var(--text-3);
}
.tool-card-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-card.is-error .tool-card-label { color: var(--warn); }
.tool-meta { font-size: 11px; color: var(--text-3); overflow-wrap: anywhere; }
.tool-meta code { font-family: var(--mono); }
.tool-detail { margin: 0; color: var(--text-2); white-space: pre-wrap; overflow-wrap: anywhere; }
.tool-pill-btn {
  padding: 1px 6px;
  border-radius: var(--r-full);
  border: 1px solid var(--line);
  background: var(--surface-1);
  color: var(--text-2);
  font-size: 10.5px;
  cursor: pointer;
  flex: none;
}
.tool-pill-btn:hover { background: var(--surface-3); color: var(--text); }
.tool-pill-btn.is-accent {
  border-color: var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}
@media (pointer: coarse) { .tool-card-head { min-height: 44px; } }

.tool-card::details-content {
  interpolate-size: allow-keywords;
  overflow: clip;
  contain: layout;
}
.tool-card:not([open])::details-content {
  block-size: 0;
}
@media (prefers-reduced-motion: no-preference) {
  .tool-chev { transition: rotate 0.16s ease; }
  .tool-card::details-content {
    transition: block-size, content-visibility, display;
    transition-duration: 0.2s;
    transition-timing-function: ease-out;
    transition-behavior: allow-discrete;
  }
}

.tool-card-body {
  min-width: 0;
  display: grid;
  gap: 8px;
  margin: 4px 0 3px 5px;
  padding: 8px 8px 8px 10px;
  border-left: 1px solid var(--line-strong, var(--line));
}
.tool-actions { display: flex; flex-wrap: wrap; gap: 4px; }
.tool-section { display: grid; gap: 4px; }
.tool-sec-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10.5px;
  color: var(--text-3);
}
.tool-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10.5px;
  color: var(--text-2);
  background: var(--surface-2);
  cursor: pointer;
}
.tool-copy-ic {
  width: 11px;
  height: 11px;
}
.tool-copy-btn:hover { background: var(--surface-3); color: var(--text); }
.tool-pre {
  margin: 0;
  padding: 7px 9px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 180px;
  overflow: auto;
}
.tool-pre--out { max-height: 220px; }
.tool-pre--diff {
  padding: 6px 0;
  max-height: 220px;
  white-space: pre;
  overflow-x: auto;
}
.tool-dline {
  display: block;
  padding: 0 9px;
}
.tool-dline.is-add {
  background: color-mix(in srgb, var(--ok-soft) 72%, transparent);
  color: var(--ok);
}
.tool-dline.is-del {
  background: color-mix(in srgb, var(--warn-soft) 72%, transparent);
  color: var(--warn);
}
.tool-err {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--r-xs);
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 11.5px;
}
.tool-err .i { width: 13px; height: 13px; flex: none; margin-top: 1px; }
.tool-empty {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-3);
}
.tool-media-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px;
  background: var(--solid);
}
.tool-media-item {
  display: flex;
  flex-direction: column;
  max-width: min(260px, 100%);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface-2);
}
.tool-media-img {
  display: block;
  max-width: 100%;
  max-height: 160px;
  object-fit: contain;
}
.tool-media-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 8px;
  border-top: 1px solid var(--line);
}
.tool-media-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-2);
}
</style>
