<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity,
  Bookmark,
  Gauge,
  Database,
  LayoutGrid,
  ChartNoAxesCombined,
  Plus,
  RefreshCw,
  Server,
  Settings,
  Sparkles,
  Tag,
  Wallet,
} from 'lucide-vue-next'
import ExternalLink from '../components/ui/ExternalLink.vue'
import DashboardGauge from '../components/ui/DashboardGauge.vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import TokenUsageChart from '../components/ui/TokenUsageChart.vue'
import SubscriptionQuotaPanel from '../components/ui/SubscriptionQuotaPanel.vue'
import type { SyncStatus } from '../api/sync'
import { useAuthStore } from '../stores/auth'
import { useLedgerStore } from '../stores/ledger'
import { useAutomationStore } from '../stores/automation'
import { useWebsitesStore } from '../stores/websites'
import { useDataStore } from '../stores/data'
import { useDevicesStore } from '../stores/devices'
import { useFleetStore } from '../stores/fleet'
import { websiteService } from '../services/websites'
import { localDateKey, localMonthKey } from '../services/localTime'
import type { RecordedTokenUsage } from '../services/recordedTokenUsage'
import type { FleetUsageDay } from '../types/fleet'
import type { Website } from '../types/website'

type RangeMode = '7d' | 'month'
type BookmarkStyle = 'pill' | 'card' | 'icon'

const props = defineProps<{
  mobile: boolean
  syncStatus: SyncStatus | null
  syncLabel: string
  syncKind: 'offline' | 'pending' | 'synced' | 'conflict'
}>()

const emit = defineEmits<{
  navigate: [page: string]
  create: [kind: string, value?: string]
  action: [message: string]
  sync: []
  askAgent: []
}>()

const auth = useAuthStore()
const ledger = useLedgerStore()
const automation = useAutomationStore()
const websites = useWebsitesStore()
const failedBookmarkIcons = ref<Record<string, string | null>>({})
const dataStore = useDataStore()
const devicesStore = useDevicesStore()
const fleet = useFleetStore()

const allSites = ref<Website[]>([])
const recentTxIds = ref<string[]>([])
const range = ref<RangeMode>(localStorage.getItem('studiolo:home-range') === 'month' ? 'month' : '7d')
const storedBookmarkStyle = localStorage.getItem('studiolo:bookmark-style')
const bookmarkStyle = ref<BookmarkStyle>(
  storedBookmarkStyle === 'card' || storedBookmarkStyle === 'icon' || storedBookmarkStyle === 'pill'
    ? storedBookmarkStyle
    : 'pill',
)

// 两段式数据加载动效控制：骨架屏 -> 数据入场递增 / 生长动画
const refreshing = ref(false)
const revealSeq = ref(0)
const gaugeProgress = ref(0)
const balanceProgress = ref(0)
const animBalance = ref(0)
const animActive = ref(0)
const animRecords = ref(0)
let refreshTimer: ReturnType<typeof setTimeout> | undefined
let countFrame: number | undefined

const now = new Date()
const tokenUsageDemo = import.meta.env.DEV && new URLSearchParams(window.location.search).get('token-usage-demo') === '1'
const tokenRecords = computed<ReadonlyMap<string, RecordedTokenUsage>>(() => {
  if (!tokenUsageDemo) return fleet.recordedTokenUsage
  const records = new Map<string, RecordedTokenUsage>()
  const dailyRequests = [11, 45, 16, 0, 62, 9, 24, 0, 18, 7, 4, 15, 0, 5]
  const dailySize = [90, 36, 105, 0, 72, 190, 44, 0, 58, 115, 201, 35, 0, 60]
  dailyRequests.forEach((requests, daysAgo) => {
    const recordedAt = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysAgo, 9).getTime()
    for (let index = 0; index < requests; index++) {
      const input = dailySize[daysAgo]! * (780 + index % 8 * 43)
      const cached = Math.round(input * (0.65 + daysAgo % 4 * 0.06))
      const output = (index % 7 + 2) * 1370
      records.set(`${daysAgo}-${index}`, { recordedAt, cached, otherInput: input - cached, output, other: 0, total: input + output })
    }
  })
  return records
})
const monthKey = localMonthKey(now.toISOString())

const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' })

function setRange(next: RangeMode) {
  if (range.value === next) return
  range.value = next
  localStorage.setItem('studiolo:home-range', next)
  triggerRevealTransition()
}

function setBookmarkStyle(next: BookmarkStyle) {
  bookmarkStyle.value = next
  localStorage.setItem('studiolo:bookmark-style', next)
}

function siteHostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

// 书签列表：优先星标置顶，其次按最近访问时间排序，默认上限 8 个
const quickBookmarks = computed(() => {
  const ranked = [...allSites.value].sort((a, b) => {
    if (a.favorite !== b.favorite) return a.favorite ? -1 : 1
    const aTime = a.lastVisitedAt ? new Date(a.lastVisitedAt).getTime() : 0
    const bTime = b.lastVisitedAt ? new Date(b.lastVisitedAt).getTime() : 0
    if (aTime !== bTime) return bTime - aTime
    return a.order - b.order
  })
  return ranked.slice(0, 8)
})

// 数据骨架屏：首次拉取且尚无账本/概览数据时展示，或手动刷新/切换维度时展示短过渡
const showSkeleton = computed(() => {
  if (refreshing.value) return true
  const coreBusy = (ledger.loading && !ledger.loaded) || (dataStore.overviewLoading && !dataStore.overview)
  return coreBusy
})

function previousDateKey(daysAgo: number): string {
  const copy = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysAgo)
  return localDateKey(copy.toISOString())
}

const current7dKeys = computed(() => Array.from({ length: 7 }, (_, i) => previousDateKey(6 - i)))
const usageDates = computed(() => range.value === '7d'
  ? current7dKeys.value
  : Array.from({ length: now.getDate() }, (_, index) => previousDateKey(now.getDate() - index - 1)))
const usageReport = ref<FleetUsageDay[] | null>(null)
const usageLabel = computed(() => {
  if (tokenUsageDemo) return '示例数据'
  if (!usageReport.value) return '本机收到的实测用量'
  return auth.mode === 'core' || auth.coreConnection?.connected ? 'Core 汇总' : '本机后端汇总'
})
let usageFetch: AbortController | undefined
let usageTimer: ReturnType<typeof setTimeout> | undefined

async function refreshTokenUsage() {
  usageFetch?.abort()
  if (tokenUsageDemo || fleet.usageOrigin === null) return
  const start = usageDates.value[0]
  const end = usageDates.value.at(-1)
  if (!start || !end) return
  const controller = new AbortController()
  usageFetch = controller
  try {
    const report = await fleet.loadTokenUsage(start, end, controller.signal)
    if (!controller.signal.aborted) usageReport.value = report
  } catch {
    // Local telemetry is still available when the Core is offline or predates this endpoint.
    if (!controller.signal.aborted) usageReport.value = null
  }
}

watch([usageDates, () => fleet.usageOrigin, () => auth.token], () => {
  usageReport.value = null
  void refreshTokenUsage()
}, { immediate: true })

watch([() => fleet.recordedTokenUsage, () => fleet.wsState], ([, state]) => {
  if (tokenUsageDemo || state !== 'online') return
  clearTimeout(usageTimer)
  usageTimer = setTimeout(() => { void refreshTokenUsage() }, 400)
})

const periodExpense = computed(() => {
  if (range.value === 'month') {
    if (ledger.summary?.month === monthKey) return Number(ledger.summary.expense ?? 0)
    return ledger.items
      .filter(tx => tx.type === 'expense' && localMonthKey(tx.occurredAt) === monthKey)
      .reduce((sum, tx) => sum + Number(tx.amount), 0)
  }
  const set = new Set(current7dKeys.value)
  return ledger.items
    .filter(tx => tx.type === 'expense' && set.has(localDateKey(tx.occurredAt)))
    .reduce((sum, tx) => sum + Number(tx.amount), 0)
})

const periodIncome = computed(() => {
  if (range.value === 'month') {
    if (ledger.summary?.month === monthKey) return Number(ledger.summary.income ?? 0)
    return ledger.items
      .filter(tx => tx.type === 'income' && localMonthKey(tx.occurredAt) === monthKey)
      .reduce((sum, tx) => sum + Number(tx.amount), 0)
  }
  const set = new Set(current7dKeys.value)
  return ledger.items
    .filter(tx => tx.type === 'income' && set.has(localDateKey(tx.occurredAt)))
    .reduce((sum, tx) => sum + Number(tx.amount), 0)
})

const periodBalance = computed(() => Math.round((periodIncome.value - periodExpense.value) * 100) / 100)
const balancePercent = computed(() => periodIncome.value > 0
  ? Math.min(100, Math.max(0, Math.round(periodBalance.value / periodIncome.value * 100)))
  : 0)
const balanceCaption = computed(() => {
  if (ledger.error) return '账本读取失败'
  if (periodBalance.value < 0) return '支出超过收入'
  if (periodIncome.value <= 0) return '暂无收入记录'
  return `剩余收入 ${balancePercent.value}%`
})

// 小卡 2：系统与任务（自动化启用数 + 在线设备数）
const enabledJobsCount = computed(() => automation.items.filter(item => item.enabled).length)
const failedJobsCount = computed(() => automation.items.filter(item => {
  if (!item.enabled) return false
  const last = automation.runtimeExecutions.find(run => run.workflowId === item.id)
  return last?.status === 'failed'
}).length)
const runningJobsCount = computed(() => automation.runtimeExecutions.filter(item => item.status === 'running').length)
const onlineDevicesCount = computed(() => devicesStore.devices.filter(device => device.online).length)
const totalDevicesCount = computed(() => devicesStore.devices.length)
const systemCombinedActive = computed(() => enabledJobsCount.value + onlineDevicesCount.value)

// 小卡 3：数据与记录
const totalRecords = computed(() => dataStore.overview?.totalRecords ?? 0)
const totalCollections = computed(() => dataStore.overview?.totalCollections ?? 0)
const activeRecords = computed(() => dataStore.overview?.active ?? 0)
const completedRecords = computed(() => dataStore.overview?.completed ?? 0)

// 工作台状态表盘根据同步队列和冲突显示就绪度。
const queued = computed(() => (props.syncStatus?.pending ?? 0) + (props.syncStatus?.inFlight ?? 0))
const gaugeState = computed(() => {
  const conflicts = props.syncStatus?.conflicts ?? 0
  // 无论在线同步中还是离线积压，只要存在待同步项就按队列压力扣减就绪度
  const healthPct =
    conflicts > 0
      ? 45
      : queued.value > 0
        ? Math.max(20, 100 - Math.min(queued.value, 20) * 4)
        : 100
  return {
    sub: props.syncStatus?.connected ? 'Core 同步状态' : '本机优先运行中',
    centerText: conflicts > 0 ? `${conflicts} 冲突` : queued.value > 0 ? `${queued.value} 待传` : '100%',
    caption: conflicts > 0 ? '点此前往冲突处理' : props.syncLabel,
    pct: healthPct,
  }
})

let isCounting = false

// Count-up 数字递增与表盘弧线生长动画
function runCountUp() {
  if (countFrame) cancelAnimationFrame(countFrame)

  const reduced = document.documentElement.dataset.motion === 'reduced'
  if (reduced) {
    isCounting = false
    animBalance.value = periodBalance.value
    balanceProgress.value = balancePercent.value
    animActive.value = systemCombinedActive.value
    animRecords.value = totalRecords.value
    gaugeProgress.value = gaugeState.value.pct
    return
  }

  isCounting = true
  animBalance.value = 0
  balanceProgress.value = 0
  animActive.value = 0
  animRecords.value = 0
  gaugeProgress.value = 0

  const start = performance.now()
  const duration = 520
  const tick = (nowTs: number) => {
    const progress = Math.min(1, (nowTs - start) / duration)
    const eased = 1 - Math.pow(1 - progress, 3)
    // 每帧读取最新响应式目标值，确保异步完成的同步状态/设备请求平滑汇入终值
    const targetBalance = periodBalance.value
    const targetBalanceProgress = balancePercent.value
    const targetSys = systemCombinedActive.value
    const targetRec = totalRecords.value
    const targetGauge = gaugeState.value.pct
    animBalance.value = targetBalance * eased
    balanceProgress.value = targetBalanceProgress * eased
    animActive.value = Math.round(targetSys * eased)
    animRecords.value = Math.round(targetRec * eased)
    gaugeProgress.value = targetGauge * eased
    if (progress < 1) {
      countFrame = requestAnimationFrame(tick)
    } else {
      isCounting = false
      animBalance.value = targetBalance
      balanceProgress.value = targetBalanceProgress
      animActive.value = targetSys
      animRecords.value = targetRec
      gaugeProgress.value = targetGauge
    }
  }
  countFrame = requestAnimationFrame(tick)
}

function triggerRevealTransition() {
  if (refreshTimer) clearTimeout(refreshTimer)
  const reduced = document.documentElement.dataset.motion === 'reduced'
  if (reduced) {
    revealSeq.value++
    runCountUp()
    return
  }
  refreshing.value = true
  refreshTimer = setTimeout(() => {
    refreshing.value = false
    revealSeq.value++
    runCountUp()
  }, 360)
}

async function refreshAll() {
  if (!auth.token) return
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshing.value = true
  try {
    await Promise.allSettled([
      ledger.load(auth.token, true),
      automation.load(auth.token, true),
      dataStore.loadOverview(auth.token, true),
      devicesStore.load(auth.token, true),
      refreshTokenUsage(),
      websiteService.list(auth.token, { sort: 'recent' }).then(items => { allSites.value = items }),
    ])
  } finally {
    refreshing.value = false
    revealSeq.value++
    runCountUp()
  }
}

watch(
  [showSkeleton, () => ledger.loaded, () => dataStore.overview?.totalRecords],
  ([skel, ledgerLoaded]) => {
    if (!skel && ledgerLoaded && revealSeq.value === 0) {
      revealSeq.value++
      runCountUp()
    }
  },
  { immediate: true },
)

// 后台同步状态或快速录入异步到达时，实时同步最新指标与表盘弧度
watch(
  [periodBalance, balancePercent, systemCombinedActive, totalRecords, () => gaugeState.value.pct],
  ([balance, remaining, sys, rec, pct]) => {
    if (revealSeq.value > 0 && !showSkeleton.value && !isCounting) {
      animBalance.value = balance
      balanceProgress.value = remaining
      animActive.value = sys
      animRecords.value = rec
      gaugeProgress.value = pct
    }
  },
)

// 移动端与旧兼容层所需计算属性
const transactions = computed(() => [...ledger.items].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt)))
const jobs = computed(() => automation.items.slice(0, 3).map(item => {
  const last = automation.runtimeExecutions.find(run => run.workflowId === item.id)
  const status: 'paused' | 'running' | 'fail' | 'ok' | 'unknown' =
    !item.enabled ? 'paused' : last?.status === 'running' ? 'running' : last?.status === 'failed' ? 'fail' : last?.status === 'succeeded' || last?.status === 'success' ? 'ok' : 'unknown'
  return { ...item, status }
}))
const running = computed(() => automation.runtimeExecutions.filter(item => item.status === 'running'))
const finishedToday = computed(() => automation.runtimeExecutions.filter(item => item.finishedAt && new Date(item.finishedAt).toDateString() === now.toDateString()).length)

// 快捷输入解析（记账 / 收藏网站 / 问 Agent）
const capture = ref('')
const captureBusy = ref(false)
const intent = computed(() => {
  const text = capture.value.trim()
  if (!text) return null
  if (/^(https?:\/\/)?[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/i.test(text)) {
    const host = text.replace(/^https?:\/\//i, '').split('/')[0]
    return { type: 'website', icon: 'globe', label: `收藏网站 · ${host}` } as const
  }
  const match = text.match(/^(.+?)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(元|块)?$/)
  if (match) {
    return { type: 'ledger', icon: 'ledger', label: `记账 · ${match[1]!.trim()} · ¥${Number(match[2]).toFixed(2)}`, title: match[1]!.trim(), amount: match[2]! } as const
  }
  return { type: 'chat', icon: 'chat', label: '发给 Agent' } as const
})

function matchCategoryId(title: string) {
  const expenses = ledger.categories.filter(item => item.type === 'expense')
  const keyword = /饭|餐|面|咖啡|奶茶|菜|早|晚|午/.test(title) ? '餐饮' : /地铁|打车|油|公交|停车|车/.test(title) ? '交通' : /会员|订阅/.test(title) ? '订阅' : /买|购|衣|鞋/.test(title) ? '购物' : ''
  return (keyword && expenses.find(item => item.name.includes(keyword))?.id) || expenses[0]?.id || null
}

async function visitBookmark(site: Website) {
  if (!auth.token) return
  try {
    await websites.visit(auth.token, site.id)
    const nowIso = new Date().toISOString()
    allSites.value = allSites.value.map(item => item.id === site.id ? { ...item, lastVisitedAt: nowIso } : item)
  } catch { /* 非阻塞 */ }
}

function showBookmarkIcon(site: Website) {
  return Boolean(site.icon && /^https?:\/\//i.test(site.icon) && failedBookmarkIcons.value[site.id] !== site.icon)
}

async function submitCapture() {
  if (!intent.value || captureBusy.value) return
  const current = intent.value
  if (current.type === 'chat') {
    capture.value = ''
    emit('askAgent')
    return
  }
  if (!auth.token) return
  captureBusy.value = true
  try {
    if (current.type === 'ledger') {
      const before = new Set(ledger.items.map(item => item.id))
      await ledger.createTransaction(auth.token, {
        type: 'expense',
        category_id: matchCategoryId(current.title),
        amount: current.amount,
        description: current.title,
        occurred_at: new Date().toISOString(),
        merchant: '',
        note: '',
      })
      recentTxIds.value = ledger.items.filter(item => !before.has(item.id)).map(item => item.id)
      capture.value = ''
      revealSeq.value++
      runCountUp()
      emit('action', `已记一笔：${current.title} ¥${Number(current.amount).toFixed(2)}`)
    } else {
      const raw = capture.value.trim()
      const link = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`)
      const existing = await websiteService.list(auth.token)
      await websites.create(auth.token, {
        name: link.hostname.replace(/^www\./, ''),
        url: link.href,
        order: Math.max(-1, ...existing.map(item => item.order)) + 1,
        favorite: true,
      })
      allSites.value = await websiteService.list(auth.token, { sort: 'recent' })
      capture.value = ''
      emit('action', `已收藏 ${link.hostname}`)
    }
  } catch {
    emit('create', current.type, capture.value.trim())
  } finally {
    captureBusy.value = false
  }
}

onMounted(async () => {
  if (!auth.token) return
  await Promise.allSettled([
    ledger.load(auth.token),
    automation.load(auth.token),
    dataStore.loadOverview(auth.token),
    devicesStore.load(auth.token),
    websiteService.list(auth.token, { sort: 'recent' }).then(items => { allSites.value = items }),
  ])
  if (revealSeq.value === 0) {
    revealSeq.value++
    runCountUp()
  }
})

onUnmounted(() => {
  usageFetch?.abort()
  clearTimeout(usageTimer)
  if (refreshTimer) clearTimeout(refreshTimer)
  if (countFrame) cancelAnimationFrame(countFrame)
})
</script>

<template>
  <div v-if="mobile" class="mpage mobile-today">
    <div class="mhead-minimal">
      <div class="home-seg" role="group" aria-label="统计周期">
        <button type="button" :aria-pressed="range === '7d'" @click="setRange('7d')">近 7 天</button>
        <button type="button" :aria-pressed="range === 'month'" @click="setRange('month')">本月</button>
      </div>
      <button class="mhead-settings" type="button" aria-label="设置" title="设置" @click="emit('navigate', 'Settings')">
        <Settings :size="18" :stroke-width="1.9" />
      </button>
    </div>
    <section class="mcard mat mobile-balance" aria-labelledby="m-balance-title">
      <div class="mcard-h">
        <span class="deliv-icon"><Wallet :size="15" :stroke-width="1.9" /></span>
        <div class="deliv-head-copy">
          <strong id="m-balance-title">余额</strong>
          <span>{{ range === '7d' ? '近 7 天收支结余' : '本月收支结余' }}</span>
        </div>
        <span class="spacer" />
        <button class="btn btn-sm btn-subtle" type="button" @click="emit('navigate', 'Ledger')">账本 <OpusIcon name="chevR" /></button>
      </div>
      <div v-if="showSkeleton" class="sk sk-gauge" aria-hidden="true"></div>
      <DashboardGauge v-else :progress="balanceProgress" :value="ledger.error ? '—' : money.format(animBalance)" :caption="balanceCaption" compact />
    </section>
    <section class="mcard mat mobile-token" aria-labelledby="m-token-usage-title">
      <div class="mcard-h">
        <span class="deliv-icon"><ChartNoAxesCombined :size="15" :stroke-width="1.9" /></span>
        <div class="deliv-head-copy">
          <strong id="m-token-usage-title">Token 用量</strong>
          <span>{{ range === '7d' ? '最近 7 日' : '本月' }} · {{ usageLabel }}</span>
        </div>
      </div>
      <div v-if="showSkeleton" class="sk-bars" aria-hidden="true">
        <span v-for="height in [42, 68, 86, 36, 58, 92, 64]" :key="height" class="sk sk-bar" :style="{ height: height + '%' }"></span>
      </div>
      <TokenUsageChart v-else :key="revealSeq" :dates="usageDates" :records="tokenRecords" :report="usageReport" />
    </section>
    <section class="mcard mat mobile-quota" aria-labelledby="m-subscription-quota-title">
      <div class="mcard-h">
        <span class="deliv-icon"><Gauge :size="15" :stroke-width="1.9" /></span>
        <div class="deliv-head-copy"><strong id="m-subscription-quota-title">订阅额度</strong></div>
      </div>
      <SubscriptionQuotaPanel @sign-in="emit('navigate', 'Chat')" @action="emit('action', $event)" />
    </section>
    <section class="mcard mat">
      <div class="mcard-h"><OpusIcon name="tasks" /> 任务<span class="spacer"></span><button class="btn btn-sm btn-subtle" type="button" @click="emit('navigate', 'Automation')">全部 <OpusIcon name="chevR" /></button></div>
      <div class="task-mini">
        <button type="button" @click="emit('navigate', 'Automation')"><b style="color:var(--accent)">{{ running.length }}</b><span>运行中</span></button>
        <button type="button" @click="emit('navigate', 'Automation')"><b style="color:var(--danger)">{{ jobs.filter(item => item.status === 'fail').length }}</b><span>需要关注</span></button>
        <button type="button" @click="emit('navigate', 'Automation')"><b>{{ finishedToday }}</b><span>今天已完成</span></button>
      </div>
    </section>
    <div class="sec-t">最近记录<span class="spacer"></span></div>
    <div class="mlist mat-solid">
      <div v-for="tx in transactions.slice(0, 4)" :key="tx.id" class="mrow" :class="{ enter: recentTxIds.includes(tx.id) }"><span class="tile-icon"><OpusIcon name="receipt" /></span>
        <span class="grow"><div class="title">{{ tx.description }}</div><div class="sub">{{ new Date(tx.occurredAt).toLocaleString('zh-CN') }}</div></span>
        <span class="end"><span class="num" style="font-weight:650" :class="{ 'amt-pos': tx.type === 'income' }">{{ money.format(Number(tx.amount) * (tx.type === 'income' ? 1 : -1)) }}</span></span>
      </div>
      <div v-if="!transactions.length" class="mrow faint">{{ ledger.loading ? '正在读取账本…' : ledger.error || '暂无记录' }}</div>
    </div>
  </div>

  <!-- 桌面端重构：居中等比画布 + 极简顶部 + 可选形态书签 + Delivry 风格 4 小卡 + 2 大卡 -->
  <div v-else class="home-desk-stage">
  <div class="home-desk">
    <!-- 顶部极简操作栏（无臃肿日期/问候大标题） -->
    <div class="home-top">
      <label class="home-capture">
        <Sparkles :size="15" :stroke-width="2" class="home-capture__ico" />
        <input
          v-model="capture"
          placeholder="记一笔「午饭 32」、粘贴网址收藏，或输入 / 执行…"
          autocomplete="off"
          :disabled="captureBusy"
          @keydown.enter.prevent="submitCapture"
        />
        <span v-if="intent" class="intent">{{ intent.label }}</span>
        <span class="kbd">Enter</span>
      </label>

      <div class="home-controls">
        <div class="home-seg" role="group" aria-label="统计周期">
          <button type="button" :aria-pressed="range === '7d'" @click="setRange('7d')">近 7 天</button>
          <button type="button" :aria-pressed="range === 'month'" @click="setRange('month')">本月</button>
        </div>
        <button class="home-refresh" type="button" title="刷新概览数据" aria-label="刷新概览数据" :disabled="refreshing" @click="refreshAll">
          <RefreshCw :size="14" :stroke-width="2" :class="{ 'is-spinning': refreshing }" />
        </button>
      </div>
    </div>

    <!-- 顶部常用书签条（支持圆角胶囊 / 书签小方牌 / 纯图标切换并持久化） -->
    <div class="bookmark-bar" aria-label="常用书签">
      <div class="bookmark-list" :class="`is-${bookmarkStyle}`">
        <ExternalLink
          v-for="site in quickBookmarks"
          :key="site.id"
          :href="site.url"
          class="bm-item"
          :title="`${site.name} · ${siteHostname(site.url)}`"
          @activate="visitBookmark(site)"
          @action="emit('action', $event)"
        >
          <span class="bm-fav" :class="{ 'bm-fav--img': showBookmarkIcon(site) }">
            <img v-if="showBookmarkIcon(site)" class="opus-favicon" :src="site.icon ?? undefined" alt="" @error="failedBookmarkIcons[site.id] = site.icon ?? null" />
            <template v-else>{{ site.name[0]?.toUpperCase() }}</template>
          </span>
          <span v-if="bookmarkStyle === 'pill'" class="bm-name">{{ site.name }}</span>
          <span v-else-if="bookmarkStyle === 'card'" class="bm-card-copy">
            <strong>{{ site.name }}</strong>
            <small>{{ siteHostname(site.url) }}</small>
          </span>
        </ExternalLink>

        <button class="bm-add" type="button" title="收藏新网站" aria-label="收藏新网站" @click="emit('create', 'website')">
          <Plus :size="13" :stroke-width="2.2" />
          <span v-if="bookmarkStyle !== 'icon'">收藏</span>
        </button>
      </div>

      <div class="bookmark-tools">
        <div class="bm-style-switch" role="group" aria-label="书签显示形态">
          <button type="button" title="圆角胶囊" aria-label="圆角胶囊" :aria-pressed="bookmarkStyle === 'pill'" @click="setBookmarkStyle('pill')">
            <Tag :size="13" :stroke-width="2" />
          </button>
          <button type="button" title="书签小方牌" aria-label="书签小方牌" :aria-pressed="bookmarkStyle === 'card'" @click="setBookmarkStyle('card')">
            <Bookmark :size="13" :stroke-width="2" />
          </button>
          <button type="button" title="纯图标" aria-label="纯图标" :aria-pressed="bookmarkStyle === 'icon'" @click="setBookmarkStyle('icon')">
            <LayoutGrid :size="13" :stroke-width="2" />
          </button>
        </div>
        <button class="bm-all" type="button" @click="emit('navigate', 'Websites')">全部</button>
      </div>
    </div>

    <!-- 第一行：4 个等宽 KPI / Gauge 小卡 -->
    <section class="kpi-grid" aria-label="核心指标">
      <template v-if="showSkeleton">
        <div v-for="idx in 4" :key="idx" class="deliv-card is-skeleton" aria-hidden="true">
          <div class="deliv-head">
            <span class="sk sk-icon"></span>
            <div class="deliv-head-copy"><span class="sk sk-title"></span><span class="sk sk-sub"></span></div>
          </div>
          <template v-if="idx === 1 || idx === 4">
            <div class="sk sk-gauge"></div>
          </template>
          <template v-else>
            <div class="sk sk-num"></div>
            <div class="sk sk-meta"></div>
          </template>
        </div>
      </template>

      <template v-else>
        <button type="button" class="deliv-card is-clickable" @click="emit('navigate', 'Ledger')">
          <div class="deliv-head">
            <span class="deliv-icon"><Wallet :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy">
              <strong>余额</strong>
              <span>{{ range === '7d' ? '近 7 天收支结余' : '本月收支结余' }}</span>
            </div>
          </div>
          <DashboardGauge :progress="balanceProgress" :value="ledger.error ? '—' : money.format(animBalance)" :caption="balanceCaption" compact />
        </button>

        <!-- 小卡 2：系统与任务（自动化 + 设备在线） -->
        <button type="button" class="deliv-card is-clickable" @click="emit('navigate', 'Automation')">
          <div class="deliv-head">
            <span class="deliv-icon"><Server :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy">
              <strong>系统与任务</strong>
              <span>自动化规则与在线设备</span>
            </div>
          </div>
          <div class="deliv-kpi-body">
            <div class="deliv-split num">
              <span><b>{{ animActive }}</b><small>活跃项</small></span>
              <i></i>
              <span><b>{{ onlineDevicesCount }}/{{ totalDevicesCount }}</b><small>在线设备</small></span>
            </div>
            <div class="deliv-delta" :class="failedJobsCount > 0 ? 'is-bad' : 'is-good'">
              <template v-if="failedJobsCount > 0">{{ failedJobsCount }} 个任务异常需处理</template>
              <template v-else-if="runningJobsCount > 0">{{ runningJobsCount }} 个任务正在运行</template>
              <template v-else>启用 {{ enabledJobsCount }} 项 · 系统运行正常</template>
            </div>
          </div>
        </button>

        <!-- 小卡 3：数据与记录 -->
        <button type="button" class="deliv-card is-clickable" @click="emit('navigate', 'Data')">
          <div class="deliv-head">
            <span class="deliv-icon"><Database :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy">
              <strong>数据资产</strong>
              <span>结构化集合与记录</span>
            </div>
          </div>
          <div class="deliv-kpi-body">
            <div class="deliv-value num">{{ animRecords }}</div>
            <div class="deliv-delta">{{ totalCollections }} 个集合 · 进行中 {{ activeRecords }} / 已完成 {{ completedRecords }}</div>
          </div>
        </button>

        <button type="button" class="deliv-card is-clickable" @click="emit('sync')">
          <div class="deliv-head">
            <span class="deliv-icon"><Activity :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy">
              <strong>工作台状态</strong>
              <span>{{ gaugeState.sub }}</span>
            </div>
          </div>
          <DashboardGauge :progress="gaugeProgress" :value="gaugeState.centerText" :caption="gaugeState.caption" />
        </button>
      </template>
    </section>

    <section class="wide-grid" aria-label="用量与订阅额度">
      <template v-if="showSkeleton">
        <div class="deliv-card deliv-wide is-skeleton" aria-hidden="true">
          <div class="deliv-head">
            <span class="sk sk-icon"></span>
            <div class="deliv-head-copy"><span class="sk sk-title"></span><span class="sk sk-sub"></span></div>
          </div>
          <div class="sk-bars">
            <span v-for="h in [42, 68, 86, 36, 58, 92, 64]" :key="h" class="sk sk-bar" :style="{ height: h + '%' }"></span>
          </div>
        </div>
        <div class="deliv-card deliv-wide is-skeleton" aria-hidden="true">
          <div class="deliv-head">
            <span class="sk sk-icon"></span>
            <div class="deliv-head-copy"><span class="sk sk-title"></span><span class="sk sk-sub"></span></div>
          </div>
          <div class="sk-rows">
            <span v-for="n in 3" :key="n" class="sk sk-row"></span>
          </div>
        </div>
      </template>

      <template v-else>
        <section class="deliv-card deliv-wide" aria-labelledby="h-chart">
          <div class="deliv-wide-top">
            <div class="deliv-head">
              <span class="deliv-icon"><ChartNoAxesCombined :size="15" :stroke-width="1.9" /></span>
              <div class="deliv-head-copy">
                <strong id="h-chart">Token 用量</strong>
                <span>{{ range === '7d' ? '最近 7 日' : '本月' }} · {{ usageLabel }}</span>
              </div>
            </div>
          </div>
          <TokenUsageChart :key="revealSeq" :dates="usageDates" :records="tokenRecords" :report="usageReport" />
        </section>

        <section class="deliv-card deliv-wide quota-card" aria-labelledby="h-subscription-quota">
          <div class="deliv-head">
            <span class="deliv-icon"><Gauge :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy"><strong id="h-subscription-quota">订阅额度</strong></div>
          </div>
          <SubscriptionQuotaPanel @sign-in="emit('navigate', 'Chat')" @action="emit('action', $event)" />
        </section>
      </template>
    </section>
  </div>
  </div>
</template>

<style scoped>
/* 桌面端等比放大舞台：保持 4 小卡与 2 大卡布局比例，随窗口尺寸自适应铺满 */
.home-desk-stage {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  min-height: 100%;
  width: 100%;
  padding: clamp(16px, 2.2vh, 34px) clamp(22px, 2.5vw, 48px);
  box-sizing: border-box;
}
.home-desk {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto auto minmax(156px, 1fr) minmax(308px, 2.15fr);
  width: 100%;
  gap: clamp(12px, 1.5vh, 22px);
}

/* 顶部快捷指令与时间周期 */
.home-top {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.home-capture {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  height: 38px;
  padding: 0 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-strong);
  background: var(--solid);
  transition: border-color var(--dur-1), box-shadow var(--dur-1);
}
.home-capture:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.home-capture__ico { color: var(--text-2); flex: none; }
.home-capture input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  outline: none;
  box-shadow: none;
  padding: 0;
  font-size: 13.5px;
  color: var(--text);
}
.home-capture input::placeholder { color: var(--text-3); }
.home-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.home-seg {
  display: inline-flex;
  align-items: center;
  height: 38px;
  padding: 3px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line);
  background: var(--surface-2);
  gap: 2px;
}
.home-seg button {
  height: 30px;
  padding: 0 11px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 550;
  color: var(--text-2);
  transition: background-color var(--dur-1), color var(--dur-1), box-shadow var(--dur-1);
}
.home-seg button[aria-pressed="true"] {
  background: var(--solid);
  color: var(--text);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .06), 0 0 0 1px var(--line);
}
.home-refresh {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line);
  background: var(--solid);
  color: var(--text-2);
  transition: background-color var(--dur-1), color var(--dur-1);
}
.home-refresh:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.is-spinning { animation: spin 0.8s linear infinite; }

/* 顶部常用书签条：3 种形态（默认圆角胶囊） */
.bookmark-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  min-width: 0;
}
.bookmark-list {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 2px 0;
}
.bookmark-list::-webkit-scrollbar { display: none; }
.bm-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: none;
  border: 1px solid var(--line-strong);
  background: var(--solid);
  color: var(--text);
  text-decoration: none;
  transition: background-color var(--dur-1), border-color var(--dur-1), translate var(--dur-1);
}
.bm-item:hover {
  background: var(--surface-2);
  translate: 0 -1px;
}
.is-pill .bm-item {
  height: 30px;
  padding: 0 11px 0 8px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 500;
}
.is-card .bm-item {
  height: 40px;
  padding: 0 11px 0 9px;
  border-radius: var(--r-sm);
}
.is-icon .bm-item {
  width: 34px;
  height: 34px;
  justify-content: center;
  padding: 0;
  border-radius: var(--r-sm);
}
.bm-fav {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: var(--surface-3);
  color: var(--text);
  font-size: 11px;
  font-weight: 700;
  flex: none;
  overflow: hidden;
}
.bm-fav--img {
  background: #ffffff;
  padding: 2px;
  box-shadow: inset 0 0 0 1px var(--line);
}
.is-pill .bm-fav { border-radius: 50%; }
.is-icon .bm-fav { width: 20px; height: 20px; }
.bm-name { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bm-card-copy { display: grid; line-height: 1.2; text-align: left; }
.bm-card-copy strong { font-size: 12px; font-weight: 600; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bm-card-copy small { font-size: 10.5px; color: var(--text-3); max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bm-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px dashed var(--line-strong);
  color: var(--text-3);
  font-size: 12px;
  flex: none;
}
.is-card .bm-add { height: 40px; border-radius: var(--r-sm); }
.is-icon .bm-add { width: 34px; height: 34px; padding: 0; justify-content: center; border-radius: var(--r-sm); }
.bm-add:hover { color: var(--text); background: var(--surface-2); }

.bookmark-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}
.bm-style-switch {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 2px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface-2);
}
.bm-style-switch button {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  color: var(--text-3);
}
.bm-style-switch button[aria-pressed="true"] {
  background: var(--solid);
  color: var(--text);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .06);
}
.bm-all {
  height: 30px;
  padding: 0 10px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--solid);
  font-size: 12px;
  color: var(--text-2);
}
.bm-all:hover { color: var(--text); background: var(--surface-2); }

/* 4 个小卡 + 2 个大卡对称网格（等比缩放 + 上下中缝对齐） */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: clamp(12px, 1.3cqi, 18px);
  min-width: 0;
  min-height: 0;
}
.wide-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: clamp(12px, 1.3cqi, 18px);
  min-width: 0;
  min-height: 0;
}

.deliv-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: clamp(12px, 1.4vh, 18px);
  min-width: 0;
  min-height: 0;
  padding: clamp(16px, 1.6cqi, 24px);
  border-radius: var(--r-md);
  border: 1px solid var(--line-strong);
  background: var(--solid);
  text-align: left;
  transition: border-color var(--dur-1), box-shadow var(--dur-1), translate var(--dur-1);
}
.deliv-card.is-clickable:hover {
  border-color: color-mix(in srgb, var(--accent) 30%, var(--line-strong));
  box-shadow: var(--shadow-2);
  translate: 0 -1px;
}
[data-motion="reduced"] .deliv-card.is-clickable:hover { translate: none; }

.deliv-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.deliv-icon {
  display: grid;
  place-items: center;
  width: clamp(30px, 2.2cqi, 40px);
  height: clamp(30px, 2.2cqi, 40px);
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text);
  flex: none;
}
.deliv-head-copy { display: grid; gap: 2px; min-width: 0; }
.deliv-head-copy strong { font-size: clamp(13px, 1cqi, 17px); font-weight: 650; color: var(--text); line-height: 1.3; }
.deliv-head-copy span { font-size: clamp(11.5px, 0.85cqi, 14px); color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.deliv-kpi-body {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 5px;
  margin: auto 0;
  padding: 4px 0 2px;
}
.deliv-value {
  font-size: clamp(24px, 2.2cqi, 44px);
  font-weight: 750;
  letter-spacing: -.03em;
  line-height: 1.15;
  color: var(--text);
}
.deliv-split {
  display: flex;
  align-items: center;
  gap: clamp(14px, 1.6cqi, 28px);
}
.deliv-split span {
  display: grid;
  gap: 2px;
}
.deliv-split b { font-size: clamp(20px, 1.9cqi, 36px); font-weight: 750; letter-spacing: -.02em; line-height: 1.15; color: var(--text); }
.deliv-split small { font-size: clamp(11px, 0.85cqi, 13.5px); color: var(--text-3); }
.deliv-split i { width: 1px; height: clamp(26px, 2cqi, 36px); background: var(--line-strong); }

.deliv-delta {
  font-size: clamp(11.5px, 0.85cqi, 14px);
  font-weight: 550;
  color: var(--text-3);
}
.deliv-delta.is-good { color: var(--ok); }
.deliv-delta.is-bad { color: var(--danger); }

/* 第二行宽卡与图表 */
.deliv-wide { min-height: 308px; }
.deliv-wide-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.quota-card { gap: 5px; }

/* 骨架屏 Shimmer 动效 */
.sk {
  display: block;
  border-radius: 6px;
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: skShimmer 1.3s ease-in-out infinite;
}
[data-motion="reduced"] .sk { animation: none; }
@keyframes skShimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.sk-icon { width: 30px; height: 30px; border-radius: 7px; flex: none; }
.sk-title { width: 76px; height: 12px; }
.sk-sub { width: 108px; height: 10px; margin-top: 4px; }
.sk-num { width: 92px; height: 28px; margin: 10px auto 0; }
.sk-meta { width: 110px; height: 11px; margin: 4px auto 0; }
.sk-gauge { width: 124px; height: 64px; margin: 8px auto 0; border-radius: 999px 999px 0 0; }
.sk-bars {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex: 1;
  min-height: 200px;
  padding: 16px 8px 8px;
}
.sk-bar { flex: 1; border-radius: 4px 4px 0 0; }
.sk-rows { display: grid; gap: 12px; padding-top: 8px; }
.sk-row { height: 36px; width: 100%; }

@container (max-width: 820px) {
  .home-desk { grid-template-rows: auto; min-height: 0; }
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi-grid .deliv-card { min-height: 164px; }
  .wide-grid { grid-template-columns: minmax(0, 1fr); }
  .deliv-wide { height: auto; min-height: 312px; }
}
@container (max-width: 560px) {
  .home-top { flex-wrap: wrap; }
  .home-controls { margin-left: auto; }
}

.mhead-minimal {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0 10px;
}
.mhead-settings {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  transition: background-color var(--dur-1), color var(--dur-1);
}
.mhead-settings:hover { color: var(--text); background: var(--surface-3); }
.mobile-token { min-height: 294px; }
.mobile-today .deliv-icon { width: 30px; height: 30px; }
.mobile-today .mobile-quota .mcard-h { margin-bottom: 2px; }
.mobile-balance .sk-gauge { margin-bottom: 16px; }
</style>
