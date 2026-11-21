<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { hasAnsiSequences, parseAnsiText } from '../../services/ansiParser'
import { useFleetStore } from '../../stores/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  sessionKey: string
}>()

const emit = defineEmits<{
  close: []
  attach: [text: string]
}>()

const fleet = useFleetStore()
const cmdInput = ref('')
const cmdHistory = ref<string[]>([])
const historyCursor = ref(-1)
const outEl = ref<HTMLElement | null>(null)
const selectedOutput = ref('')
const manualPort = ref<number>()

const term = computed(() => (props.sessionKey ? fleet.terminalBySession[props.sessionKey] ?? null : null))

const renderedSpans = computed(() => {
  const txt = term.value?.output || ''
  if (!txt) return []
  return hasAnsiSequences(txt) ? parseAnsiText(txt) : [{ text: txt }]
})
const outputText = computed(() => renderedSpans.value.map(span => span.text).join(''))
const terminalKeys = [
  { label: 'Esc', value: '\x1b' }, { label: '↑', value: '\x1b[A' }, { label: '↓', value: '\x1b[B' },
  { label: '←', value: '\x1b[D' }, { label: '→', value: '\x1b[C' }, { label: '|', value: '|' }, { label: '~', value: '~' },
]
const previewPorts = computed(() => {
  const ports = new Map<number, boolean>()
  for (const match of outputText.value.matchAll(/\b(https?):\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::\]):(\d{1,5})\b/g)) {
    const port = Number(match[2])
    if (port >= 1024 && port <= 65535) ports.set(port, match[1] === 'https')
  }
  for (const port of Object.keys(fleet.terminalPreviews[props.sessionKey] ?? {})) {
    if (!ports.has(Number(port))) ports.set(Number(port), false)
  }
  return ports
})
watch(() => props.sessionKey, () => { selectedOutput.value = ''; manualPort.value = undefined })

function rememberOutputSelection() {
  const selection = window.getSelection()
  selectedOutput.value = selection?.anchorNode && selection.focusNode &&
    outEl.value?.contains(selection.anchorNode) && outEl.value.contains(selection.focusNode) ? selection.toString() : ''
}

function attachOutput() {
  const text = selectedOutput.value || outEl.value?.innerText || ''
  if (!outputText.value || !text.trim()) return
  emit('attach', text.slice(-16_000))
}

watch(
  () => [props.sessionKey, term.value?.terminalId] as const,
  ([k, tid]) => {
    if (k && !tid && fleet.sessionsByKey[k]) {
      fleet.openTerminal(k)
    }
  },
  { immediate: true },
)

watch(
  () => term.value?.output.length,
  async () => {
    await nextTick()
    if (outEl.value) outEl.value.scrollTop = outEl.value.scrollHeight
  },
)

function sendLine(line?: string) {
  const payload = (line ?? cmdInput.value).trimEnd()
  if (!payload || !props.sessionKey || !term.value || term.value.closed) return
  fleet.sendTerminalInput(props.sessionKey, `${payload}\n`)
  if (line === undefined) {
    if (cmdHistory.value[cmdHistory.value.length - 1] !== payload) {
      cmdHistory.value = [...cmdHistory.value.slice(-49), payload]
    }
    historyCursor.value = -1
    cmdInput.value = ''
  }
}

function sendInterrupt() {
  if (!props.sessionKey || !term.value || term.value.closed) return
  fleet.sendTerminalSignal(props.sessionKey, 'SIGINT')
}

function sendTabKey() {
  if (!props.sessionKey || !term.value || term.value.closed) return
  fleet.sendTerminalInput(props.sessionKey, `${cmdInput.value}\t`)
}

function handleInputKeydown(ev: KeyboardEvent) {
  if (ev.ctrlKey && ev.key.toLowerCase() === 'c' && !window.getSelection()?.toString()) {
    ev.preventDefault()
    sendInterrupt()
    return
  }
  if (ev.key === 'ArrowUp' && cmdHistory.value.length) {
    ev.preventDefault()
    if (historyCursor.value === -1) historyCursor.value = cmdHistory.value.length - 1
    else if (historyCursor.value > 0) historyCursor.value -= 1
    cmdInput.value = cmdHistory.value[historyCursor.value] ?? ''
    return
  }
  if (ev.key === 'ArrowDown' && historyCursor.value >= 0) {
    ev.preventDefault()
    if (historyCursor.value < cmdHistory.value.length - 1) {
      historyCursor.value += 1
      cmdInput.value = cmdHistory.value[historyCursor.value] ?? ''
    } else {
      historyCursor.value = -1
      cmdInput.value = ''
    }
  }
}

function clearOutput() {
  if (!props.sessionKey || !term.value) return
  fleet.terminalBySession[props.sessionKey] = { ...term.value, output: '' }
}

function restartTerminal() {
  if (!props.sessionKey) return
  fleet.closeTerminal(props.sessionKey)
  fleet.openTerminal(props.sessionKey)
}
</script>

<template>
  <section class="term-drawer" aria-label="受控工作区集成终端">
    <header class="term-hdr">
      <div class="term-title">
        <OpusIcon name="terminal" class="term-ic" />
        <span>受控终端</span>
        <span v-if="term?.pty" class="term-badge is-pty">PTY</span>
        <span v-if="term?.closed" class="term-badge is-closed">已退出 ({{ term.exitCode ?? 0 }})</span>
        <span v-else-if="term" class="term-badge is-live">运行中</span>
      </div>
      <div class="term-actions">
        <button
          type="button"
          class="btn btn-subtle btn-sm"
          title="发送 SIGINT 中断当前运行命令 (Ctrl+C)"
          :disabled="!term || term.closed"
          @click="sendInterrupt"
        >Ctrl+C</button>
        <button
          v-if="term?.pty"
          type="button"
          class="btn btn-subtle btn-sm"
          title="发送 Tab 补全"
          :disabled="term.closed"
          @click="sendTabKey"
        >Tab</button>
        <button type="button" class="btn btn-subtle btn-sm" @click="sendLine('git status -sb')">git status</button>
        <button type="button" class="icon-btn" title="清屏" aria-label="清空终端输出" @click="clearOutput">
          <OpusIcon name="trash" />
        </button>
        <button type="button" class="icon-btn" title="重启终端" aria-label="重启终端会话" @click="restartTerminal">
          <OpusIcon name="sync" />
        </button>
        <button type="button" class="icon-btn" title="关闭终端面板" aria-label="关闭终端面板" @click="emit('close')">
          <OpusIcon name="x" />
        </button>
      </div>
    </header>

    <div v-if="term?.cwd" class="term-cwd">
      <code>{{ term.cwd }}</code>
    </div>

    <pre ref="outEl" class="term-output" role="log" aria-live="polite" tabindex="0" @pointerup="rememberOutputSelection" @keyup="rememberOutputSelection"><template v-if="renderedSpans.length"><span
      v-for="(sp, idx) in renderedSpans"
      :key="idx"
      :style="{
        color: sp.fg,
        backgroundColor: sp.bg,
        fontWeight: sp.bold ? 600 : undefined,
        opacity: sp.dim ? 0.72 : undefined,
      }"
    >{{ sp.text }}</span></template><span v-else class="faint">等待终端会话就绪… 输入命令按 Enter 执行，支持 ↑/↓ 历史记录与 Ctrl+C 中断。</span></pre>

    <div class="term-shortcuts">
      <template v-if="term?.pty && !term.closed">
        <button v-for="key in terminalKeys" :key="key.label" type="button" class="btn btn-ghost btn-sm"
          @click="fleet.sendTerminalInput(sessionKey, key.value)">{{ key.label }}</button>
      </template>
      <button type="button" class="btn btn-ghost btn-sm" :disabled="!outputText" @click="attachOutput">
        {{ selectedOutput ? '附上所选输出' : '附上可见输出' }}
      </button>
    </div>
    <div v-if="term && !term.closed" class="term-previews" aria-label="端口预览">
      <form class="term-port-form" @submit.prevent="manualPort && fleet.requestTerminalPreview(sessionKey, manualPort, previewPorts.get(manualPort))">
        <input v-model.number="manualPort" class="input" type="number" min="1024" max="65535" placeholder="端口" aria-label="预览端口号" />
        <button type="submit" class="btn btn-ghost btn-sm" :disabled="!manualPort || manualPort < 1024 || manualPort > 65535">转发端口</button>
      </form>
      <div v-for="[port, tls] in previewPorts" :key="port" class="term-port-row">
        <button type="button" class="btn btn-ghost btn-sm" :disabled="fleet.terminalPreviews[sessionKey]?.[port]?.pending"
          @click="fleet.requestTerminalPreview(sessionKey, port, tls)">
          {{ fleet.terminalPreviews[sessionKey]?.[port]?.pending ? '正在转发…' : `预览 ${port}` }}
        </button>
        <a v-if="fleet.terminalPreviews[sessionKey]?.[port]?.url" class="btn btn-primary btn-sm"
          :href="fleet.terminalPreviews[sessionKey][port].url" target="_blank" rel="noopener noreferrer">打开预览 {{ port }}</a>
        <span v-else-if="fleet.terminalPreviews[sessionKey]?.[port]?.error" class="faint" role="status">{{ fleet.terminalPreviews[sessionKey][port].error }}</span>
      </div>
    </div>
    <form class="term-input-bar" @submit.prevent="sendLine()">
      <span class="term-prompt">$</span>
      <input
        v-model="cmdInput"
        type="text"
        class="term-input"
        :disabled="!term || term.closed"
        placeholder="输入命令后按 Enter（↑/↓ 翻历史 · Ctrl+C 中断）…"
        aria-label="向节点终端发送命令"
        @keydown="handleInputKeydown"
      >
      <button type="submit" class="btn btn-primary btn-sm" :disabled="!cmdInput.trim() || !term || term.closed">运行</button>
    </form>
  </section>
</template>

<style scoped>
.term-shortcuts { display: flex; gap: 4px; flex-wrap: wrap; padding: 4px 8px; border-top: 1px solid var(--line); }
.term-previews { display: flex; gap: 4px; flex-wrap: wrap; padding: 4px 8px; align-items: center; }
.term-port-row, .term-port-form { display: flex; gap: 4px; align-items: center; }
.term-port-form .input { width: 84px; min-height: 29px; }
.term-port-row a { text-decoration: none; }
.term-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--surface-1);
}
.term-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.term-title { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; }
.term-ic { width: 14px; height: 14px; color: var(--accent); }
.term-badge {
  padding: 1px 6px;
  border-radius: var(--r-full);
  font-size: 10.5px;
  font-weight: 500;
}
.term-badge.is-live { background: color-mix(in srgb, var(--ok) 15%, transparent); color: var(--ok); }
.term-badge.is-pty { background: var(--accent-soft); color: var(--accent); font-family: var(--font-mono, monospace); }
.term-badge.is-closed { background: var(--surface-3); color: var(--text-3); }
.term-actions { display: flex; align-items: center; gap: 4px; }
.term-cwd {
  padding: 4px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.term-output {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--solid);
  color: var(--text);
}
.term-input-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-top: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.term-prompt { font-family: var(--font-mono); font-weight: 700; color: var(--accent); }
.term-input {
  flex: 1;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  background: var(--solid);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12px;
}
</style>
