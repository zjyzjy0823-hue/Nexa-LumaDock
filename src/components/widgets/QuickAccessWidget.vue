<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronRight, Plus } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { useAuthStore } from '../../stores/auth'
import { useWebsitesStore } from '../../stores/websites'
import type { Website } from '../../types/website'

const auth = useAuthStore()
const websites = useWebsitesStore()
const recent = computed(() => websites.recent)
const failedIcons = ref(new Set<string>())

onMounted(() => {
  if (auth.token) void websites.loadRecent(auth.token).catch(() => {})
})

function openWebsite(item: Website) {
  if (auth.token) void websites.visit(auth.token, item.id).catch(() => {})
}
function markIconFailed(id: string) { failedIcons.value.add(id) }
</script>

<template>
  <GlassCard title="快捷访问" class="quick-access-card">
    <template #action><span class="card-chevron" aria-hidden="true"><ChevronRight :size="18" /></span></template>
    <div class="access-grid">
      <a v-for="item in recent" :key="item.id" class="access-item" :href="item.url" target="_blank" rel="noopener noreferrer" :aria-label="`打开 ${item.name}`" @click="openWebsite(item)">
        <span class="access-brand" aria-hidden="true">
          <img v-if="item.icon && /^https?:\/\//.test(item.icon) && !failedIcons.has(item.id)" :src="item.icon" alt="" @error="markIconFailed(item.id)" />
          <span v-else class="access-initial">{{ item.name.slice(0, 1).toUpperCase() }}</span>
        </span>
        <span class="access-label">{{ item.name }}</span>
      </a>
      <a class="access-item access-item--add" href="/websites" aria-label="添加网站">
        <span class="access-brand" aria-hidden="true"><Plus :size="32" :stroke-width="1.75" /></span>
        <span class="access-label">添加</span>
      </a>
    </div>
    <p v-if="websites.recentError" class="access-hint" role="alert">数据加载失败 <button type="button" @click="auth.token && websites.loadRecent(auth.token)">重试</button></p>
    <p v-else-if="!recent.length" class="access-hint">{{ websites.recentLoading ? '正在加载网站…' : '暂无快捷网站，打开网站后会显示在这里。' }}</p>
  </GlassCard>
</template>

<style scoped>
.quick-access-card { min-width: 0; }
.quick-access-card :deep(.glass-card__header) { margin-bottom: 10px; }
.quick-access-card :deep(.glass-card__body) { display: flex; flex-direction: column; justify-content: safe center; }
.quick-access-card :deep(.glass-card__title) { color: #fff; font-size: 18px; font-weight: 580; text-shadow: 0 1px 10px rgba(37,52,94,.16); }
.quick-access-card :deep(.glass-card__title)::before { content: '✧'; display: inline-block; margin-right: 10px; color: #f6f8ff; font-size: 25px; line-height: 0; vertical-align: -2px; }
.card-chevron { display: grid; width: 24px; height: 24px; place-items: center; color: white; border: 1px solid rgba(255,255,255,.18); border-radius: 50%; background: rgba(255,255,255,.08); }
.access-grid { display: flex; flex-wrap: wrap; align-content: center; justify-content: center; gap: 12px 16px; width: 100%; padding: 6px 2px; }
.access-item { position: relative; display: flex; width: calc((100% - 64px) / 5); min-width: 0; min-height: 92px; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 10px 2px 7px; border: 1px solid rgba(255,255,255,.68); border-radius: 18px; color: #151b27; background: linear-gradient(140deg,rgba(250,251,255,.56),rgba(235,239,255,.34)); box-shadow: inset 0 1px 1px rgba(255,255,255,.7),0 5px 14px rgba(31,42,89,.08); font: inherit; text-decoration: none; cursor: pointer; transition: transform .22s ease, background .22s ease, box-shadow .22s ease; }
.access-item:hover { z-index: 2; transform: scale(1.025); background: rgba(255,255,255,.7); box-shadow: inset 0 1px 1px white,0 11px 23px rgba(20,32,76,.17); }
.access-item:focus-visible { outline: 2px solid white; outline-offset: 3px; }
.access-brand { display: grid; height: 46px; place-items: center; color: #3e62ba; }
.access-brand img { width: 38px; height: 38px; object-fit: contain; }
.access-initial { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 12px; background: rgba(255,255,255,.72); font-size: 22px; font-weight: 760; }
.access-item--add .access-brand { color: #1c2435; }
.access-label { max-width: 100%; overflow: hidden; color: #1c2430; font-size: 13px; font-weight: 540; line-height: 1.15; letter-spacing: -.025em; text-overflow: ellipsis; white-space: nowrap; }
.access-hint { margin: 4px 0 0; color: rgba(255,255,255,.84); font-size: 11px; text-align: center; }
@container (max-width: 480px) { .quick-access-card { padding: 13px 14px; } .access-grid { gap: 7px; padding-inline: 4px; } .access-item { width: calc((100% - 28px) / 5); min-height: 70px; gap: 3px; padding: 5px 2px; border-radius: 14px; } .access-brand { height: 35px; } .access-brand img, .access-initial { width: 30px; height: 30px; font-size: 17px; } .access-label { font-size: 11px; } }
@container (max-width: 380px) { .access-item { width: calc((100% - 21px) / 4); } }
@container (max-width: 280px) { .access-item { width: calc((100% - 14px) / 3); } }
@media (max-width: 560px) { .access-grid { gap: 8px; } .access-item { min-height: 75px; } }
</style>
