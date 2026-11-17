<script setup lang="ts">
import { onMounted, onUnmounted, ref, type Component } from 'vue'
import { ArrowUpRight, Bell, Plus } from 'lucide-vue-next'

interface CreateAction {
  label: string
  kind: string
  icon: Component
}

withDefaults(defineProps<{ createItems: CreateAction[]; addLabel?: string; showCreate?: boolean }>(), { addLabel: '新建', showCreate: true })
const emit = defineEmits<{ create: [kind: string]; opened: [] }>()
const root = ref<HTMLElement | null>(null)
const openMenu = ref<'notifications' | 'create' | null>(null)

function closeMenus() { openMenu.value = null }
function toggleMenu(menu: 'notifications' | 'create') {
  openMenu.value = openMenu.value === menu ? null : menu
  if (openMenu.value) emit('opened')
}
function create(kind: string) {
  emit('create', kind)
  closeMenus()
}
function onDocumentPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) closeMenus()
}
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenus()
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})
defineExpose({ closeMenus })
</script>

<template>
  <div ref="root" class="top-action-controls">
    <div class="tool-wrap">
      <button class="topbar__icon-button" :aria-expanded="openMenu === 'notifications'" aria-label="通知" type="button" @click="toggleMenu('notifications')">
        <Bell :size="27" :stroke-width="1.65" />
      </button>
      <div v-if="openMenu === 'notifications'" class="toolbar-popover notifications-panel">
        <div class="popover-heading">通知</div>
        <div class="notification-item">暂无通知</div>
      </div>
    </div>

    <div v-if="showCreate" class="tool-wrap">
      <button class="topbar__new" :aria-expanded="openMenu === 'create'" :aria-label="addLabel" type="button" @click="toggleMenu('create')"><Plus :size="26" :stroke-width="1.65" /></button>
      <div v-if="openMenu === 'create'" class="toolbar-popover create-panel">
        <div class="popover-heading">新建</div>
        <button v-for="item in createItems" :key="item.kind" type="button" class="create-item" @click="create(item.kind)">
          <component :is="item.icon" :size="17" /><span>{{ item.label }}</span><ArrowUpRight :size="14" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.top-action-controls { display: flex; align-items: center; gap: 14px; }
.tool-wrap { position: relative; }
.topbar__icon-button, .topbar__new { display: grid; flex: none; width: 47px; height: 47px; place-items: center; color: var(--workbench-text); transition: transform .2s, background .2s, box-shadow .2s; }
.topbar__icon-button { position: relative; border: 0; border-radius: 15px; background: transparent; }
.topbar__icon-button:hover { transform: translateY(-2px); background: var(--workbench-soft); }
.notification-dot { position: absolute; top: 8px; right: 7px; width: 10px; height: 10px; border-radius: 50%; background: var(--workbench-solid); box-shadow: 0 0 0 2px rgba(90,111,174,.8); }
.topbar__new { border: 1px solid var(--workbench-line); border-radius: 15px; background: var(--workbench-solid); box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 8px 20px rgba(22,37,84,.13); backdrop-filter: var(--workbench-material); }
.topbar__new:hover { transform: translateY(-2px); background: var(--workbench-soft); box-shadow: 0 10px 24px rgba(22,37,84,.2); }
.toolbar-popover { position: absolute; z-index: 30; top: calc(100% + 10px); right: 0; width: 280px; padding: 12px; color: var(--workbench-accent-ink); border: 1px solid var(--workbench-line); border-radius: 18px; background: var(--workbench-accent); box-shadow: 0 20px 45px rgba(20,31,67,.35), inset 0 1px 0 rgba(255,255,255,.12); backdrop-filter: var(--workbench-material); }
.popover-heading { display: flex; justify-content: space-between; padding: 4px 7px 10px; color: var(--workbench-muted); font-size: 10px; font-weight: 700; letter-spacing: .12em; }
.popover-heading span { color: var(--workbench-good); }
.notification-item { display: flex; align-items: flex-start; gap: 9px; padding: 11px 6px; border-top: 1px solid var(--workbench-line); }
.notification-icon { display: grid; place-items: center; flex: none; width: 27px; height: 27px; border-radius: 9px; }
.notification-icon--success { color: var(--workbench-good); background: var(--workbench-good-soft); }
.notification-icon--info { color: var(--workbench-accent); background: var(--workbench-solid); }
.notification-item strong, .notification-item small { display: block; }
.notification-item strong { margin-bottom: 4px; color: var(--workbench-text); font-size: 11px; }
.notification-item small { color: var(--workbench-muted); font-size: 10px; line-height: 1.35; }
.create-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 10px 8px; text-align: left; color: var(--workbench-muted); border: 0; border-radius: 10px; background: transparent; font-size: 11px; font-weight: 600; transition: background .2s; }
.create-item:hover { background: var(--workbench-soft); }
.create-item svg:first-child { color: var(--workbench-accent); }
.create-item svg:last-child { margin-left: auto; color: var(--workbench-muted); }
@media (max-width: 420px) { .top-action-controls { gap: 7px; } }
</style>
