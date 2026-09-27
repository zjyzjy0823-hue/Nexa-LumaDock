<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  House, LayoutGrid, Monitor, Sparkle, Database, BookOpen,
  Zap, Braces, Settings, ChevronRight, LogOut,
} from 'lucide-vue-next'
import { useAuthStore } from '../../stores/auth'

const props = defineProps<{ activeItem: string; name?: string; avatar?: string | null }>()
const auth = useAuthStore()
const displayName = computed(() => props.name ?? auth.user?.username ?? (auth.token ? 'Nexa' : '访客'))
const displayAvatar = computed(() => auth.user ? (props.avatar ?? auth.user.avatar ?? '/avatar-doodle.svg') : null)
const emit = defineEmits<{ select: [item: string] }>()
const menuOpen = ref(false)
const userButton = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const menuLeft = ref(12)
const menuTop = ref(0)

function positionMenu() {
  const rect = userButton.value?.getBoundingClientRect()
  if (!rect) return
  menuLeft.value = Math.max(12, Math.min(rect.right - 220, window.innerWidth - 232))
  menuTop.value = rect.top >= 110 ? rect.top - 100 : rect.bottom + 8
}
function toggleMenu() { positionMenu(); menuOpen.value = !menuOpen.value }
function onPointerDown(event: PointerEvent) {
  const target = event.target as Node
  if (!userButton.value?.contains(target) && !menu.value?.contains(target)) menuOpen.value = false
}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') menuOpen.value = false }
function logout() { menuOpen.value = false; auth.logout() }
onMounted(() => { document.addEventListener('pointerdown', onPointerDown); document.addEventListener('keydown', onKeydown); window.addEventListener('resize', positionMenu) })
onUnmounted(() => { document.removeEventListener('pointerdown', onPointerDown); document.removeEventListener('keydown', onKeydown); window.removeEventListener('resize', positionMenu) })

const navItems = [
  { key: 'Home', label: '首页', icon: House },
  { key: 'Websites', label: '网站', icon: LayoutGrid },
  { key: 'Devices', label: '设备', icon: Monitor },
  { key: 'Agents', label: '智能体', icon: Sparkle },
  { key: 'Data', label: '数据', icon: Database },
  { key: 'Ledger', label: '账本', icon: BookOpen },
  { key: 'Automation', label: '自动化', icon: Zap },
  { key: 'API', label: 'API', icon: Braces },
  { key: 'Settings', label: '设置', icon: Settings },
]
</script>

<template>
  <aside class="sidebar" aria-label="主导航">
    <div class="brand">
      <span class="brand__mark" aria-hidden="true"><img src="/nexa-app-icon.png" alt="" /></span>
      <span class="brand__name">Nexa</span>
    </div>

    <nav class="sidebar__nav" aria-label="主菜单">
      <button
        v-for="item in navItems"
        :key="item.key"
        class="nav-item"
        :class="{ 'nav-item--active': activeItem === item.key }"
        :title="item.label"
        :aria-current="activeItem === item.key ? 'page' : undefined"
        type="button"
        @click="emit('select', item.key)"
      >
        <component :is="item.icon" :size="23" :stroke-width="1.85" />
        <span class="nav-item__label">{{ item.label }}</span>
      </button>
    </nav>

    <button ref="userButton" class="user" type="button" aria-label="账户菜单" aria-haspopup="menu" :aria-expanded="menuOpen" @click="toggleMenu">
      <span class="user__avatar" :class="{ 'user__avatar--guest': !auth.user }" aria-hidden="true"><img v-if="displayAvatar" :src="displayAvatar" alt="" /><span v-else>{{ auth.user ? displayName.slice(0, 1).toUpperCase() : '未登录' }}</span></span>
      <span class="user__details"><strong>{{ displayName }}</strong><small>{{ auth.user ? '在线' : '未登录' }} <i :class="{ 'user__offline': !auth.user }" /></small></span>
      <ChevronRight class="user__chevron" :size="15" :stroke-width="1.7" :class="{ 'user__chevron--open': menuOpen }" />
    </button>
  </aside>
  <Teleport to="body"><div v-if="menuOpen" ref="menu" class="account-menu" role="menu" :style="{ left: `${menuLeft}px`, top: `${menuTop}px` }">
    <div class="account-menu__identity"><strong>{{ displayName }}</strong><small>已登录 Nexa</small></div>
    <button type="button" role="menuitem" @click="logout"><LogOut :size="16" />退出登录</button>
  </div></Teleport>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: max(16px, calc((100dvh - 824px) / 2));
  display: flex;
  flex-direction: column;
  width: 177px;
  height: min(824px, calc(100dvh - 32px));
  min-height: 0;
  padding: 13px 12px 14px;
  overflow-x: hidden;
  overflow-y: auto;
  color: #fff;
  border: 1px solid rgba(255,255,255,.29);
  border-radius: 20px;
  background: linear-gradient(160deg, rgba(88,112,169,.51), rgba(48,67,113,.42) 65%, rgba(43,59,99,.48));
  box-shadow: 0 20px 42px rgba(25,38,78,.19), inset 0 1px 0 rgba(255,255,255,.22);
  backdrop-filter: blur(29px) saturate(125%);
  -webkit-backdrop-filter: blur(29px) saturate(125%);
}
.sidebar::before {
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, rgba(255,255,255,.11), transparent 56%);
  content: '';
  pointer-events: none;
}
.brand, .sidebar__nav, .user { position: relative; z-index: 1; }
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: none;
  height: 56px;
  padding: 0 11px 10px;
  transform: translateY(-9px);
  white-space: nowrap;
}
.brand__mark { display: grid; width: 30px; height: 36px; flex: none; place-items: center; }
.brand__mark img { display: block; width: 30px; height: 30px; border-radius: 8px; object-fit: cover; box-shadow: 0 2px 8px rgba(22,37,89,.2); }
.brand__name { font-size: 24px; font-weight: 520; letter-spacing: -.045em; }
.sidebar__nav { display: flex; flex: 1; flex-direction: column; gap: 2px; margin-top: 0; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
  min-height: 51px;
  padding: 0 14px;
  color: rgba(255,255,255,.87);
  border: 1px solid transparent;
  border-radius: 14px;
  background: transparent;
  text-align: left;
  transition: transform .18s ease, background .18s ease, box-shadow .18s ease, color .18s ease;
}
.nav-item:hover { color: #fff; background: rgba(255,255,255,.13); transform: translateX(2px); }
.nav-item--active, .nav-item--active:hover {
  color: #fff;
  border-color: rgba(255,255,255,.21);
  background: linear-gradient(110deg, rgba(218,232,255,.22), rgba(185,210,255,.12));
  box-shadow: inset 0 1px 0 rgba(255,255,255,.16), 0 8px 22px rgba(28,43,95,.13);
  transform: none;
}
.nav-item svg { flex: none; }
.nav-item__label { font-size: 14px; font-weight: 480; white-space: nowrap; }
.nav-item:last-child { margin-top: auto; }
.user {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 66px;
  margin-top: 15px;
  padding: 12px 8px 2px;
  color: #fff;
  border: 0;
  border-top: 1px solid rgba(255,255,255,.16);
  background: none;
  text-align: left;
}
.user__avatar {
  display: grid;
  width: 48px;
  height: 48px;
  flex: none;
  place-items: center;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.62);
  border-radius: 50%;
  background: radial-gradient(circle at 32% 22%, #f5d5e5, #aa94bd 45%, #354061 73%);
  box-shadow: 0 4px 12px rgba(23,28,64,.2), inset 0 1px 0 rgba(255,255,255,.72);
}
.user__avatar img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: center; }
.user__avatar > span { color: #fff; font-size: 19px; font-weight: 700; }
.user__avatar--guest { background:#fff; box-shadow:0 4px 12px rgba(23,28,64,.12); }
.user__avatar--guest > span { color:#52679b; font-size:12px; }
.user__details { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.user__details strong { max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; font-weight: 580; }
.user__details small { display: flex; align-items: center; gap: 8px; color: rgba(255,255,255,.72); font-size: 12px; }
.user__details i { width: 7px; height: 7px; border-radius: 50%; background: #73e5b4; box-shadow: 0 0 9px rgba(115,229,180,.64); }
.user__details .user__offline { background: #a9b4c9; box-shadow: none; }
.user__chevron { margin-left: auto; color: rgba(255,255,255,.67); }
.user__chevron--open { transform:rotate(-90deg); }
.account-menu { position:fixed; z-index:200; width:220px; padding:8px; color:#354b71; border:1px solid rgba(255,255,255,.75); border-radius:14px; background:rgba(249,252,255,.96); box-shadow:0 15px 36px rgba(26,39,84,.24); backdrop-filter:blur(24px); }
.account-menu__identity { display:grid; gap:3px; padding:8px 10px 10px; border-bottom:1px solid rgba(130,151,195,.2); }.account-menu__identity strong { font-size:13px; }.account-menu__identity small { color:#8493ae; font-size:11px; }
.account-menu button { display:flex; align-items:center; gap:9px; width:100%; margin-top:5px; padding:9px 10px; color:#ad5361; border:0; border-radius:8px; background:transparent; font-size:12px; text-align:left; cursor:pointer; }.account-menu button:hover { background:#f8edf0; }
@media (max-width: 1279px) {
  .sidebar { width: 100%; align-items: center; padding: 13px 8px 12px; }
  .brand { height: 56px; padding: 0 0 10px; transform: none; }
  .brand__name, .nav-item__label, .user__details, .user__chevron { display: none; }
  .sidebar__nav { width: 100%; align-items: center; }
  .nav-item { justify-content: center; width: 56px; min-height: 50px; padding: 0; }
  .user { justify-content: center; padding-inline: 0; }
  .user__avatar { width: 43px; height: 43px; }
}
@media (max-width: 700px) {
  .sidebar { position: relative; top: auto; flex-direction: row; width: 100%; height: 64px; min-height: 0; padding: 8px 10px; border-radius: 18px; }
  .brand { height: 46px; padding: 0; }
  .brand__mark { width: 28px; height: 36px; }
  .brand__mark img { width: 31px; height: 31px; }
  .sidebar__nav { flex-direction: row; flex: 1; align-items: center; justify-content: flex-start; gap: 2px; min-width: 0; margin-left: 12px; overflow-x: auto; scrollbar-width: none; }
  .sidebar__nav::-webkit-scrollbar { display: none; }
  .nav-item { width: 44px; min-width: 44px; min-height: 42px; }
  .nav-item:last-child { margin-top: 0; }
  .user { display:flex; width:43px; min-height:43px; flex:none; justify-content:center; margin:0; padding:0; border-top:0; }
  .user__avatar { width:38px; height:38px; }
}
</style>
