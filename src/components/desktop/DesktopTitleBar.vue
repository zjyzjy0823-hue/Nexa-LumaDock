<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { Copy, Minus, Square, X } from 'lucide-vue-next'

const appWindow = getCurrentWindow()
const maximized = ref(false)
const error = ref('')
let disposed = false
let unlisten: (() => void) | undefined
async function syncMaximized() {
  maximized.value = await appWindow.isMaximized()
}
async function control(action: 'minimize' | 'toggleMaximize' | 'close') {
  try {
    error.value = ''
    await appWindow[action]()
    if (action === 'toggleMaximize') await syncMaximized()
  } catch {
    error.value = '窗口操作失败，请重试。'
  }
}
onMounted(async () => {
  try {
    await syncMaximized()
    const stop = await appWindow.onResized(() => { void syncMaximized().catch(() => {}) })
    if (disposed) stop()
    else unlisten = stop
  } catch { error.value = '无法读取窗口状态。' }
})
onUnmounted(() => { disposed = true; unlisten?.() })
</script>

<template>
  <header class="desktop-titlebar" aria-label="Nexa 窗口">
    <div class="desktop-titlebar__drag" data-tauri-drag-region>
      <img src="/nexa-app-icon.png" alt="" draggable="false" data-tauri-drag-region />
      <span data-tauri-drag-region>Nexa</span>
      <small v-if="error" role="alert" data-tauri-drag-region>{{ error }}</small>
    </div>
    <div class="desktop-titlebar__controls">
      <button type="button" aria-label="最小化窗口" title="最小化" @click="control('minimize')"><Minus :size="15" /></button>
      <button type="button" :aria-label="maximized ? '还原窗口' : '最大化窗口'" :title="maximized ? '还原' : '最大化'" @click="control('toggleMaximize')"><Copy v-if="maximized" :size="13" /><Square v-else :size="13" /></button>
      <button type="button" class="desktop-titlebar__close" aria-label="关闭到托盘" title="关闭到托盘" @click="control('close')"><X :size="16" /></button>
    </div>
  </header>
</template>

<style scoped>
.desktop-titlebar { position:relative; z-index:90; display:flex; flex:none; height:36px; color:rgba(255,255,255,.92); border-bottom:1px solid rgba(255,255,255,.18); background:rgba(67,83,134,.27); backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); user-select:none; }
.desktop-titlebar__drag { display:flex; flex:1; min-width:0; align-items:center; gap:8px; padding-left:14px; font-size:12px; font-weight:600; }
.desktop-titlebar__drag img { width:20px; height:20px; object-fit:contain; }
.desktop-titlebar__drag small { margin-left:12px; font-weight:400; }
.desktop-titlebar__controls { display:flex; flex:none; }
.desktop-titlebar button { display:grid; place-items:center; width:46px; height:36px; padding:0; border:0; border-radius:0; background:transparent; color:inherit; }
.desktop-titlebar button:hover { background:rgba(255,255,255,.16); }
.desktop-titlebar button:active { background:rgba(255,255,255,.24); }
.desktop-titlebar .desktop-titlebar__close:hover { background:#c94b60; color:white; }
.desktop-titlebar button:focus-visible { outline:2px solid rgba(255,255,255,.8); outline-offset:-3px; }
</style>
