<script setup lang="ts">
import { computed, ref } from 'vue'
import type { GroupedToolRun } from '../../services/chatHelpers'
import OpusIcon from '../ui/OpusIcon.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps<{
  group: GroupedToolRun
}>()

const emit = defineEmits<{
  openFile: [filePath: string]
  openSubagent: [sessionId: string]
}>()

const userToggled = ref(false)
const manualOpen = ref(false)

const isOpen = computed(() => {
  if (userToggled.value) return manualOpen.value
  return props.group.hasError
})

function onToggle(ev: Event) {
  const el = ev.target as HTMLDetailsElement
  userToggled.value = true
  manualOpen.value = el.open
}

const durationText = computed(() => {
  const ms = props.group.totalDurationMs
  if (!ms || ms <= 0) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
})

const runningToolTitle = computed(() => {
  const active = props.group.tools.find(t => t.status === 'running')
  if (!active) return ''
  return active.title && active.title !== active.name ? `${active.name} · ${active.title}` : active.name
})
</script>

<template>
  <details
    class="work-run"
    :class="{
      'is-running': group.hasRunning,
      'is-error': group.hasError,
    }"
    :open="isOpen"
    @toggle="onToggle"
  >
    <summary class="work-run-head">
      <OpusIcon name="chevR" class="work-run-chev" />
      <span v-if="group.hasRunning" class="work-run-spin" aria-hidden="true" />
      <span v-else-if="group.hasError" class="work-run-dot is-err" aria-hidden="true" />
      <span v-else class="work-run-dot is-ok" aria-hidden="true" />
      <span class="work-run-lead">执行 {{ group.tools.length }} 步</span>
      <span class="work-run-sep" aria-hidden="true">·</span>
      <span class="work-run-summary">{{ group.hasRunning && runningToolTitle ? runningToolTitle : group.summaryLabel }}</span>
      <span class="work-run-spacer" />
      <span v-if="durationText" class="work-run-dur num">{{ durationText }}</span>
    </summary>

    <div class="work-run-body">
      <ToolCallCard
        v-for="tc in group.tools"
        :key="tc.callId || tc.id"
        :tool="tc"
        @open-file="fp => emit('openFile', fp)"
        @open-subagent="sid => emit('openSubagent', sid)"
      />
    </div>
  </details>
</template>

<style scoped>
.work-run {
  border-radius: var(--r-sm);
  background: transparent;
  font-size: 12px;
}

.work-run-head {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  min-block-size: 28px;
  padding: 4px 8px;
  border-radius: var(--r-sm);
  color: var(--text-2);
  cursor: pointer;
  user-select: none;
  transition: background-color 0.14s ease, color 0.14s ease;
}

.work-run-head::-webkit-details-marker {
  display: none;
}

.work-run-head:hover {
  background: var(--surface-2);
  color: var(--text);
}

.work-run-head:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.work-run-chev {
  width: 12px;
  height: 12px;
  flex: none;
  color: var(--text-3);
  rotate: 0deg;
}

.work-run[open] > .work-run-head .work-run-chev {
  rotate: 90deg;
}

.work-run-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}

.work-run-dot.is-ok {
  background: var(--ok);
  opacity: 0.78;
}

.work-run-dot.is-err {
  background: var(--warn);
}

.work-run-spin {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 1.5px solid var(--accent);
  border-top-color: transparent;
  flex: none;
  animation: work-run-spin 0.8s linear infinite;
}

@keyframes work-run-spin {
  to {
    transform: rotate(360deg);
  }
}

.work-run-lead {
  font-weight: 560;
  color: var(--text);
  flex: none;
}

.work-run-sep {
  color: var(--text-3);
  flex: none;
}

.work-run-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
}

.work-run.is-running .work-run-summary {
  color: var(--accent);
}

.work-run.is-error .work-run-lead {
  color: var(--warn);
}

.work-run-spacer {
  flex: 1;
}

.work-run-dur {
  font-size: 11px;
  color: var(--text-3);
  flex: none;
}

.work-run::details-content {
  interpolate-size: allow-keywords;
  overflow: clip;
  contain: layout;
}

.work-run:not([open])::details-content {
  block-size: 0;
}

@media (prefers-reduced-motion: no-preference) {
  .work-run-chev {
    transition: rotate 0.16s ease;
  }
  .work-run::details-content {
    transition: block-size, content-visibility, display;
    transition-duration: 0.22s;
    transition-timing-function: ease-out;
    transition-behavior: allow-discrete;
  }
}

.work-run-body {
  display: grid;
  gap: 6px;
  margin: 4px 0 4px 13px;
  padding-left: 12px;
  border-left: 1.5px solid var(--line);
}
</style>
