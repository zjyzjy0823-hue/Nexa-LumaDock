<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import OpusIcon from '../ui/OpusIcon.vue'

export interface PaletteCommandItem {
  id: string
  group: 'command' | 'session' | 'file' | 'message'
  title: string
  subtitle?: string
  badge?: string
  payload: string
}

const props = defineProps<{
  open: boolean
  sessions: Array<{ key: string; title: string; subtitle: string; provider: string }>
  files: string[]
  commands: Array<{ id: string; label: string; description: string; command: string }>
  messageHits?: Array<{ id: string; sessionKey: string; sessionTitle: string; snippet: string }>
}>()

const emit = defineEmits<{
  close: []
  selectSession: [sessionKey: string]
  openFile: [filePath: string]
  runCommand: [command: string]
}>()

const dialogEl = ref<HTMLDialogElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)
const query = ref('')
const activeIndex = ref(0)

watch(
  () => props.open,
  async (val) => {
    const dlg = dialogEl.value
    if (!dlg) return
    if (val) {
      query.value = ''
      activeIndex.value = 0
      if (!dlg.open) {
        dlg.showModal()
      }
      await nextTick()
      inputEl.value?.focus()
    } else if (dlg.open) {
      dlg.close()
    }
  },
)

const items = computed<PaletteCommandItem[]>(() => {
  const q = query.value.trim().toLowerCase()
  const out: PaletteCommandItem[] = []

  for (const c of props.commands) {
    if (!q || `${c.label} ${c.description} ${c.command}`.toLowerCase().includes(q)) {
      out.push({
        id: `cmd:${c.id}`,
        group: 'command',
        title: c.label,
        subtitle: c.description,
        badge: '快捷指令',
        payload: c.command,
      })
    }
  }

  for (const s of props.sessions) {
    if (!q || `${s.title} ${s.subtitle} ${s.provider}`.toLowerCase().includes(q)) {
      out.push({
        id: `sess:${s.key}`,
        group: 'session',
        title: s.title,
        subtitle: s.subtitle,
        badge: s.provider,
        payload: s.key,
      })
    }
  }

  for (const f of props.files.slice(0, 60)) {
    if (!q || f.toLowerCase().includes(q)) {
      out.push({
        id: `file:${f}`,
        group: 'file',
        title: f,
        subtitle: '在右侧面板中只读预览文件内容',
        badge: '工作区文件',
        payload: f,
      })
      if (out.filter(x => x.group === 'file').length >= 12) break
    }
  }

  for (const m of props.messageHits ?? []) {
    if (!q || `${m.sessionTitle} ${m.snippet}`.toLowerCase().includes(q)) {
      out.push({
        id: `msg:${m.id}`,
        group: 'message',
        title: m.snippet,
        subtitle: `位于会话「${m.sessionTitle}」`,
        badge: '历史消息',
        payload: m.sessionKey,
      })
    }
  }

  return out.slice(0, 32)
})

watch(items, (list) => {
  if (activeIndex.value >= list.length) {
    activeIndex.value = Math.max(0, list.length - 1)
  }
})

function triggerItem(item: PaletteCommandItem) {
  if (item.group === 'command') emit('runCommand', item.payload)
  else if (item.group === 'file') emit('openFile', item.payload)
  else emit('selectSession', item.payload)
  emit('close')
}

function onKeyDown(ev: KeyboardEvent) {
  if (ev.key === 'ArrowDown') {
    ev.preventDefault()
    if (items.value.length) activeIndex.value = (activeIndex.value + 1) % items.value.length
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault()
    if (items.value.length) activeIndex.value = (activeIndex.value - 1 + items.value.length) % items.value.length
  } else if (ev.key === 'Enter') {
    const picked = items.value[activeIndex.value]
    if (picked) {
      ev.preventDefault()
      triggerItem(picked)
    }
  }
}

function onDialogClick(ev: MouseEvent) {
  // 点击对话框遮罩空白区域时实现轻量关闭（light-dismiss）
  if (ev.target === dialogEl.value) {
    emit('close')
  }
}

function onNativeClose() {
  if (dialogEl.value) dialogEl.value.returnValue = ''
  if (props.open) emit('close')
}

const activeDescendantId = computed(() => items.value[activeIndex.value]?.id)
</script>

<template>
  <dialog
    ref="dialogEl"
    class="cmd-dialog"
    aria-labelledby="cmd-palette-title"
    closedby="any"
    @close="onNativeClose"
    @click="onDialogClick"
  >
    <div class="cmd-shell" @keydown="onKeyDown">
      <header class="cmd-hdr">
        <OpusIcon name="search" class="cmd-ic" />
        <h2 id="cmd-palette-title" class="sr-only">全局命令与资源快速跳转面板</h2>
        <input
          ref="inputEl"
          v-model="query"
          type="search"
          autofocus
          class="cmd-input"
          placeholder="搜索会话、工作区文件、历史消息或快捷指令（↑/↓ 选择 · Enter 打开 · Esc 关闭）"
          aria-label="搜索命令、会话或文件"
          :aria-activedescendant="activeDescendantId"
        >
        <button type="button" class="icon-btn" aria-label="关闭命令面板" @click="emit('close')">
          <OpusIcon name="x" />
        </button>
      </header>

      <div class="cmd-list" role="listbox" aria-label="命令面板检索结果">
        <div v-if="!items.length" class="cmd-empty faint">
          未找到匹配的命令、会话或工作区文件。
        </div>
        <button
          v-for="(item, idx) in items"
          :id="item.id"
          :key="item.id"
          type="button"
          role="option"
          :aria-selected="idx === activeIndex"
          class="cmd-row"
          :class="{ 'is-active': idx === activeIndex }"
          @mouseenter="activeIndex = idx"
          @click="triggerItem(item)"
        >
          <OpusIcon
            :name="item.group === 'file' ? 'file' : item.group === 'command' ? 'zap' : item.group === 'message' ? 'chat' : 'terminal'"
            class="cmd-row-ic"
          />
          <span class="cmd-row-main">
            <span class="cmd-row-title">{{ item.title }}</span>
            <span v-if="item.subtitle" class="cmd-row-sub">{{ item.subtitle }}</span>
          </span>
          <span v-if="item.badge" class="cmd-badge">{{ item.badge }}</span>
        </button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.cmd-dialog {
  margin: min(12vh, 88px) auto auto;
  padding: 0;
  width: min(640px, 92vw);
  max-height: 74vh;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface-1);
  color: var(--text);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.42);
}
dialog.cmd-dialog:modal {
  overscroll-behavior: contain;
}
dialog.cmd-dialog::backdrop {
  background: rgba(15, 23, 42, 0.48);
  backdrop-filter: blur(4px);
  overflow: hidden;
  overscroll-behavior: contain;
}
.cmd-shell {
  display: flex;
  flex-direction: column;
  max-height: 74vh;
}
.cmd-hdr {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}
.cmd-ic { width: 16px; height: 16px; color: var(--accent); flex: none; }
.cmd-input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 13.5px;
}
.cmd-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cmd-empty {
  padding: 24px;
  text-align: center;
  font-size: 12.5px;
}
.cmd-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.cmd-row:hover,
.cmd-row.is-active {
  background: var(--surface-3);
}
.cmd-row.is-active {
  outline: 1px solid var(--accent-line);
}
.cmd-row-ic { width: 15px; height: 15px; color: var(--text-3); flex: none; }
.cmd-row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cmd-row-title {
  font-size: 12.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cmd-row-sub {
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cmd-badge {
  flex: none;
  padding: 2px 7px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--text-3);
  font-size: 10.5px;
}
</style>
