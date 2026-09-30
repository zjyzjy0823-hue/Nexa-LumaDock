<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ArrowUpRight, Copy, MoreHorizontal, RadioTower, Send } from 'lucide-vue-next'
import Toggle from '../ui/Toggle.vue'
import type { Webhook } from '../../types/api'

const props = defineProps<{ webhook: Webhook }>()
const emit = defineEmits<{ toggle: [id: string, enabled: boolean]; copyUrl: [url: string]; test: [id: string] }>()
const root = ref<HTMLElement | null>(null)
const menuOpen = ref(false)

function onPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) menuOpen.value = false
}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') menuOpen.value = false }
function copyUrl() { emit('copyUrl', props.webhook.url); menuOpen.value = false }
function test() { emit('test', props.webhook.id); menuOpen.value = false }
onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <article ref="root" class="webhook-card">
    <div class="webhook-card__top">
      <span class="webhook-card__icon"><RadioTower :size="17" :stroke-width="1.8" /></span>
      <div class="webhook-card__title"><h3>{{ webhook.name }}</h3><span>{{ webhook.enabled ? '已启用' : '已暂停' }}</span></div>
      <div class="webhook-card__more-wrap">
        <button class="icon-button webhook-card__more" type="button" :aria-label="`${webhook.name} 更多操作`" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen"><MoreHorizontal :size="17" /></button>
        <div v-if="menuOpen" class="webhook-card__menu" role="menu">
          <button type="button" role="menuitem" @click="copyUrl"><Copy :size="13" />复制 URL</button>
          <button type="button" role="menuitem" @click="test"><Send :size="13" />发送测试事件</button>
        </div>
      </div>
    </div>
    <div class="webhook-card__endpoint"><span>{{ webhook.method }}</span><code :title="webhook.url">{{ webhook.url }}</code><ArrowUpRight :size="13" /></div>
    <div class="webhook-card__footer"><span>事件推送</span><Toggle :model-value="webhook.enabled" :aria-label="`${webhook.name} 启用状态`" @update:model-value="enabled => emit('toggle', webhook.id, enabled)" /></div>
  </article>
</template>

<style scoped>
.webhook-card { position:relative; min-width:0; padding:12px; border:var(--glass-tile-border); border-radius:14px; background:var(--glass-tile-background); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(var(--glass-blur)) saturate(125%); -webkit-backdrop-filter:blur(var(--glass-blur)) saturate(125%); transition:transform .22s ease,box-shadow .22s ease; }
.webhook-card:hover { transform:translateY(-2px) scale(1.005); box-shadow:var(--glass-tile-hover-shadow); }
.webhook-card__top { display:flex; align-items:flex-start; gap:8px; }
.webhook-card__icon { display:grid; width:29px; height:29px; flex:none; place-items:center; border-radius:9px; color:var(--accent-deep); background:rgba(118,145,230,.14); }
.webhook-card__title { min-width:0; flex:1; }
.webhook-card__title h3 { margin:1px 0 3px; overflow:hidden; color:var(--text-primary); font-size:11px; font-weight:710; text-overflow:ellipsis; white-space:nowrap; }
.webhook-card__title span { color:var(--text-secondary); font-size:9px; }
.webhook-card__more-wrap { position:relative; flex:none; }
.webhook-card__more { width:24px; height:24px; border-radius:7px; }
.webhook-card__menu { position:absolute; z-index:10; top:29px; right:0; min-width:142px; padding:5px; border:var(--glass-tile-border); border-radius:10px; background:var(--glass-popover-background); box-shadow:0 10px 22px rgba(31,46,88,.2);  backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.webhook-card__menu button { display:flex; align-items:center; gap:7px; width:100%; padding:7px; border:0; border-radius:7px; color:var(--text-primary); background:transparent; font-size:10px; text-align:left; white-space:nowrap; }
.webhook-card__menu button:hover { background:rgba(109,140,224,.12); }
.webhook-card__endpoint { display:flex; align-items:center; gap:6px; min-width:0; margin-top:11px; padding:7px 8px; border:1px solid rgba(143,165,208,.19); border-radius:8px; background:rgba(255,255,255,.42); }
.webhook-card__endpoint span { flex:none; color:#7d66bf; font-size:9px; font-weight:780; }
.webhook-card__endpoint code { min-width:0; flex:1; overflow:hidden; color:#5b6b83; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
.webhook-card__endpoint > svg { flex:none; color:#97a5be; }
.webhook-card__footer { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:10px; padding:0 2px; color:var(--text-secondary); font-size:10px; }
</style>
