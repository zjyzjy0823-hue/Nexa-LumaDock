<script setup lang="ts">
import { ref } from 'vue'
import type { Component } from 'vue'
import { AppWindow, ArrowUpRight, Copy, FolderKanban, Globe2, HardDrive, Layers3, MoreHorizontal, Repeat2, Server } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { CollectionIcon, CollectionSummary } from '../../types/data'

defineProps<{ collection: CollectionSummary; selected: boolean }>()
const emit = defineEmits<{ select: []; copy: []; edit: []; remove: [] }>()
const menuOpen = ref(false)

const icons: Record<CollectionIcon, Component> = {
  projects: FolderKanban,
  domains: Globe2,
  software: AppWindow,
  servers: Server,
  assets: HardDrive,
  subscriptions: Repeat2,
  custom: Layers3,
}

function selectCollection() {
  menuOpen.value = false
  emit('select')
}

function copyName() {
  menuOpen.value = false
  emit('copy')
}
</script>

<template>
  <GlassCard class="collection-card" :class="[`collection-card--${collection.tone}`, { 'collection-card--selected': selected }]">
    <button class="collection-card__select" type="button" :aria-label="`查看 ${collection.name} 集合`" :aria-pressed="selected" @click="selectCollection">
      <span class="collection-card__icon"><component :is="icons[collection.icon] ?? Layers3" :size="23" :stroke-width="1.8" /></span>
      <span class="collection-card__name">{{ collection.name }}</span>
      <span class="collection-card__description">{{ collection.description }}</span>
      <span class="collection-card__footer"><span><strong>{{ collection.recordCount }}</strong> 条记录</span><ArrowUpRight :size="16" :stroke-width="1.8" /></span>
    </button>
    <div class="collection-card__menu-wrap">
      <button class="collection-card__more" type="button" :aria-label="`${collection.name} 更多操作`" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen"><MoreHorizontal :size="18" /></button>
      <div v-if="menuOpen" class="collection-card__menu" role="menu">
        <button type="button" role="menuitem" @click="selectCollection"><ArrowUpRight :size="14" />查看记录</button>
        <button type="button" role="menuitem" @click="copyName"><Copy :size="14" />复制名称</button>
        <button type="button" role="menuitem" @click="menuOpen = false; emit('edit')">编辑集合</button>
        <button type="button" role="menuitem" @click="menuOpen = false; emit('remove')">删除集合</button>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.collection-card { position:relative; height:auto; min-height:0; padding:0; border:0; background:none; box-shadow:none; backdrop-filter:none; --collection-accent:#718dea; --collection-wash:rgba(113,141,234,.2); }
.collection-card :deep(.glass-card__body) { overflow:visible; }
.collection-card--violet { --collection-accent:#9472da; --collection-wash:rgba(148,114,218,.2); }
.collection-card--cyan { --collection-accent:#4ba5c1; --collection-wash:rgba(75,165,193,.2); }
.collection-card--mint { --collection-accent:#49ad98; --collection-wash:rgba(73,173,152,.2); }
.collection-card--amber { --collection-accent:#d7a353; --collection-wash:rgba(215,163,83,.2); }
.collection-card--rose { --collection-accent:#ce839f; --collection-wash:rgba(206,131,159,.2); }
.collection-card__select { display:grid; grid-template-columns:32px minmax(0,1fr); align-items:center; column-gap:9px; row-gap:3px; width:100%; min-height:69px; padding:9px 40px 9px 9px; border:var(--glass-tile-border); border-radius:10px; background:var(--workbench-solid); text-align:left; transition:background .2s ease,border-color .2s ease; }
.collection-card--selected .collection-card__select { border-color:var(--workbench-accent); background:var(--workbench-soft); }
.collection-card__icon { grid-row:1 / span 3; display:grid; width:32px; height:32px; place-items:center; border-radius:8px; color:var(--workbench-accent); background:var(--collection-wash); }
.collection-card__icon svg { width:17px; height:17px; }
.collection-card__name { overflow:hidden; color:var(--workbench-text); font-size:13px; line-height:1.25; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }
.collection-card__description { overflow:hidden; color:var(--workbench-muted); font-size:11px; line-height:1.3; text-overflow:ellipsis; white-space:nowrap; }
.collection-card__description:empty { display:none; }
.collection-card__footer { display:flex; align-items:center; justify-content:space-between; gap:6px; color:var(--workbench-muted); font-size:11px; }
.collection-card__footer > svg { display:none; }
.collection-card__footer strong { color:var(--collection-accent); font-size:13px; font-weight:760; }
.collection-card__footer svg { color:var(--collection-accent); transition:transform .2s ease; }
.collection-card__select:hover .collection-card__footer svg { transform:translate(2px,-2px); }
.collection-card__menu-wrap { position:absolute; top:8px; right:8px; z-index:4; }
.collection-card__more { display:grid; width:30px; height:30px; place-items:center; border:1px solid var(--workbench-line); border-radius:9px; color:var(--workbench-muted); background:var(--workbench-solid); }
.collection-card__more:hover,.collection-card__more[aria-expanded="true"] { color:var(--workbench-good); background:var(--workbench-soft); }
.collection-card__menu { position:absolute; top:36px; right:0; display:grid; gap:2px; width:127px; padding:5px; border:1px solid var(--workbench-line); border-radius:11px; background:var(--glass-popover-background); box-shadow:0 11px 27px rgba(37,53,97,.2);   backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.collection-card__menu button { display:flex; align-items:center; gap:7px; width:100%; padding:7px; border:0; border-radius:7px; color:var(--workbench-muted); background:transparent; font-size:10px; text-align:left; }
.collection-card__menu button:hover { color:var(--workbench-good); background:var(--workbench-overlay); }
</style>
