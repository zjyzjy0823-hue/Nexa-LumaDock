<script setup lang="ts">
import { computed, ref } from 'vue'
import { ExternalLink as ExternalIcon, RefreshCw } from 'lucide-vue-next'
import ExternalLink from './ExternalLink.vue'
import { useFleetStore } from '../../stores/fleet'
import type { SubscriptionQuota, SubscriptionQuotaProvider, SubscriptionQuotaWindow } from '../../types/fleet'

const emit = defineEmits<{ signIn: []; action: [message: string] }>()
const demo = import.meta.env.DEV && new URLSearchParams(location.search).get('subscription-quota-demo') === '1'
const fleet = useFleetStore()
const selectedIds = ref<Partial<Record<SubscriptionQuotaProvider, string>>>({})
const providers = [{ id: 'codex', label: 'Codex' }, { id: 'opencode', label: 'OpenCode Go' }] as const
const clock = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const percent = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 })

function demoQuota(provider: SubscriptionQuotaProvider): SubscriptionQuota {
  const now = Math.floor(Date.now() / 1000)
  const windows: SubscriptionQuotaWindow[] = provider === 'codex' ? [
    { group: 'Codex', kind: 'primary', remainingPercent: 72, windowMinutes: 300, resetsAt: now + 7200 },
    { group: 'Codex', kind: 'secondary', remainingPercent: 41, windowMinutes: 10080, resetsAt: now + 259200 },
  ] : [
    { group: 'OpenCode Go', kind: 'primary', remainingPercent: 84, windowMinutes: 300, resetsAt: now + 10800 },
    { group: 'OpenCode Go', kind: 'secondary', remainingPercent: 63, windowMinutes: 10080, resetsAt: now + 259200 },
    { group: 'OpenCode Go', kind: 'monthly', remainingPercent: 46, windowMinutes: null, resetsAt: now + 950400 },
  ]
  return { status: 'ready', checkedAt: now, windows }
}

const rows = computed(() => providers.map(provider => {
  const nodes = fleet.nodes.filter(node => node.adapters.some(adapter => adapter.provider === provider.id))
  const node = nodes.find(item => item.id === selectedIds.value[provider.id])
    ?? nodes.find(item => item.status === 'online') ?? nodes[0]
  const key = node ? `${provider.id}:${node.id}` : ''
  return {
    ...provider, nodes, node,
    quota: demo ? demoQuota(provider.id) : fleet.subscriptionQuotas[key],
    busy: Boolean(fleet.subscriptionQuotaLoading[key]),
    canRead: !demo && fleet.usageOrigin !== null && node?.status === 'online',
  }
}))

function status(row: (typeof rows.value)[number]) {
  if (demo) return '示例数据'
  if (row.busy) return '正在读取额度…'
  if (fleet.coreSignInUrl) return '登录 Core Fleet 后可读取'
  if (!row.node) return `连接启用 ${row.id === 'opencode' ? 'OpenCode' : 'Codex'} 的 Agent Node 后可读取`
  if (row.node.status !== 'online' || row.quota?.status === 'offline') return '节点离线'
  if (row.quota?.status === 'no_data') return row.id === 'opencode'
    ? '未返回 Go 额度，请检查节点的 Console 登录或 Go API Key'
    : 'Codex 未返回订阅额度'
  if (row.quota?.status === 'unsupported') return '当前 Core 或 Agent Node 版本暂不支持读取'
  if (row.quota?.status === 'unavailable') return `读取失败，请检查 ${row.label} 连接`
  return row.quota?.checkedAt ? `读取于 ${clock.format(row.quota.checkedAt * 1000)}` : '点击读取额度'
}

function windowLabel(window: SubscriptionQuotaWindow) {
  if (window.kind === 'monthly') return '月度额度'
  if (window.group === 'OpenCode Go' && window.kind === 'secondary') return '每周额度'
  const minutes = window.windowMinutes
  if (!minutes) return window.kind === 'primary' ? '主要额度' : '次要额度'
  if (minutes % 1440 === 0) return `${minutes / 1440} 天额度`
  if (minutes % 60 === 0) return `${minutes / 60} 小时额度`
  return `${minutes} 分钟额度`
}
</script>

<template>
  <div class="quota-panel">
    <section v-for="row in rows" :key="row.id" class="quota-provider" :aria-label="`${row.label} 订阅额度`">
      <div class="provider-head">
        <div class="provider-copy">
          <strong>{{ row.label }}</strong>
          <span v-if="row.nodes.length === 1 && !demo" class="faint">{{ row.node?.name }}</span>
        </div>
        <select v-if="row.nodes.length > 1 && !demo" class="input quota-node" :aria-label="`${row.label} 节点`"
          :value="row.node?.id" @change="selectedIds[row.id] = ($event.target as HTMLSelectElement).value">
          <option v-for="item in row.nodes" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
        <button v-if="row.id === 'codex' && fleet.coreSignInUrl && !demo" class="btn btn-sm btn-subtle quota-action" type="button" @click="emit('signIn')">登录 Core Fleet</button>
        <button v-if="row.canRead && row.node" class="btn btn-sm btn-subtle quota-action" type="button" :disabled="row.busy" @click="fleet.refreshSubscriptionQuota(row.node.id, row.id)">
          <RefreshCw :size="13" aria-hidden="true" /> {{ row.quota ? '刷新额度' : '读取额度' }}
        </button>
        <ExternalLink v-if="row.id === 'opencode'" class="btn btn-sm btn-subtle quota-action" href="https://opencode.ai/console" @action="emit('action', $event)">
          打开控制台 <ExternalIcon :size="12" aria-hidden="true" />
        </ExternalLink>
      </div>

      <div v-if="row.quota?.windows.length" class="quota-windows">
        <div v-for="(window, index) in row.quota.windows" :key="`${window.group}-${window.kind}-${index}`" class="quota-window">
          <div class="quota-window-heading">
            <span>{{ window.group === row.label ? windowLabel(window) : `${window.group} · ${windowLabel(window)}` }}</span>
            <strong class="num">剩余 {{ percent.format(window.remainingPercent) }}%</strong>
          </div>
          <div class="quota-meter" role="meter" :aria-label="`${window.group} ${windowLabel(window)}剩余比例`"
            aria-valuemin="0" aria-valuemax="100" :aria-valuenow="window.remainingPercent">
            <span :style="{ width: `${window.remainingPercent}%` }"></span>
          </div>
          <small v-if="window.resetsAt" class="faint">{{ clock.format(window.resetsAt * 1000) }} 重置</small>
        </div>
      </div>
      <p class="quota-status faint" role="status">{{ status(row) }}</p>
    </section>
  </div>
</template>

<style scoped>
.quota-panel { display: grid; align-content: start; gap: 0; min-height: 0; flex: 1; overflow-y: auto; }
.quota-provider { display: grid; gap: 12px; padding: 12px 0 16px; }
.quota-provider + .quota-provider { border-top: 1px solid var(--line); }
.provider-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.provider-copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.provider-copy strong { font-size: 13px; font-weight: 650; }
.provider-copy span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; }
.quota-node { width: auto; max-width: 132px; min-height: 26px; padding: 2px 6px; font-size: 11.5px; }
.quota-action { display: inline-flex; gap: 5px; align-items: center; white-space: nowrap; }
.quota-windows { display: grid; gap: 12px; }
.quota-window { display: grid; gap: 5px; }
.quota-window-heading { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 10px; font-size: 12px; }
.quota-meter { overflow: hidden; height: 5px; border-radius: 9px; background: var(--surface-3); }
.quota-meter span { display: block; height: 100%; border-radius: inherit; background: var(--text); }
.quota-window small, .quota-status { font-size: 11px; }
.quota-status { margin: 0; }
</style>
