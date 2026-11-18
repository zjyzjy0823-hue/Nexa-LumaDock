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
}>()

const fleet = useFleetStore()
const cmdInput = ref('')
const outEl = ref<HTMLElement | null>(null)

const term = computed(() => (props.sessionKey ? fleet.terminalBySession[props.sessionKey] ?? null : null))

const renderedSpans = computed(() => {
  const txt = term.value?.output || ''
  if (!txt) return []
  return hasAnsiSequences(txt) ? parseAnsiText(txt) : [{ text: txt }]
})

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
  if (line === undefined) cmdInput.value = ''
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
        <span v-if="term?.closed" class="term-badge is-closed">已退出 ({{ term.exitCode ?? 0 }})</span>
        <span v-else-if="term" class="term-badge is-live">运行中</span>
      </div>
      <div class="term-actions">
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

    <pre ref="outEl" class="term-output" role="log" aria-live="polite"><template v-if="renderedSpans.length"><span
      v-for="(sp, idx) in renderedSpans"
      :key="idx"
      :style="{
        color: sp.fg,
        backgroundColor: sp.bg,
        fontWeight: sp.bold ? 600 : undefined,
        opacity: sp.dim ? 0.72 : undefined,
      }"
    >{{ sp.text }}</span></template><span v-else class="faint">等待终端会话就绪… 可在下方输入命令（按 Enter 执行）。</span></pre>

    <form class="term-input-bar" @submit.prevent="sendLine()">
      <span class="term-prompt">$</span>
      <input
        v-model="cmdInput"
        type="text"
        class="term-input"
        :disabled="!term || term.closed"
        placeholder="输入命令后按 Enter（限工作区 allowedRoots 内）…"
        aria-label="向节点终端发送命令"
      >
      <button type="submit" class="btn btn-primary btn-sm" :disabled="!cmdInput.trim() || !term || term.closed">运行</button>
    </form>
  </section>
</template>

<style scoped>
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
