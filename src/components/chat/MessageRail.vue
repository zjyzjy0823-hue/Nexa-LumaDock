<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatMessage } from '../../types/fleet'

const props = defineProps<{
  messages: ChatMessage[]
  activeMsgId?: string | null
}>()

const emit = defineEmits<{
  jump: [msgId: string]
}>()

const hovered = ref(false)

interface RailEntry {
  id: string
  index: number
  label: string
}

const entries = computed<RailEntry[]>(() => {
  const out: RailEntry[] = []
  let turn = 0
  for (const m of props.messages) {
    if (m.role !== 'user') continue
    turn += 1
    const clean = (m.text || '').replace(/\s+/g, ' ').trim()
    out.push({
      id: m.id,
      index: turn,
      label: clean ? (clean.length > 36 ? `${clean.slice(0, 36)}…` : clean) : `第 ${turn} 轮`,
    })
  }
  return out
})

const visible = computed(() => entries.value.length >= 3)
</script>

<template>
  <nav
    v-if="visible"
    class="msg-rail"
    :class="{ 'is-open': hovered }"
    aria-label="对话大纲快速跳转"
    @pointerenter="hovered = true"
    @pointerleave="hovered = false"
  >
    <div class="rail-ticks" aria-hidden="true">
      <span
        v-for="item in entries.slice(-24)"
        :key="item.id"
        class="rail-tick"
        :class="{ 'is-active': activeMsgId === item.id }"
      />
    </div>

    <div v-if="hovered" class="rail-popover" role="list">
      <div class="rail-hdr">对话大纲 · {{ entries.length }} 轮</div>
      <button
        v-for="item in entries"
        :key="item.id"
        type="button"
        role="listitem"
        class="rail-row"
        :class="{ 'is-active': activeMsgId === item.id }"
        @click="emit('jump', item.id)"
      >
        <span class="rail-idx num">{{ item.index }}</span>
        <span class="rail-txt">{{ item.label }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.msg-rail {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  z-index: 16;
  display: flex;
  align-items: center;
  padding: 8px 4px;
}

.rail-ticks {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
  padding: 6px 3px;
  border-radius: 999px;
  transition: opacity 0.16s ease;
  opacity: 0.45;
}

.msg-rail:hover .rail-ticks {
  opacity: 0.9;
}

.rail-tick {
  width: 10px;
  height: 2px;
  border-radius: 999px;
  background: var(--text-3);
  transition: width 0.14s ease, background-color 0.14s ease;
}

.rail-tick.is-active {
  width: 16px;
  background: var(--accent);
}

.rail-popover {
  position: absolute;
  right: 18px;
  top: 50%;
  transform: translateY(-50%);
  width: 248px;
  max-height: min(360px, 60vh);
  overflow-y: auto;
  padding: 6px;
  border-radius: var(--r-md);
  border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--solid) 94%, transparent);
  backdrop-filter: blur(12px);
  box-shadow: var(--shadow-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rail-hdr {
  padding: 4px 8px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
  margin-bottom: 2px;
}

.rail-row {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--r-xs);
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.rail-row:hover,
.rail-row.is-active {
  background: var(--surface-2);
  color: var(--text);
}

.rail-idx {
  flex: none;
  min-width: 18px;
  font-size: 10.5px;
  color: var(--text-3);
}

.rail-row.is-active .rail-idx {
  color: var(--accent);
  font-weight: 600;
}

.rail-txt {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
