<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { Check, Copy, Minus, Square, X } from 'lucide-vue-next'
import { desktopPlatform } from '../../desktop/platform'
import type { WorkbenchTheme } from '../../composables/useWorkbenchTheme'

interface MenuItem {
  id: string
  label?: string
  shortcut?: string
  checked?: boolean
  disabled?: boolean
  danger?: boolean
  divider?: boolean
  run?: () => void
}

type MenuId = 'studiolo' | 'workspace' | 'view' | 'window'

const props = withDefaults(defineProps<{
  authenticated?: boolean
  workstation?: boolean
  setupRequired?: boolean
  theme?: WorkbenchTheme
  mode?: string
  reducedMotion?: boolean
  sidebarCollapsed?: boolean
  dockOpen?: boolean
  syncConnected?: boolean
}>(), {
  authenticated: false,
  workstation: false,
  setupRequired: false,
  theme: 'white',
  mode: 'light',
  reducedMotion: false,
  sidebarCollapsed: false,
  dockOpen: false,
  syncConnected: false,
})

const emit = defineEmits<{
  navigate: [page: string]
  create: [kind: string]
  openPalette: []
  toggleSidebar: []
  toggleDock: []
  sync: []
  openSyncSettings: []
  setTheme: [theme: WorkbenchTheme]
  toggleMode: []
  toggleReducedMotion: []
  back: []
  refresh: []
  logout: []
  action: [message: string]
}>()

const tauri = isTauri()
const windows = tauri && desktopPlatform() === 'windows'
const ctrl = desktopPlatform() === 'macos' ? '⌘' : 'Ctrl'
const maximized = ref(false)
const openMenu = ref<MenuId | null>(null)
const barRef = ref<HTMLElement | null>(null)
let disposed = false
let unlisten: (() => void) | undefined

async function syncMaximized() {
  if (!windows) return
  try {
    maximized.value = await getCurrentWindow().isMaximized()
  } catch { /* 非桌面宿主时忽略 */ }
}

async function control(action: 'minimize' | 'toggleMaximize' | 'close') {
  openMenu.value = null
  if (!windows) return
  try {
    const win = getCurrentWindow()
    await win[action]()
    if (action === 'toggleMaximize') await syncMaximized()
  } catch {
    emit('action', '窗口操作失败，请重试。')
  }
}

function exec(item: MenuItem) {
  if (item.disabled || !item.run) return
  openMenu.value = null
  item.run()
}

const menus = computed<Array<{ id: MenuId; label: string; items: MenuItem[] }>>(() => {
  const authed = props.authenticated
  return [
    {
      id: 'studiolo',
      label: 'Studiolo',
      items: authed
        ? [
            { id: 'home', label: '今天概览', run: () => emit('navigate', 'Home') },
            { id: 'sync', label: '立即同步', disabled: !props.syncConnected, run: () => emit('sync') },
            { id: 'sync-cfg', label: '冲突与同步设置', run: () => emit('openSyncSettings') },
            { id: 'd1', divider: true },
            { id: 'agents', label: 'Agent 配置', run: () => emit('navigate', 'Agents') },
            { id: 'api', label: '集成与 API', run: () => emit('navigate', 'API') },
            { id: 'settings', label: '设置…', run: () => emit('navigate', 'Settings') },
            ...(props.workstation
              ? []
              : [
                  { id: 'd2', divider: true },
                  { id: 'logout', label: '退出登录', danger: true, run: () => emit('logout') },
                ]),
          ]
        : [
            props.setupRequired
              ? { id: 'focus-setup', label: '立即离线使用', run: () => document.querySelector<HTMLButtonElement>('.setup-primary')?.click() }
              : { id: 'focus-login', label: '登录或注册账户', run: () => document.querySelector<HTMLInputElement>('input[name="username"]')?.focus() },
            { id: 'about', label: '关于 Studiolo', run: () => emit('action', 'Studiolo 个人数字控制中心') },
          ],
    },
    {
      id: 'workspace',
      label: '工作区',
      items: authed
        ? [
            { id: 'nav-home', label: '今天', run: () => emit('navigate', 'Home') },
            { id: 'nav-ledger', label: '账本', run: () => emit('navigate', 'Ledger') },
            { id: 'nav-websites', label: '网站', run: () => emit('navigate', 'Websites') },
            { id: 'nav-data', label: '数据', run: () => emit('navigate', 'Data') },
            { id: 'nav-devices', label: '设备', run: () => emit('navigate', 'Devices') },
            { id: 'nav-space', label: '共享空间', run: () => emit('navigate', 'Space') },
            { id: 'nav-chat', label: 'Agent 对话', run: () => emit('navigate', 'Chat') },
            { id: 'nav-tasks', label: '任务', run: () => emit('navigate', 'Automation') },
            { id: 'nav-dash', label: '自定义仪表盘', run: () => emit('navigate', 'Dashboard') },
            { id: 'wd1', divider: true },
            { id: 'new-tx', label: '记一笔', run: () => emit('create', 'ledger') },
            { id: 'new-web', label: '收藏网站', run: () => emit('create', 'website') },
            { id: 'new-rec', label: '新建数据记录', run: () => emit('create', 'record') },
            { id: 'new-dev', label: '添加设备', run: () => emit('create', 'device') },
            { id: 'new-agent', label: '添加智能体', run: () => emit('create', 'agent') },
            { id: 'new-auto', label: '新建自动化任务', run: () => emit('create', 'automation') },
          ]
        : [
            { id: 'need-login', label: '请先登录以访问工作区', disabled: true },
          ],
    },
    {
      id: 'view',
      label: '视图',
      items: [
        ...(authed
          ? [
              { id: 'cmdk', label: '命令面板…', shortcut: `${ctrl} K`, run: () => emit('openPalette') },
              { id: 'sidebar', label: '左侧导航栏', shortcut: `${ctrl} B`, checked: !props.sidebarCollapsed, run: () => emit('toggleSidebar') },
              { id: 'dock', label: 'Agent 侧板', shortcut: `${ctrl} J`, checked: props.dockOpen, run: () => emit('toggleDock') },
              { id: 'vd1', divider: true },
            ]
          : []),
        { id: 'theme-glass', label: '主题：Liquid Glass', checked: props.theme === 'glass', run: () => emit('setTheme', 'glass') },
        { id: 'theme-white', label: '主题：纯白', checked: props.theme === 'white', run: () => emit('setTheme', 'white') },
        { id: 'theme-paper', label: '主题：纸墨', checked: props.theme === 'paper', run: () => emit('setTheme', 'paper') },
        { id: 'vd2', divider: true },
        { id: 'mode-dark', label: '深色模式', checked: props.mode === 'dark', run: () => emit('toggleMode') },
        { id: 'motion-reduced', label: '减少动态效果', checked: !!props.reducedMotion, run: () => emit('toggleReducedMotion') },
      ],
    },
    {
      id: 'window',
      label: '窗口',
      items: [
        ...(authed
          ? [
              { id: 'back', label: '返回上一页', run: () => emit('back') },
              { id: 'refresh', label: '刷新同步与页面状态', run: () => emit('refresh') },
            ]
          : [
              { id: 'reload', label: '重新载入界面', run: () => window.location.reload() },
            ]),
        ...(windows
          ? [
              { id: 'win-div', divider: true },
              { id: 'win-min', label: '最小化', run: () => void control('minimize') },
              { id: 'win-max', label: maximized.value ? '还原' : '最大化', run: () => void control('toggleMaximize') },
              { id: 'win-close', label: '关闭到托盘', run: () => void control('close') },
            ]
          : []),
      ],
    },
  ]
})

function toggleMenu(id: MenuId) {
  openMenu.value = openMenu.value === id ? null : id
}

function stepMenu(delta: number) {
  if (!openMenu.value) return
  const order: MenuId[] = ['studiolo', 'workspace', 'view', 'window']
  const next = (order.indexOf(openMenu.value) + delta + order.length) % order.length
  openMenu.value = order[next] ?? null
}

function onPointerDown(event: PointerEvent) {
  if (openMenu.value && event.target instanceof Node && !barRef.value?.contains(event.target)) {
    openMenu.value = null
  }
}

function onKeyDown(event: KeyboardEvent) {
  if (!openMenu.value) return
  if (event.key === 'Escape') {
    event.stopPropagation()
    openMenu.value = null
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    stepMenu(1)
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    stepMenu(-1)
  }
}

onMounted(async () => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeyDown)
  if (windows) {
    try {
      await syncMaximized()
      const stop = await getCurrentWindow().onResized(() => { void syncMaximized().catch(() => {}) })
      if (disposed) stop()
      else unlisten = stop
    } catch { /* 忽略非桌面宿主 */ }
  }
})

onUnmounted(() => {
  disposed = true
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeyDown)
  unlisten?.()
})
</script>

<template>
  <header ref="barRef" class="ide-titlebar" data-tauri-drag-region aria-label="Studiolo 顶部菜单栏">
    <nav class="ide-menubar" role="menubar" aria-label="主菜单">
      <div v-for="menu in menus" :key="menu.id" class="ide-menu-group">
        <button
          type="button"
          class="ide-menu-btn"
          role="menuitem"
          aria-haspopup="menu"
          :aria-expanded="openMenu === menu.id"
          :class="{ 'is-open': openMenu === menu.id }"
          @click="toggleMenu(menu.id)"
          @pointerenter="openMenu && (openMenu = menu.id)"
        >
          {{ menu.label }}
        </button>
        <div v-if="openMenu === menu.id" class="ide-menu-pop mat-solid" role="menu" :aria-label="menu.label">
          <template v-for="item in menu.items" :key="item.id">
            <div v-if="item.divider" class="ide-menu-sep" role="separator" />
            <button
              v-else
              type="button"
              class="ide-menu-item"
              role="menuitem"
              :disabled="item.disabled"
              :class="{ 'is-danger': item.danger }"
              @click="exec(item)"
            >
              <span class="ide-menu-check" aria-hidden="true"><Check v-if="item.checked" :size="13" :stroke-width="2.2" /></span>
              <span class="ide-menu-label">{{ item.label }}</span>
              <span v-if="item.shortcut" class="ide-menu-kbd">{{ item.shortcut }}</span>
            </button>
          </template>
        </div>
      </div>
    </nav>

    <div class="ide-drag-spacer" data-tauri-drag-region />

    <div v-if="windows" class="ide-win-ctl">
      <button type="button" aria-label="最小化窗口" title="最小化" @click="control('minimize')"><Minus :size="14" :stroke-width="1.6" /></button>
      <button type="button" :aria-label="maximized ? '还原窗口' : '最大化窗口'" :title="maximized ? '还原' : '最大化'" @click="control('toggleMaximize')">
        <Copy v-if="maximized" :size="12" :stroke-width="1.6" /><Square v-else :size="12" :stroke-width="1.6" />
      </button>
      <button type="button" class="ide-win-close" aria-label="关闭到托盘" title="关闭到托盘" @click="control('close')"><X :size="14" :stroke-width="1.6" /></button>
    </div>
  </header>
</template>

<style scoped>
.ide-titlebar {
  position: relative;
  z-index: 90;
  display: flex;
  flex: none;
  align-items: center;
  height: 36px;
  padding-left: 8px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  backdrop-filter: var(--material-filter);
  -webkit-backdrop-filter: var(--material-filter);
  color: var(--text);
  user-select: none;
}
:global([data-theme="paper"]) .ide-titlebar { background: var(--bg); }

.ide-menubar {
  display: flex;
  align-items: center;
  gap: 2px;
  height: 100%;
}
.ide-menu-group { position: relative; display: flex; align-items: center; }
.ide-menu-btn {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 9px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-2);
  transition: background-color var(--dur-1), color var(--dur-1);
}
.ide-menu-btn:hover,
.ide-menu-btn.is-open {
  background: var(--surface-3);
  color: var(--text);
}

.ide-menu-pop {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 120;
  min-width: 210px;
  max-height: calc(100dvh - 54px);
  overflow-y: auto;
  padding: 5px;
  border-radius: var(--r-md);
  border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--solid) 97%, transparent);
  backdrop-filter: var(--material-filter);
  -webkit-backdrop-filter: var(--material-filter);
  box-shadow: var(--shadow-2);
}
.ide-menu-sep {
  height: 1px;
  margin: 4px 6px;
  background: var(--line);
}
.ide-menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 30px;
  padding: 0 8px;
  border-radius: 7px;
  font-size: 12.5px;
  color: var(--text);
  text-align: left;
  transition: background-color var(--dur-1), color var(--dur-1);
}
.ide-menu-item:hover:not(:disabled) { background: var(--surface-3); }
.ide-menu-item:disabled { opacity: .45; cursor: not-allowed; }
.ide-menu-item.is-danger { color: var(--danger); }
.ide-menu-check { display: inline-grid; place-items: center; width: 16px; flex: none; color: var(--accent); }
.ide-menu-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ide-menu-kbd { font-size: 11px; color: var(--text-3); margin-left: 12px; }

.ide-drag-spacer { flex: 1; min-width: 24px; height: 100%; }

.ide-win-ctl { display: flex; align-items: stretch; height: 100%; }
.ide-win-ctl button {
  display: grid;
  place-items: center;
  width: 46px;
  height: 36px;
  color: var(--text-2);
  border-radius: 0;
  transition: background-color var(--dur-1), color var(--dur-1);
}
.ide-win-ctl button:hover { background: var(--surface-3); color: var(--text); }
.ide-win-ctl .ide-win-close:hover { background: #c42b1c; color: #fff; }
</style>
