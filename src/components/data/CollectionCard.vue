<script setup lang="ts">
import { ref } from 'vue'
import type { Component } from 'vue'
import { AppWindow, ArrowUpRight, Copy, FolderKanban, Globe2, HardDrive, Layers3, MoreHorizontal, Repeat2, Server } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { CollectionIcon, DataCollection } from '../../types/data'

defineProps<{ collection: DataCollection; selected: boolean }>()
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
.collection-card { position:relative; min-height:174px; --collection-accent:#718dea; --collection-wash:rgba(113,141,234,.2); }
.collection-card--violet { --collection-accent:#9472da; --collection-wash:rgba(148,114,218,.2); }
.collection-card--cyan { --collection-accent:#4ba5c1; --collection-wash:rgba(75,165,193,.2); }
.collection-card--mint { --collection-accent:#49ad98; --collection-wash:rgba(73,173,152,.2); }
.collection-card--amber { --collection-accent:#d7a353; --collection-wash:rgba(215,163,83,.2); }
.collection-card--rose { --collection-accent:#ce839f; --collection-wash:rgba(206,131,159,.2); }
.collection-card__select { display:flex; flex-direction:column; align-items:flex-start; width:100%; min-height:138px; padding:12px; border:var(--glass-tile-border); border-radius:14px; background:linear-gradient(140deg,rgba(250,251,255,.56),rgba(235,239,255,.34)); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); text-align:left; transition:background .2s ease,border-color .2s ease; }
.collection-card--selected .collection-card__select { border-color:rgba(164,191,255,.85); background:rgba(196,212,255,.58); }
.collection-card__icon { display:grid; width:42px; height:42px; place-items:center; border:1px solid rgba(255,255,255,.75); border-radius:14px; color:var(--collection-accent); background:linear-gradient(145deg,rgba(255,255,255,.94),var(--collection-wash)); box-shadow:0 7px 17px var(--collection-wash),inset 0 1px 0 rgba(255,255,255,.9); }
.collection-card__name { margin-top:12px; color:#1f2e4a; font-size:17px; line-height:1.2; font-weight:750; letter-spacing:-.025em; text-shadow:0 1px rgba(255,255,255,.42); }
.collection-card__description { margin-top:5px; color:#435574; font-size:11px; font-weight:590; line-height:1.35; text-shadow:0 1px rgba(255,255,255,.32); }
.collection-card__footer { display:flex; align-items:center; justify-content:space-between; gap:10px; width:100%; margin-top:auto; padding-top:10px; color:#435879; font-size:10px; font-weight:620; }
.collection-card__footer strong { color:var(--collection-accent); font-size:13px; font-weight:760; }
.collection-card__footer svg { color:var(--collection-accent); transition:transform .2s ease; }
.collection-card__select:hover .collection-card__footer svg { transform:translate(2px,-2px); }
.collection-card__menu-wrap { position:absolute; top:8px; right:8px; z-index:4; }
.collection-card__more { display:grid; width:30px; height:30px; place-items:center; border:1px solid rgba(255,255,255,.6); border-radius:9px; color:#7d8ba6; background:rgba(255,255,255,.5); }
.collection-card__more:hover,.collection-card__more[aria-expanded="true"] { color:#4d70d7; background:rgba(255,255,255,.84); }
.collection-card__menu { position:absolute; top:36px; right:0; display:grid; gap:2px; width:127px; padding:5px; border:1px solid rgba(255,255,255,.9); border-radius:11px; background:rgba(248,251,255,.97); box-shadow:0 11px 27px rgba(37,53,97,.2); backdrop-filter:blur(16px); }
.collection-card__menu button { display:flex; align-items:center; gap:7px; width:100%; padding:7px; border:0; border-radius:7px; color:#536580; background:transparent; font-size:10px; text-align:left; }
.collection-card__menu button:hover { color:#4d70d7; background:rgba(108,141,220,.11); }
</style>
