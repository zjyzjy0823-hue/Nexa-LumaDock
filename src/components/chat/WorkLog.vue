<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { describeToolCall } from '../../services/chatHelpers'
import type { WorkLogProgress, WorkLogStep } from '../../services/messageSegments'
import OpusIcon from '../ui/OpusIcon.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps<{
  steps: WorkLogStep[]
  progress?: WorkLogProgress
  durationMs?: number
  reveal?: { stepId: string }
}>()

const emit = defineEmits<{
  openFile: [path: string]
  openSubagent: [sessionId: string]
}>()

const isOpen = ref(false)
watch(() => props.reveal, reveal => {
  if (reveal) isOpen.value = true
}, { immediate: true })

function onToggle(event: Event) {
  isOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

function formatTime(ms?: number): string {
  if (ms === undefined || !Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} 毫秒`
  if (ms < 60000) return `${Number((ms / 1000).toFixed(1))} 秒`
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor(ms / 1000) % 60
  return seconds ? `${minutes} 分钟 ${seconds} 秒` : `${minutes} 分钟`
}

const tools = computed(() => props.steps.flatMap(step => step.type === 'tool' ? [step.tool] : []))
const currentTool = computed(() => props.progress?.type === 'tool' ? describeToolCall(props.progress.tool) : undefined)
const isWorking = computed(() => Boolean(props.progress) && (props.progress?.type !== 'tool' || props.progress.tool.status === 'running'))
const label = computed(() => {
  if (currentTool.value) return currentTool.value.label
  if (props.progress?.type === 'thought') return '思考中'
  if (props.progress?.type === 'text') return '回复中'
  const elapsed = formatTime(props.durationMs)
  if (elapsed) return `用时 ${elapsed}`
  const durations = tools.value.flatMap(({ durationMs }) =>
    durationMs !== undefined && Number.isFinite(durationMs) && durationMs >= 0 ? [durationMs] : [],
  )
  if (!durations.length) return '用时未记录'
  return `工具用时 ${formatTime(durations.reduce((sum, ms) => sum + ms, 0))}`
})
</script>

<template>
  <details class="work-log" :open="isOpen" @toggle.self="onToggle">
    <summary class="work-log-toggle">
      <OpusIcon v-if="currentTool" :name="currentTool.icon" class="work-log-icon" />
      <span v-else-if="isWorking" class="work-log-spinner" aria-hidden="true" />
      <span class="work-log-label" :class="{ 'chat-progress-shimmer': isWorking }" aria-live="polite">{{ label }}</span>
      <OpusIcon name="chevD" class="work-log-chevron" />
    </summary>

    <ol v-if="isOpen" class="work-log-timeline" aria-label="工作步骤">
      <li
        v-for="step in steps"
        :key="step.id"
        :data-work-step="step.id"
        :class="step.type === 'thought' ? 'step-thought' : `step-${step.tool.status ?? 'completed'}`"
      >
        <span class="step-marker" aria-hidden="true" />
        <div v-if="step.type === 'thought'" class="work-log-thought">
          <span class="thought-label"><OpusIcon name="sparkle" />思考过程</span>
          <p>{{ step.text }}</p>
        </div>
        <ToolCallCard
          v-else
          :tool="step.tool"
          :reveal="reveal?.stepId === step.id ? reveal : undefined"
          @open-file="path => emit('openFile', path)"
          @open-subagent="id => emit('openSubagent', id)"
        />
      </li>
    </ol>
  </details>
</template>

<style scoped>
.work-log { min-width: 0; color: var(--text-2); font-size: 13px; }
.work-log-toggle {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  min-height: 32px;
  padding-block: 4px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  list-style: none;
  cursor: pointer;
  user-select: none;
}
.work-log-toggle::-webkit-details-marker { display: none; }
.work-log-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.work-log-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.work-log-icon { width: 14px; height: 14px; flex: none; }
.work-log-chevron { width: 11px; height: 11px; flex: none; }
.work-log[open] > .work-log-toggle .work-log-chevron { transform: rotate(180deg); }
.work-log-toggle:hover .work-log-chevron { color: var(--text); }
.work-log-spinner {
  width: 12px;
  height: 12px;
  flex: none;
  border: 1.5px solid var(--accent);
  border-inline-end-color: transparent;
  border-radius: 50%;
}
.work-log-timeline { display: grid; gap: 0; padding: 3px 2px 0 10px; margin: 0; list-style: none; }
.work-log-timeline > li {
  position: relative;
  min-width: 0;
  padding: 3px 0 3px 16px;
}
.work-log-timeline > li:not(:last-child)::before {
  position: absolute;
  inset: 15px auto -15px 2px;
  width: 1px;
  background: var(--line-strong, var(--line));
  content: '';
}
.step-marker {
  position: absolute;
  inset: 14px auto auto 0;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-3);
  box-shadow: 0 0 0 2px var(--solid);
}
.step-thought .step-marker, .step-running .step-marker { background: var(--accent); }
.step-error .step-marker { background: var(--warn); }
.work-log-thought { min-width: 0; padding: 4px 6px 7px; }
.thought-label { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); font-weight: 540; }
.thought-label .i { width: 13px; height: 13px; color: var(--accent); }
.work-log-thought p { margin: 4px 0 0; color: var(--text-2); line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
@keyframes work-log-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: no-preference) {
  .work-log-spinner { animation: work-log-spin .85s linear infinite; }
}
@media (pointer: coarse) { .work-log-toggle { min-height: 44px; } }
</style>
