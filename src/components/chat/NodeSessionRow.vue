<script setup lang="ts">
import { computed } from 'vue'
import type { ChatSession } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'
import { getProviderMeta } from './providerMeta'

const props = defineProps<{
  session: ChatSession
  status: { key: string; label: string }
  active: boolean
  renaming: boolean
  snippet?: string
  branch?: string
  time?: string
}>()
const draft = defineModel<string>('draft', { required: true })
const emit = defineEmits<{ open: []; rename: []; save: []; cancel: []; split: []; remove: [] }>()
const provider = computed(() => getProviderMeta(props.session.provider))
</script>

<template>
  <div class="node-session-row" :class="{ 'is-active': active, 'is-renaming': renaming }">
    <input
      v-if="renaming"
      v-model="draft"
      type="text"
      class="input tree-rename-input"
      aria-label="输入新会话名称"
      @keydown.enter.prevent="emit('save')"
      @keydown.esc.prevent="emit('cancel')"
      @blur="emit('save')"
    />
    <button
      v-else
      type="button"
      class="node-session-open"
      :aria-current="active ? 'true' : undefined"
      :title="session.title"
      @click="emit('open')"
    >
      <span class="node-session-status" :class="`is-${status.key}`" aria-hidden="true" />
      <OpusIcon :name="provider.icon" class="node-session-icon" :title="provider.label" />
      <span class="node-session-name">
        <span class="node-session-title">{{ session.title }}</span>
        <span v-if="snippet || branch" class="node-session-subtitle" :title="snippet || branch">{{ snippet || branch }}</span>
      </span>
      <span class="node-session-facts">
        <span class="node-session-badge" :class="`is-${status.key}`">{{ status.label }}</span>
        <span v-if="session.model" class="node-session-model" :title="session.model">{{ session.model }}</span>
        <span v-if="time" class="node-session-time">{{ time }}</span>
      </span>
    </button>
    <div v-if="!renaming" class="node-session-actions">
      <button type="button" title="重命名会话" aria-label="重命名会话" @click="emit('rename')"><OpusIcon name="pencil" /></button>
      <button type="button" title="在右侧分屏并行查看" aria-label="在右侧分屏并行查看" @click="emit('split')"><OpusIcon name="panel" /></button>
      <button type="button" title="关闭并删除会话" aria-label="删除会话" @click="emit('remove')"><OpusIcon name="trash" /></button>
    </div>
  </div>
</template>

<style scoped>
.node-session-row {
  position: relative;
  min-width: 0;
  color: var(--text-2);
  border: 1px solid transparent;
  border-radius: 8px;
}
.node-session-row:hover,
.node-session-row:focus-within { background: var(--surface-3); color: var(--text); }
.node-session-row.is-active { background: var(--solid); color: var(--text); border-color: var(--line-strong); }
.node-session-open {
  display: grid;
  grid-template-columns: 10px 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  width: 100%;
  min-height: 32px;
  padding: 4px 7px;
  color: inherit;
  text-align: left;
  border-radius: inherit;
}
.node-session-status {
  width: 8px;
  height: 8px;
  border: 1px solid var(--ok);
  border-radius: 50%;
}
.node-session-status.is-running { border: 2px solid var(--warn); border-right-color: transparent; }
.node-session-status.is-approval { background: var(--warn); border-color: var(--warn); }
.node-session-status.is-input, .node-session-status.is-waiting { border-color: var(--text-3); }
.node-session-badge.is-approval, .node-session-badge.is-running { color: var(--warn); }
.node-session-icon { width: 16px; height: 16px; }
.node-session-name { display: grid; min-width: 0; }
.node-session-title, .node-session-subtitle, .node-session-model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-session-title { font-size: 12.5px; font-weight: 530; }
.node-session-subtitle, .node-session-facts { font-size: 11px; color: var(--text-3); }
.node-session-facts { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.node-session-model { max-width: 70px; font-family: var(--mono, monospace); }
.node-session-actions {
  position: absolute;
  inset: 0 5px 0 auto;
  display: flex;
  align-items: center;
  gap: 1px;
  opacity: 0;
  pointer-events: none;
}
.node-session-row:hover .node-session-actions, .node-session-row:focus-within .node-session-actions {
  opacity: 1;
  pointer-events: auto;
}
.node-session-row:hover .node-session-open, .node-session-row:focus-within .node-session-open {
  padding-right: 74px;
}
.node-session-row:hover .node-session-facts, .node-session-row:focus-within .node-session-facts { display: none; }
.node-session-actions button {
  display: grid;
  place-items: center;
  width: 21px;
  height: 24px;
  border-radius: 5px;
  color: var(--text-3);
}
.node-session-actions button:hover { background: var(--surface-2); color: var(--text); }
.node-session-actions .i { width: 13px; height: 13px; }
.node-session-row.is-renaming { padding: 3px 6px; }
.tree-rename-input { width: 100%; min-width: 0; height: 27px; padding: 2px 6px; font-size: 12px; }
@container node-sidebar (max-width: 260px) {
  .node-session-model { display: none; }
}
@container node-sidebar (max-width: 185px) {
  .node-session-facts { display: none; }
  .node-session-open { gap: 4px; padding-inline: 4px; }
}
</style>
