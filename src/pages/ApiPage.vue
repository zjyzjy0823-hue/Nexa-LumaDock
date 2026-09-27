<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus } from 'lucide-vue-next'
import ApiKeyCard from '../components/api/ApiKeyCard.vue'
import ApiRequestTable from '../components/api/ApiRequestTable.vue'
import ApiStatCard from '../components/api/ApiStatCard.vue'
import ApiUsageChart from '../components/api/ApiUsageChart.vue'
import CreateApiKeyModal from '../components/api/CreateApiKeyModal.vue'
import WebhookCard from '../components/api/WebhookCard.vue'
import TopActionControls from '../components/layout/TopActionControls.vue'
import ActionButton from '../components/ui/ActionButton.vue'
import GlassCard from '../components/ui/GlassCard.vue'
import Input from '../components/ui/Input.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { apiScopes, apiStats, apiUsage, initialApiKeys, initialWebhooks, recentApiRequests } from '../mock/api'
import type { ApiKey, ApiKeyDraft, ApiStat, Webhook } from '../types/api'

const emit = defineEmits<{ action: [message: string] }>()
const keys = ref<ApiKey[]>(initialApiKeys.map(key => ({ ...key, scopes: [...key.scopes] })))
const webhooks = ref<Webhook[]>(initialWebhooks.map(webhook => ({ ...webhook })))
const query = ref('')
const createOpen = ref(false)

const search = computed(() => query.value.trim().toLocaleLowerCase())
const visibleKeys = computed(() => keys.value.filter(key => !search.value ||
  `${key.name} ${key.maskedKey} ${key.scopes.join(' ')}`.toLocaleLowerCase().includes(search.value)))
const visibleRequests = computed(() => recentApiRequests.filter(request => !search.value ||
  `${request.method} ${request.path} ${request.status} ${request.durationMs}`.toLocaleLowerCase().includes(search.value)))
const visibleWebhooks = computed(() => webhooks.value.filter(webhook => !search.value ||
  `${webhook.name} ${webhook.url} ${webhook.method}`.toLocaleLowerCase().includes(search.value)))
const activeKeys = computed(() => keys.value.filter(key => key.status === 'active').length)
const totalWebhooks = Number(apiStats.find(stat => stat.id === 'webhooks')?.value ?? webhooks.value.length)
const stats = computed<ApiStat[]>(() => apiStats.map(stat => stat.id === 'keys'
  ? { ...stat, value: String(activeKeys.value), trend: activeKeys.value === keys.value.length ? '全部正常运行' : `${keys.value.length - activeKeys.value} 枚已停用` }
  : stat))

function openCreate() { createOpen.value = true }
defineExpose({ openCreate })

function createKey(draft: ApiKeyDraft) {
  const secret = `sk_live_${Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')}`
  keys.value.unshift({
    id: `key-${Date.now()}`,
    name: draft.name,
    status: 'active',
    maskedKey: `sk_live_••••••••${secret.slice(-4)}`,
    secret,
    scopes: draft.scopes,
    lastUsed: '尚未使用',
    expiration: draft.expiration,
  })
  createOpen.value = false
  query.value = ''
  emit('action', `已创建「${draft.name}」API Key（本地演示）。`)
}

function toggleKeyStatus(id: string) {
  const key = keys.value.find(item => item.id === id)
  if (!key) return
  key.status = key.status === 'active' ? 'inactive' : 'active'
  emit('action', `「${key.name}」已${key.status === 'active' ? '启用' : '停用'}。`)
}

async function copyKey(key: ApiKey) {
  try {
    await navigator.clipboard.writeText(key.secret)
    emit('action', `已复制「${key.name}」的演示 Key。`)
  } catch { emit('action', '复制失败，请检查浏览器权限。') }
}

function toggleWebhook(id: string, enabled: boolean) {
  const webhook = webhooks.value.find(item => item.id === id)
  if (!webhook) return
  webhook.enabled = enabled
  emit('action', `「${webhook.name}」已${enabled ? '启用' : '暂停'}。`)
}

async function copyWebhookUrl(url: string) {
  try { await navigator.clipboard.writeText(url); emit('action', 'Webhook URL 已复制。') }
  catch { emit('action', '复制失败，请检查浏览器权限。') }
}

function testWebhook(id: string) {
  const webhook = webhooks.value.find(item => item.id === id)
  if (webhook) emit('action', `「${webhook.name}」测试事件已模拟发送。`)
}
</script>

<template>
  <div class="api-page">
    <PageHeader title="API" eyebrow="">
      <template #actions>
        <div class="api-page__header-actions">
          <Input v-model="query" class="api-page__search" type="search" placeholder="搜索 API 资源..." aria-label="搜索 API 资源" />
          <TopActionControls :create-items="[]" :show-create="false" />
          <ActionButton class="api-page__create" @click="openCreate"><Plus :size="16" />创建 API Key</ActionButton>
        </div>
      </template>
    </PageHeader>

    <section class="api-page__stats" aria-label="API 概览">
      <ApiStatCard v-for="stat in stats" :key="stat.id" :stat="stat" />
    </section>

    <div class="api-page__workspace">
      <GlassCard class="api-page__keys" title="API Keys">
        <template #action><span class="api-page__section-count">{{ visibleKeys.length.toString().padStart(2, '0') }} KEYS</span></template>
        <p class="api-page__section-description">管理你的访问密钥与权限范围</p>
        <div v-if="visibleKeys.length" class="api-page__keys-grid">
          <ApiKeyCard v-for="key in visibleKeys" :key="key.id" :api-key="key" @copy="copyKey" @toggle-status="toggleKeyStatus" />
        </div>
        <div v-else class="api-page__empty">没有找到匹配的 API Key</div>
        <p class="api-page__security-note">密钥仅展示掩码和尾号。</p>
      </GlassCard>

      <ApiRequestTable class="api-page__requests" :requests="visibleRequests" />

      <aside class="api-page__aside" aria-label="Webhook 和使用情况">
        <GlassCard class="api-page__webhooks" title="Webhooks">
          <template #action><span class="api-page__section-count">{{ webhooks.length }} / {{ totalWebhooks }}</span></template>
          <p class="api-page__section-description">事件通知端点</p>
          <div v-if="visibleWebhooks.length" class="api-page__webhook-list"><WebhookCard v-for="webhook in visibleWebhooks" :key="webhook.id" :webhook="webhook" @toggle="toggleWebhook" @copy-url="copyWebhookUrl" @test="testWebhook" /></div>
          <div v-else class="api-page__empty">没有找到匹配的 Webhook</div>
        </GlassCard>
        <ApiUsageChart :points="apiUsage" />
      </aside>
    </div>

    <CreateApiKeyModal :open="createOpen" :scopes="apiScopes" @close="createOpen = false" @create="createKey" />
  </div>
</template>

<style scoped>
.api-page { min-width:0; padding:0 20px 36px; animation:glass-page-rise .42s ease backwards; }
.api-page :deep(.page-header__copy h1),.api-page :deep(.stat-card > *),.api-page :deep(.glass-card__header),.api-page__section-description,.api-page__security-note { animation:glass-content-fade .3s ease backwards; }
.api-page :deep(.page-header__eyebrow) { display:none; }
.api-page :deep(.page-header) { align-items:center; margin:3px 0 21px; }
.api-page__header-actions { display:flex; align-items:center; gap:9px; min-width:0; }
.api-page__search { width:228px; min-width:0; }
.api-page__header-actions :deep(.top-action-controls) { gap:0; }
.api-page__header-actions :deep(.topbar__icon-button) { width:39px; height:39px; border:1px solid rgba(255,255,255,.39); border-radius:11px; background:rgba(255,255,255,.16); backdrop-filter:blur(12px); }
.api-page__header-actions :deep(.topbar__icon-button svg) { width:18px; height:18px; }
.api-page__header-actions :deep(.notification-dot) { top:6px; right:6px; width:7px; height:7px; }
.api-page__stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:15px; }
.api-page__workspace { display:grid; grid-template-columns:minmax(0,1.12fr) minmax(0,1.25fr) minmax(250px,.8fr); align-items:start; gap:15px; min-width:0; }
.api-page__keys,.api-page__requests,.api-page__aside { min-width:0; }
.api-page__keys { min-height:437px; }
.api-page__keys :deep(.glass-card__body),.api-page__webhooks :deep(.glass-card__body) { overflow:visible; }
.api-page__section-count { padding:5px 8px; border:1px solid rgba(255,255,255,.38); border-radius:7px; color:rgba(255,255,255,.88); background:rgba(255,255,255,.13); font-size:9px; font-weight:720; letter-spacing:.06em; white-space:nowrap; }
.api-page__section-description { margin:-5px 0 15px; color:rgba(255,255,255,.75); font-size:10px; }
.api-page__keys-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:start; gap:10px; }
.api-page__security-note { margin:13px 0 0; color:rgba(255,255,255,.72); font-size:9px; }
.api-page__aside { display:grid; gap:15px; }
.api-page__webhooks { min-height:290px; }
.api-page__webhook-list { display:grid; gap:10px; }
.api-page__empty { display:grid; min-height:145px; place-items:center; color:rgba(255,255,255,.78); font-size:11px; text-align:center; }
@media (max-width:1480px) { .api-page__workspace { grid-template-columns:minmax(0,1fr) minmax(0,1.2fr); } .api-page__aside { grid-column:1 / -1; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:stretch; } }
@media (max-width:1120px) { .api-page__stats { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:1050px) { .api-page__workspace { grid-template-columns:minmax(0,1fr); } .api-page__aside { grid-column:auto; } }
@media (max-width:700px) { .api-page { padding:0 3px 30px; } .api-page :deep(.page-header) { align-items:stretch; } .api-page__header-actions { width:100%; } .api-page__search { flex:1; width:auto; } .api-page__aside { grid-template-columns:1fr; } }
@media (max-width:560px) { .api-page__stats { grid-template-columns:1fr; gap:10px; } .api-page__keys-grid { grid-template-columns:1fr; } }
@media (max-width:430px) { .api-page__header-actions { flex-wrap:wrap; } .api-page__search { flex-basis:calc(100% - 50px); } .api-page__create { margin-left:auto; } }
@media (prefers-reduced-motion:reduce) { .api-page,.api-page :deep(.page-header__copy h1),.api-page :deep(.stat-card > *),.api-page :deep(.glass-card__header),.api-page__section-description,.api-page__security-note { animation:none; } }
</style>
