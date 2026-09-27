<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { KeyRound, MoreHorizontal, Power } from 'lucide-vue-next'
import StatusBadge from '../ui/StatusBadge.vue'
import type { ApiKeyPublic } from '../../types/api'

const props = defineProps<{ apiKey: ApiKeyPublic; busy?: boolean }>()
const emit = defineEmits<{ toggleStatus: [id: string] }>()
const root = ref<HTMLElement | null>(null)
const menuOpen = ref(false)

function onPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) menuOpen.value = false
}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') menuOpen.value = false }
function toggleStatus() {
  emit('toggleStatus', props.apiKey.id)
  menuOpen.value = false
}
function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '尚未使用'
}
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
  <article ref="root" class="api-key-card">
    <div class="api-key-card__heading">
      <span class="api-key-card__icon"><KeyRound :size="18" :stroke-width="1.8" /></span>
      <div class="api-key-card__name"><h3>{{ apiKey.name }}</h3><StatusBadge :label="apiKey.status === 'active' ? 'Active' : apiKey.status === 'expired' ? 'Expired' : 'Inactive'" :tone="apiKey.status === 'active' ? 'success' : 'neutral'" /></div>
      <div v-if="apiKey.status !== 'expired'" class="api-key-card__menu-wrap">
        <button class="icon-button api-key-card__more" type="button" :disabled="busy" :aria-label="`${apiKey.name} 更多操作`" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen"><MoreHorizontal :size="17" /></button>
        <div v-if="menuOpen" class="api-key-card__menu" role="menu">
          <button type="button" role="menuitem" :disabled="busy" @click="toggleStatus"><Power :size="14" />{{ apiKey.status === 'active' ? '停用密钥' : '启用密钥' }}</button>
        </div>
      </div>
    </div>
    <div class="api-key-card__secret"><code>{{ apiKey.masked_key }}</code></div>
    <div class="api-key-card__scopes" aria-label="权限 Scope"><span v-for="scope in apiKey.scopes" :key="scope">{{ scope }}</span></div>
    <div class="api-key-card__footer"><span>最后使用</span><time>{{ formatTime(apiKey.last_used_at) }}</time></div>
    <div class="api-key-card__footer"><span>到期时间</span><time>{{ apiKey.expires_at ? formatTime(apiKey.expires_at) : '永不过期' }}</time></div>
  </article>
</template>

<style scoped>
.api-key-card { position:relative; min-width:0; min-height:194px; padding:15px; border:var(--glass-tile-border); border-radius:16px; background:var(--glass-tile-background); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(var(--glass-blur)) saturate(125%); -webkit-backdrop-filter:blur(var(--glass-blur)) saturate(125%); color:var(--text-primary); transition:transform .22s ease,box-shadow .22s ease,background .22s ease; }
.api-key-card:hover { transform:translateY(-2px) scale(1.005); background:var(--glass-tile-hover-background); box-shadow:var(--glass-tile-hover-shadow); }
.api-key-card__heading { display:flex; align-items:flex-start; gap:9px; }
.api-key-card__icon { display:grid; width:32px; height:32px; flex:none; place-items:center; border:1px solid rgba(255,255,255,.8); border-radius:10px; color:var(--accent-deep); background:rgba(118,146,231,.15); }
.api-key-card__name { min-width:0; flex:1; }
.api-key-card__name h3 { margin:1px 0 6px; overflow:hidden; color:var(--text-primary); font-size:12px; font-weight:720; text-overflow:ellipsis; white-space:nowrap; }
.api-key-card__name :deep(.status-badge) { min-height:19px; padding:3px 7px; font-size:9px; }
.api-key-card__menu-wrap { position:relative; flex:none; }
.api-key-card__more { width:26px; height:26px; border-radius:8px; }
.api-key-card__menu { position:absolute; z-index:10; top:31px; right:0; min-width:125px; padding:5px; border:var(--glass-tile-border); border-radius:10px; background:rgba(251,252,255,.97); box-shadow:0 10px 22px rgba(31,46,88,.2); }
.api-key-card__menu button { display:flex; align-items:center; gap:7px; width:100%; padding:8px; border:0; border-radius:7px; color:var(--text-primary); background:transparent; font-size:10px; white-space:nowrap; }
.api-key-card__menu button:hover { background:rgba(109,140,224,.12); }
.api-key-card__secret { display:flex; align-items:center; justify-content:space-between; gap:5px; margin-top:13px; padding:7px 8px 7px 10px; border:1px solid rgba(143,165,208,.2); border-radius:9px; background:rgba(255,255,255,.45); }
.api-key-card__secret code { min-width:0; overflow:hidden; color:#566888; font-size:10px; letter-spacing:.005em; text-overflow:ellipsis; white-space:nowrap; }
.api-key-card__secret .icon-button { width:24px; height:24px; flex:none; border-radius:7px; }
.api-key-card__scopes { display:flex; flex-wrap:wrap; gap:5px; min-height:22px; margin-top:11px; }
.api-key-card__scopes span { display:inline-flex; align-items:center; min-height:20px; padding:3px 7px; border:1px solid rgba(110,140,215,.2); border-radius:6px; color:#5e76b1; background:rgba(130,157,228,.11); font-size:9px; font-weight:680; }
.api-key-card__footer { display:flex; justify-content:space-between; gap:8px; margin-top:12px; padding-top:10px; border-top:1px solid rgba(127,148,194,.17); color:var(--text-secondary); font-size:10px; }
.api-key-card__footer time { color:var(--text-primary); font-weight:650; white-space:nowrap; }
</style>
