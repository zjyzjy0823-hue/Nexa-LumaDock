<script setup lang="ts">
import { ChevronRight, Cloud, Github, HardDrive, Plus } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { quickAccessItems, type QuickAccessItem } from '../../data/overview'

const emit = defineEmits<{
  add: []
  select: [id: string]
}>()

function handleClick(item: QuickAccessItem) {
  if (item.href) return
  if (item.id === 'add') emit('add')
  else emit('select', item.id)
}
</script>

<template>
  <GlassCard title="快捷访问" class="quick-access-card">
    <template #action><span class="card-chevron" aria-hidden="true"><ChevronRight :size="18" /></span></template>

    <div class="access-grid">
      <component
        :is="item.href ? 'a' : 'button'"
        v-for="item in quickAccessItems"
        :key="item.id"
        class="access-item"
        :class="`access-item--${item.icon}`"
        :href="item.href"
        :target="item.href ? '_blank' : undefined"
        :rel="item.href ? 'noopener noreferrer' : undefined"
        :type="item.href ? undefined : 'button'"
        :aria-label="item.icon === 'add' ? '添加快捷方式' : item.label"
        @click="handleClick(item)"
      >
        <span class="access-brand" aria-hidden="true">
          <svg v-if="item.icon === 'chatgpt'" class="chatgpt-mark" viewBox="0 0 24 24"><path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z" fill="currentColor" /></svg>
          <svg v-else-if="item.icon === 'claude'" class="claude-mark" viewBox="0 0 48 48" fill="none">
            <path d="M24 3v42M3 24h42M8.2 8.2l31.6 31.6m0-31.6L8.2 39.8M15.5 4.8l17 38.4M4.8 15.5l38.4 17M32.5 4.8l-17 38.4M43.2 15.5l-38.4 17" stroke="currentColor" stroke-width="3.1" stroke-linecap="round" />
          </svg>
          <Github v-else-if="item.icon === 'github'" :size="37" :stroke-width="2.5" fill="currentColor" />
          <svg v-else-if="item.icon === 'youtube'" class="youtube-mark" viewBox="0 0 40 30" aria-hidden="true"><rect x="1" y="2" width="38" height="26" rx="7" fill="currentColor" /><path d="m17 9 11 6-11 6Z" fill="white" /></svg>
          <span v-else-if="item.icon === 'notion'" class="notion-mark">N</span>
          <svg v-else-if="item.icon === 'gmail'" class="gmail-mark" viewBox="0 0 48 38" fill="none">
            <path d="M5 34V7l19 14L43 7v27" stroke="#EA4335" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M5 10v24" stroke="#4285F4" stroke-width="6" stroke-linecap="round" />
            <path d="M43 10v24" stroke="#34A853" stroke-width="6" stroke-linecap="round" />
            <path d="m5 7 19 14" stroke="#C5221F" stroke-width="6" stroke-linecap="round" />
            <path d="M43 7 24 21" stroke="#FBBC04" stroke-width="6" stroke-linecap="round" />
          </svg>
          <Cloud v-else-if="item.icon === 'cloudflare'" :size="40" :stroke-width="1.35" fill="currentColor" />
          <span v-else-if="item.icon === 'nas'" class="nas-mark"><HardDrive :size="27" :stroke-width="1.7" /></span>
          <Plus v-else :size="32" :stroke-width="1.75" />
        </span>
        <span class="access-label">{{ item.label }}</span>
      </component>
    </div>
  </GlassCard>
</template>

<style scoped>
.quick-access-card { min-width: 0; }
.quick-access-card :deep(.glass-card__header) { margin-bottom: 10px; }
.quick-access-card :deep(.glass-card__body) { display: flex; flex-direction: column; justify-content: safe center; }
.quick-access-card :deep(.glass-card__title) { color: #fff; font-size: 18px; font-weight: 580; text-shadow: 0 1px 10px rgba(37, 52, 94, .16); }
.quick-access-card :deep(.glass-card__title)::before { content: '✧'; display: inline-block; margin-right: 10px; color: #f6f8ff; font-size: 25px; line-height: 0; vertical-align: -2px; }
.card-chevron { display: grid; width: 24px; height: 24px; place-items: center; color: white; border: 1px solid rgba(255,255,255,.18); border-radius: 50%; background: rgba(255,255,255,.08); }
.access-grid { display: flex; flex-wrap: wrap; align-content: center; justify-content: center; gap: 12px 16px; width: 100%; padding: 6px 2px; }
.access-item { position: relative; display: flex; width: calc((100% - 64px) / 5); min-width: 0; min-height: 92px; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 10px 2px 7px; border: 1px solid rgba(255,255,255,.68); border-radius: 18px; color: #151b27; background: linear-gradient(140deg, rgba(250,251,255,.56), rgba(235,239,255,.34)); box-shadow: inset 0 1px 1px rgba(255,255,255,.7), 0 5px 14px rgba(31,42,89,.08); font: inherit; text-decoration: none; cursor: pointer; transition: transform .22s ease, background .22s ease, box-shadow .22s ease; }
.access-item:hover { z-index: 2; transform: scale(1.025); background: rgba(255,255,255,.7); box-shadow: inset 0 1px 1px white, 0 11px 23px rgba(20,32,76,.17); }
.access-item:focus-visible { outline: 2px solid white; outline-offset: 3px; }
.access-brand { display: grid; height: 46px; place-items: center; }
.access-brand :deep(svg) { display: block; }
.chatgpt-mark, .claude-mark { width: 38px; height: 38px; }
.access-item--claude .access-brand { color: #ef8854; }
.access-item--youtube .access-brand { color: #e43a3f; filter: drop-shadow(0 0 6px rgba(223,44,52,.18)); }
.access-item--cloudflare .access-brand { color: #f18412; }
.access-item--nas .access-brand { color: #3779f2; }
.access-item--add .access-brand { color: #1c2435; }
.notion-mark { display: grid; width: 34px; height: 34px; place-items: center; border: 3px solid currentColor; border-radius: 3px; box-shadow: 3px -3px 0 currentColor; font-family: Georgia, serif; font-size: 26px; font-weight: 800; line-height: 1; }
.nas-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 4px; color: #fff; background: linear-gradient(145deg, #4e9bff, #1960df); box-shadow: inset 0 1px rgba(255,255,255,.45), 0 2px 7px rgba(31,106,225,.22); }
.gmail-mark { width: 37px; height: 33px; }
.youtube-mark { width: 39px; height: 30px; }
.access-label { max-width: 100%; overflow: hidden; color: #1c2430; font-size: 13px; font-weight: 540; line-height: 1.15; letter-spacing: -.025em; text-overflow: ellipsis; white-space: nowrap; }
@container (max-width: 480px) {
  .quick-access-card { padding: 13px 14px; }
  .quick-access-card :deep(.glass-card__header) { margin-bottom: 11px; }
  .access-grid { gap: 7px; padding-inline: 4px; }
  .access-item { width: calc((100% - 28px) / 5); }
  .access-item { min-height: 70px; gap: 3px; padding: 5px 2px; border-radius: 14px; }
  .access-brand { height: 35px; }
  .access-brand :deep(svg) { max-width: 30px; max-height: 30px; }
  .notion-mark, .nas-mark { width: 27px; height: 27px; font-size: 20px; }
  .access-label { font-size: 11px; }
}
@container (max-width: 380px) {
  .access-item { width: calc((100% - 21px) / 4); }
}
@container (max-width: 280px) {
  .access-item { width: calc((100% - 14px) / 3); }
}
@container (max-height: 190px) {
  .access-item { min-height: 58px; }
  .access-brand { height: 27px; }
  .access-brand :deep(svg) { max-width: 25px; max-height: 25px; }
}
@media (max-width: 560px) { .quick-access-card :deep(.glass-card__header) { margin-bottom: 12px; } .access-grid { gap: 8px; padding-inline: 4px; } .access-item { width: calc((100% - 32px) / 5); min-height: 75px; border-radius: 15px; padding: 6px 1px; } .access-brand { height: 38px; } .access-brand :deep(svg) { max-width: 30px; max-height: 30px; } .notion-mark, .nas-mark { width: 27px; height: 27px; font-size: 20px; } .access-label { font-size: 10px; } }
@media (max-width: 560px) {
  @container (max-width: 380px) {
    .quick-access-card { padding: 12px; }
    .quick-access-card :deep(.glass-card__header) { margin-bottom: 10px; }
    .access-grid { gap: 6px; }
    .access-item { width: calc((100% - 18px) / 4); }
    .access-item { min-height: 66px; padding-block: 4px; }
    .access-brand { height: 32px; }
  }
}
</style>

