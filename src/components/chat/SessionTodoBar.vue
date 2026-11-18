<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TodoItem } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  items: TodoItem[]
  streaming?: boolean
}>()

const emit = defineEmits<{
  executePlan: []
}>()

const open = ref(true)

const completedCount = computed(
  () => props.items.filter(t => t.status === 'completed').length,
)

const activeItem = computed(
  () =>
    props.items.find(t => t.status === 'in_progress') ??
    props.items.find(t => t.status === 'pending'),
)

const hasRemaining = computed(
  () => props.items.some(t => t.status === 'pending' || t.status === 'in_progress'),
)

function onToggle(ev: Event) {
  open.value = (ev.target as HTMLDetailsElement).open
}
</script>

<template>
  <details v-if="items.length" class="todo-bar" :open="open" @toggle="onToggle">
    <summary class="todo-head">
      <OpusIcon name="chevR" class="todo-chev" />
      <OpusIcon name="tasks" class="todo-ic" />
      <span class="todo-title">执行计划</span>
      <span class="todo-progress num">{{ completedCount }}/{{ items.length }}</span>
      <span v-if="!open && activeItem" class="todo-preview">· {{ activeItem.content }}</span>
      <span class="todo-spacer" />
      <button
        v-if="hasRemaining && !streaming"
        type="button"
        class="btn btn-subtle btn-sm todo-exec-btn"
        @click.stop.prevent="emit('executePlan')"
      >
        <OpusIcon name="play" />
        <span>继续执行</span>
      </button>
    </summary>

    <ol class="todo-list">
      <li
        v-for="item in items"
        :key="item.id"
        class="todo-item"
        :class="`is-${item.status}`"
      >
        <span class="todo-state-dot" aria-hidden="true">
          <OpusIcon v-if="item.status === 'completed'" name="check" />
          <span v-else-if="item.status === 'in_progress'" class="todo-pulse" />
          <span v-else-if="item.status === 'cancelled'" class="todo-dash">–</span>
          <span v-else class="todo-ring" />
        </span>
        <span class="todo-content">{{ item.content }}</span>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.todo-bar {
  margin: 0 clamp(12px, 4%, 38px) 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-2);
  font-size: 12px;
  overflow: hidden;
}
.todo-head {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  min-block-size: 30px;
  padding: 5px 10px;
  cursor: pointer;
  user-select: none;
}
.todo-head::-webkit-details-marker { display: none; }
.todo-head:hover { background: var(--surface-3); }
.todo-head:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.todo-chev {
  width: 12px;
  height: 12px;
  flex: none;
  color: var(--text-3);
  rotate: 0deg;
}
.todo-bar[open] > .todo-head .todo-chev { rotate: 90deg; }
.todo-ic {
  width: 13px;
  height: 13px;
  color: var(--accent);
  flex: none;
}
.todo-title { font-weight: 600; color: var(--text); flex: none; }
.todo-progress {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--solid);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
  flex: none;
}
.todo-preview {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
}
.todo-spacer { flex: 1; }
.todo-exec-btn {
  min-block-size: 24px;
  padding: 2px 8px;
  font-size: 11px;
}
.todo-list {
  margin: 0;
  padding: 6px 12px 9px 14px;
  list-style: none;
  display: grid;
  gap: 5px;
  border-top: 1px solid var(--line);
  background: var(--solid);
  max-height: 168px;
  overflow: auto;
}
.todo-item {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  line-height: 1.4;
  color: var(--text-2);
}
.todo-item.is-in_progress { color: var(--text); font-weight: 550; }
.todo-item.is-completed { color: var(--text-3); }
.todo-item.is-completed .todo-content { text-decoration: line-through; }
.todo-item.is-cancelled { color: var(--text-3); opacity: .7; }
.todo-state-dot {
  width: 15px;
  height: 15px;
  margin-top: 1px;
  display: inline-grid;
  place-items: center;
  flex: none;
  color: var(--ok);
}
.todo-state-dot .i { width: 12px; height: 12px; }
.todo-ring {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 1.5px solid var(--text-3);
}
.todo-pulse {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.todo-dash { color: var(--text-3); font-size: 11px; }

.todo-bar::details-content {
  interpolate-size: allow-keywords;
  overflow: clip;
  contain: layout;
}
.todo-bar:not([open])::details-content { block-size: 0; }
@media (prefers-reduced-motion: no-preference) {
  .todo-chev { transition: rotate 0.16s ease; }
  .todo-bar::details-content {
    transition: block-size, content-visibility, display;
    transition-duration: 0.2s;
    transition-timing-function: ease-out;
    transition-behavior: allow-discrete;
  }
}
</style>
