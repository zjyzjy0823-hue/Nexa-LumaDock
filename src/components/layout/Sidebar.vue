<script setup lang="ts">
import {
  House, LayoutGrid, Monitor, Sparkle, Database, BookOpen,
  Zap, Braces, Settings, ChevronRight,
} from 'lucide-vue-next'
import { demoProfile } from '../../data/overview'

withDefaults(defineProps<{ activeItem: string; name?: string; avatar?: string | null }>(), {
  name: demoProfile.name, avatar: demoProfile.avatar,
})
const emit = defineEmits<{ select: [item: string] }>()

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
      <span class="brand__mark" aria-hidden="true">
        <svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M18 2.5 22.1 13.9 33.5 18 22.1 22.1 18 33.5 13.9 22.1 2.5 18 13.9 13.9 18 2.5Z" stroke="currentColor" stroke-width="2.15" stroke-linejoin="round" />
        </svg>
      </span>
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

    <button class="user" type="button" aria-label="打开用户设置" @click="emit('select', 'Settings')">
      <span class="user__avatar" aria-hidden="true"><img v-if="avatar" :src="avatar" alt="" /><span v-else>{{ name?.slice(0, 1).toUpperCase() }}</span></span>
      <span class="user__details"><strong>{{ name }}</strong><small>在线 <i /></small></span>
      <ChevronRight class="user__chevron" :size="15" :stroke-width="1.7" />
    </button>
  </aside>
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
.brand__mark svg { display: block; width: 30px; height: 30px; }
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
.user__details { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.user__details strong { max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; font-weight: 580; }
.user__details small { display: flex; align-items: center; gap: 8px; color: rgba(255,255,255,.72); font-size: 12px; }
.user__details i { width: 7px; height: 7px; border-radius: 50%; background: #73e5b4; box-shadow: 0 0 9px rgba(115,229,180,.64); }
.user__chevron { margin-left: auto; color: rgba(255,255,255,.67); }
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
  .brand__mark svg { width: 31px; height: 31px; }
  .sidebar__nav { flex-direction: row; flex: 1; align-items: center; justify-content: flex-start; gap: 2px; min-width: 0; margin-left: 12px; overflow-x: auto; scrollbar-width: none; }
  .sidebar__nav::-webkit-scrollbar { display: none; }
  .nav-item { width: 44px; min-width: 44px; min-height: 42px; }
  .nav-item:last-child { margin-top: 0; }
  .user { display: none; }
}
</style>
