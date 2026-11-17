<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity,
  Bookmark,
  CheckCircle2,
  Database,
  LayoutGrid,
  LayoutList,
  Plus,
  RefreshCw,
  Server,
  Settings,
  Sparkles,
  Tag,
  Wallet,
} from 'lucide-vue-next'
import ExternalLink from '../components/ui/ExternalLink.vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import type { SyncStatus } from '../api/sync'
import { useAuthStore } from '../stores/auth'
import { useLedgerStore } from '../stores/ledger'
import { useAutomationStore } from '../stores/automation'
import { useWebsitesStore } from '../stores/websites'
import { useDataStore } from '../stores/data'
import { useDevicesStore } from '../stores/devices'
import { websiteService } from '../services/websites'
import { localDateKey, localMonthKey } from '../services/localTime'
import type { Website } from '../types/website'

type RangeMode = '7d' | 'month'
type BookmarkStyle = 'pill' | 'card' | 'icon'
type ActivityFilter = 'all' | 'ledger' | 'automation' | 'data'

interface ActivityEntry {
  id: string
  kind: 'ledger' | 'automation' | 'data' | 'website'
  title: string
  meta: string
  badge: string
  tone: 'default' | 'ok' | 'danger' | 'warn'
  timestamp: string
  targetPage: string
}

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
  add: [kind: string]
  askAgent: []
}>()

const auth = useAuthStore()
const ledger = useLedgerStore()
const automation = useAutomationStore()
const websites = useWebsitesStore()
const dataStore = useDataStore()
const devicesStore = useDevicesStore()

const allSites = ref<Website[]>([])
const recentTxIds = ref<string[]>([])
const range = ref<RangeMode>(localStorage.getItem('studiolo:home-range') === 'month' ? 'month' : '7d')
const storedBookmarkStyle = localStorage.getItem('studiolo:bookmark-style')
const bookmarkStyle = ref<BookmarkStyle>(
  storedBookmarkStyle === 'card' || storedBookmarkStyle === 'icon' || storedBookmarkStyle === 'pill'
    ? storedBookmarkStyle
    : 'pill',
)
const activityFilter = ref<ActivityFilter>('all')

// 两段式数据加载动效控制：骨架屏 -> 数据入场递增 / 生长动画
const refreshing = ref(false)
const revealSeq = ref(0)
const gaugeProgress = ref(0)
const animExpense = ref(0)
const animActive = ref(0)
const animRecords = ref(0)
const hoveredBarIndex = ref<number | null>(null)
let refreshTimer: ReturnType<typeof setTimeout> | undefined
let countFrame: number | undefined

const now = new Date()
const month = (now.getMonth() + 1) + ' 月'
const monthKey = localMonthKey(now.toISOString())
const todayKey = localDateKey(now.toISOString())

const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' })
const moneyCompact = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 })

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
const prev7dKeys = computed(() => new Set(Array.from({ length: 7 }, (_, i) => previousDateKey(13 - i))))

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

const periodTxCount = computed(() => {
  if (range.value === 'month') {
    return ledger.items.filter(tx => localMonthKey(tx.occurredAt) === monthKey).length
  }
  const set = new Set(current7dKeys.value)
  return ledger.items.filter(tx => set.has(localDateKey(tx.occurredAt))).length
})

const expenseTrendDelta = computed(() => {
  if (range.value === 'month') {
    const trend = ledger.summary?.monthlyTrend ?? []
    const prevDate = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    const prevKey = localMonthKey(prevDate.toISOString())
    const prevValue = Number(trend.find(item => item.month === prevKey)?.expense ?? 0)
    if (prevValue <= 0) return null
    return Math.round(((periodExpense.value - prevValue) / prevValue) * 100)
  }
  const prevValue = ledger.items
    .filter(tx => tx.type === 'expense' && prev7dKeys.value.has(localDateKey(tx.occurredAt)))
    .reduce((sum, tx) => sum + Number(tx.amount), 0)
  if (prevValue <= 0) return null
  return Math.round(((periodExpense.value - prevValue) / prevValue) * 100)
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

// 小卡 4：半圆弧表盘（优先收支结余比例；未录收入时智能展示同步与待处理就绪度）
const queued = computed(() => (props.syncStatus?.pending ?? 0) + (props.syncStatus?.inFlight ?? 0))
const gaugeState = computed(() => {
  if (periodIncome.value > 0) {
    const ratio = Math.min(100, Math.round((periodExpense.value / periodIncome.value) * 100))
    const balance = periodIncome.value - periodExpense.value
    return {
      title: '收支占比',
      sub: range.value === '7d' ? '近 7 天支出占收入' : '本月支出占收入',
      centerText: moneyCompact.format(balance),
      caption: `结余 · 已用 ${ratio}%`,
      pct: ratio,
      target: 'Ledger' as const,
    }
  }
  const conflicts = props.syncStatus?.conflicts ?? 0
  // 无论在线同步中还是离线积压，只要存在待同步项就按队列压力扣减就绪度
  const healthPct =
    conflicts > 0
      ? 45
      : queued.value > 0
        ? Math.max(20, 100 - Math.min(queued.value, 20) * 4)
        : 100
  return {
    title: '工作台状态',
    sub: props.syncStatus?.connected ? 'Core 同步状态' : '本机优先运行中',
    centerText: conflicts > 0 ? `${conflicts} 冲突` : queued.value > 0 ? `${queued.value} 待传` : '100%',
    caption: conflicts > 0 ? '点此前往冲突处理' : props.syncLabel,
    pct: healthPct,
    target: 'Sync' as const,
  }
})

// 左下大卡：Delivry 同款双色对比柱状图（深黑 = 支出，冷灰 = 收入）
interface ChartColumn {
  label: string
  fullLabel: string
  expense: number
  income: number
}

const chartColumns = computed<ChartColumn[]>(() => {
  if (range.value === '7d') {
    return current7dKeys.value.map(key => {
      let exp = 0
      let inc = 0
      for (const tx of ledger.items) {
        if (localDateKey(tx.occurredAt) !== key) continue
        if (tx.type === 'expense') exp += Number(tx.amount)
        else inc += Number(tx.amount)
      }
      const [, mm, dd] = key.split('-')
      return {
        label: key === todayKey ? '今天' : `${Number(mm)}/${Number(dd)}`,
        fullLabel: key,
        expense: exp,
        income: inc,
      }
    })
  }
  // 本月按周（W1..W5）分段统计收支
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  const weeksCount = Math.ceil(daysInMonth / 7)
  const buckets = Array.from({ length: weeksCount }, (_, idx) => ({
    label: `第${idx + 1}周`,
    fullLabel: `${month}第 ${idx * 7 + 1}-${Math.min((idx + 1) * 7, daysInMonth)} 日`,
    expense: 0,
    income: 0,
  }))
  for (const tx of ledger.items) {
    if (localMonthKey(tx.occurredAt) !== monthKey) continue
    const dayNum = Number(localDateKey(tx.occurredAt).slice(8, 10)) || 1
    const bucketIndex = Math.min(weeksCount - 1, Math.floor((dayNum - 1) / 7))
    const target = buckets[bucketIndex]
    if (!target) continue
    if (tx.type === 'expense') target.expense += Number(tx.amount)
    else target.income += Number(tx.amount)
  }
  return buckets
})

const maxColumnTotal = computed(() => {
  const max = Math.max(...chartColumns.value.map(col => col.expense + col.income), 0)
  return max > 0 ? max : 100
})

const yTicks = computed(() => {
  const max = maxColumnTotal.value
  return [max, Math.round(max * 0.66), Math.round(max * 0.33), 0]
})

function colHeightPercent(value: number) {
  if (value <= 0) return 0
  return Math.max(5, Math.round((value / maxColumnTotal.value) * 100))
}

// 右下大卡：近期动态清单（真实整合流水、任务执行、数据记录与网站访问）
function formatRelative(iso: string): string {
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - ms) / 1000))
  if (diffSec < 60) return '刚刚'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const d = new Date(ms)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const activityItems = computed<ActivityEntry[]>(() => {
  const entries: ActivityEntry[] = []

  for (const tx of ledger.items.slice(0, 12)) {
    entries.push({
      id: `tx-${tx.id}`,
      kind: 'ledger',
      title: tx.description || tx.categoryName || '账本记录',
      meta: `${tx.categoryName || '未分类'} · ${formatRelative(tx.occurredAt)}`,
      badge: `${tx.type === 'income' ? '+' : '-'}${money.format(Number(tx.amount))}`,
      tone: tx.type === 'income' ? 'ok' : 'default',
      timestamp: tx.occurredAt,
      targetPage: 'Ledger',
    })
  }

  for (const run of automation.runtimeExecutions.slice(0, 8)) {
    const wf = automation.items.find(item => item.id === run.workflowId)
    entries.push({
      id: `run-${run.id}`,
      kind: 'automation',
      title: wf?.name ?? '自动化任务执行',
      meta: `自动化 · ${formatRelative(run.createdAt)}`,
      badge: run.status === 'failed' ? '失败' : run.status === 'running' ? '运行中' : '已完成',
      tone: run.status === 'failed' ? 'danger' : run.status === 'running' ? 'warn' : 'ok',
      timestamp: run.createdAt,
      targetPage: 'Automation',
    })
  }

  for (const rec of dataStore.overview?.recentRecords ?? []) {
    entries.push({
      id: `rec-${rec.id}`,
      kind: 'data',
      title: rec.name,
      meta: `${rec.collectionName} · ${formatRelative(rec.updatedAt)}`,
      badge: rec.status || '已更新',
      tone: rec.statusTone === 'success' ? 'ok' : rec.statusTone === 'warning' ? 'warn' : 'default',
      timestamp: rec.updatedAt,
      targetPage: 'Data',
    })
  }

  for (const site of allSites.value.filter(s => s.lastVisitedAt).slice(0, 6)) {
    entries.push({
      id: `web-${site.id}`,
      kind: 'website',
      title: `访问 ${site.name}`,
      meta: `${siteHostname(site.url)} · ${formatRelative(site.lastVisitedAt!)}`,
      badge: '网站',
      tone: 'default',
      timestamp: site.lastVisitedAt!,
      targetPage: 'Websites',
    })
  }

  const filtered = activityFilter.value === 'all'
    ? entries
    : entries.filter(item => item.kind === activityFilter.value)

  return filtered
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
    .slice(0, 8)
})

let isCounting = false

// Count-up 数字递增与表盘弧线生长动画
function runCountUp() {
  if (countFrame) cancelAnimationFrame(countFrame)

  const reduced = document.documentElement.dataset.motion === 'reduced'
  if (reduced) {
    isCounting = false
    animExpense.value = periodExpense.value
    animActive.value = systemCombinedActive.value
    animRecords.value = totalRecords.value
    gaugeProgress.value = gaugeState.value.pct
    return
  }

  isCounting = true
  animExpense.value = 0
  animActive.value = 0
  animRecords.value = 0
  gaugeProgress.value = 0

  const start = performance.now()
  const duration = 520
  const tick = (nowTs: number) => {
    const progress = Math.min(1, (nowTs - start) / duration)
    const eased = 1 - Math.pow(1 - progress, 3)
    // 每帧读取最新响应式目标值，确保异步完成的同步状态/设备请求平滑汇入终值
    const targetExp = periodExpense.value
    const targetSys = systemCombinedActive.value
    const targetRec = totalRecords.value
    const targetGauge = gaugeState.value.pct
    animExpense.value = targetExp * eased
    animActive.value = Math.round(targetSys * eased)
    animRecords.value = Math.round(targetRec * eased)
    gaugeProgress.value = targetGauge * eased
    if (progress < 1) {
      countFrame = requestAnimationFrame(tick)
    } else {
      isCounting = false
      animExpense.value = targetExp
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
)

// 后台同步状态或快速录入异步到达时，实时同步最新指标与表盘弧度
watch(
  [periodExpense, systemCombinedActive, totalRecords, () => gaugeState.value.pct],
  ([exp, sys, rec, pct]) => {
    if (revealSeq.value > 0 && !showSkeleton.value && !isCounting) {
      animExpense.value = exp
      animActive.value = sys
      animRecords.value = rec
      gaugeProgress.value = pct
    }
  },
)

// 移动端与旧兼容层所需计算属性
const transactions = computed(() => [...ledger.items].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt)))
const mobileBars = computed(() => {
  const days = Array.from({ length: now.getDate() }, () => 0)
  for (const item of transactions.value) {
    if (item.type !== 'expense' || localMonthKey(item.occurredAt) !== monthKey) continue
    const day = new Date(item.occurredAt).getDate() - 1
    days[day] = (days[day] ?? 0) + Number(item.amount)
  }
  const max = Math.max(1, ...days)
  return days.map(value => 100 * value / max)
})
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
  if (refreshTimer) clearTimeout(refreshTimer)
  if (countFrame) cancelAnimationFrame(countFrame)
})
</script>

<template>
  <!-- 移动端保持既有简洁体验：去掉顶部臃肿文字与头像，只在右上角保留设置图标 -->
  <div v-if="mobile" class="mpage">
    <div class="mhead-minimal">
      <button class="mhead-settings" type="button" aria-label="设置" title="设置" @click="emit('navigate', 'Settings')">
        <Settings :size="18" :stroke-width="1.9" />
      </button>
    </div>
    <div class="quick">
      <button type="button" @click="emit('add', 'tx')"><span class="qi"><OpusIcon name="ledger" /></span>记一笔</button>
      <button type="button" @click="emit('add', 'web')"><span class="qi"><OpusIcon name="globe" /></span>收藏</button>
      <button type="button" @click="emit('navigate', 'Chat')"><span class="qi"><OpusIcon name="chat" /></span>问 Agent</button>
      <button type="button" @click="emit('navigate', 'Space')"><span class="qi"><OpusIcon name="shield" /></span>共享空间</button>
    </div>
    <section class="mcard mat">
      <div class="mcard-h"><OpusIcon name="ledger" /> {{ month }}支出<span class="spacer"></span><button class="btn btn-sm btn-subtle" type="button" @click="emit('navigate', 'Ledger')">账本 <OpusIcon name="chevR" /></button></div>
      <div class="mbig num">{{ money.format(periodExpense) }}<small v-if="periodIncome > 0">/ 收入 {{ money.format(periodIncome) }}</small><small v-else>未录收入</small></div>
      <div :key="revealSeq" class="spark" aria-hidden="true"><i v-for="(value, i) in mobileBars" :key="i" :style="{ height: Math.max(8, value) + '%', animationDelay: i * 15 + 'ms' }"></i></div>
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
          <span class="bm-fav">
            <img v-if="site.icon && /^https?:\/\//i.test(site.icon)" class="opus-favicon" :src="site.icon" alt="" />
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
          <template v-if="idx === 4">
            <div class="sk sk-gauge"></div>
          </template>
          <template v-else>
            <div class="sk sk-num"></div>
            <div class="sk sk-meta"></div>
          </template>
        </div>
      </template>

      <template v-else>
        <!-- 小卡 1：支出总额 -->
        <button type="button" class="deliv-card is-clickable" @click="emit('navigate', 'Ledger')">
          <div class="deliv-head">
            <span class="deliv-icon"><Wallet :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy">
              <strong>{{ range === '7d' ? '近 7 天支出' : '本月支出' }}</strong>
              <span>账本消费总额</span>
            </div>
          </div>
          <div class="deliv-kpi-body">
            <div class="deliv-value num">{{ money.format(animExpense) }}</div>
            <div v-if="expenseTrendDelta !== null" class="deliv-delta" :class="expenseTrendDelta <= 0 ? 'is-good' : 'is-bad'">
              {{ expenseTrendDelta > 0 ? `↗ +${expenseTrendDelta}%` : `↘ ${expenseTrendDelta}%` }} 较上期
            </div>
            <div v-else class="deliv-delta">共 {{ periodTxCount }} 笔流水</div>
          </div>
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

        <!-- 小卡 4：半圆弧形表盘（收支比 / 同步健康智能降级） -->
        <button
          type="button"
          class="deliv-card is-clickable"
          @click="gaugeState.target === 'Sync' ? emit('sync') : emit('navigate', 'Ledger')"
        >
          <div class="deliv-head">
            <span class="deliv-icon"><Activity :size="15" :stroke-width="1.9" /></span>
            <div class="deliv-head-copy">
              <strong>{{ gaugeState.title }}</strong>
              <span>{{ gaugeState.sub }}</span>
            </div>
          </div>
          <div class="deliv-gauge-wrap">
            <div class="deliv-gauge-arc">
              <svg viewBox="0 0 132 72" class="deliv-gauge-svg" aria-hidden="true">
                <path class="gauge-track" d="M 14 64 A 52 52 0 0 1 118 64" />
                <path
                  class="gauge-fill"
                  d="M 14 64 A 52 52 0 0 1 118 64"
                  :stroke-dasharray="163.36"
                  :stroke-dashoffset="163.36 * (1 - gaugeProgress / 100)"
                />
              </svg>
              <div class="deliv-gauge-val num">{{ gaugeState.centerText }}</div>
            </div>
            <div class="deliv-gauge-cap">{{ gaugeState.caption }}</div>
          </div>
        </button>
      </template>
    </section>

    <!-- 第二行：2 张等高大卡（左：收支对比柱状图 · 右：近期动态清单） -->
    <section class="wide-grid" aria-label="趋势与近期动态">
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
            <span v-for="n in 5" :key="n" class="sk sk-row"></span>
          </div>
        </div>
      </template>

      <template v-else>
        <!-- 左大卡：Delivry 双色对比柱状图 -->
        <section class="deliv-card deliv-wide" aria-labelledby="h-chart">
          <div class="deliv-wide-top">
            <div class="deliv-head">
              <span class="deliv-icon"><LayoutList :size="15" :stroke-width="1.9" /></span>
              <div class="deliv-head-copy">
                <strong id="h-chart">收支统计</strong>
                <span>{{ range === '7d' ? '最近 7 日支出与收入对照' : `${month} 各周支出与收入对照` }}</span>
              </div>
            </div>
            <div class="chart-legend">
              <span><i class="dot-exp"></i>支出</span>
              <span><i class="dot-inc"></i>收入</span>
            </div>
          </div>

          <div class="deliv-chart-area" :key="'chart-' + revealSeq">
            <div class="chart-y" aria-hidden="true">
              <span v-for="(tick, idx) in yTicks" :key="idx">{{ tick >= 1000 ? `${(tick / 1000).toFixed(1)}k` : tick }}</span>
            </div>
            <div class="chart-plot">
              <div class="chart-gridlines" aria-hidden="true">
                <span></span><span></span><span></span><span></span>
              </div>
              <div class="chart-cols">
                <div
                  v-for="(col, i) in chartColumns"
                  :key="col.fullLabel"
                  class="chart-col-wrap"
                  @mouseenter="hoveredBarIndex = i"
                  @mouseleave="hoveredBarIndex = null"
                >
                  <div v-if="hoveredBarIndex === i" class="chart-tooltip" role="status">
                    <div class="tt-title">{{ col.fullLabel }}</div>
                    <div class="tt-row"><i class="dot-exp"></i>支出 {{ money.format(col.expense) }}</div>
                    <div class="tt-row"><i class="dot-inc"></i>收入 {{ money.format(col.income) }}</div>
                  </div>
                  <div class="chart-stack">
                    <span
                      v-if="col.income > 0"
                      class="bar-inc"
                      :style="{ height: colHeightPercent(col.income) + '%', animationDelay: i * 32 + 'ms' }"
                    ></span>
                    <span
                      class="bar-exp"
                      :class="{ 'is-empty': col.expense === 0 && col.income === 0 }"
                      :style="{
                        height: col.expense > 0 ? colHeightPercent(col.expense) + '%' : col.income > 0 ? '0%' : '3px',
                        animationDelay: i * 32 + 'ms',
                      }"
                    ></span>
                  </div>
                  <span class="chart-x">{{ col.label }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 右大卡：近期动态清单 -->
        <section class="deliv-card deliv-wide" aria-labelledby="h-feed">
          <div class="deliv-wide-top">
            <div class="deliv-head">
              <span class="deliv-icon"><CheckCircle2 :size="15" :stroke-width="1.9" /></span>
              <div class="deliv-head-copy">
                <strong id="h-feed">近期动态</strong>
                <span>来自账本、任务、数据与网站</span>
              </div>
            </div>
            <div class="feed-tabs" role="group" aria-label="动态筛选">
              <button type="button" :aria-pressed="activityFilter === 'all'" @click="activityFilter = 'all'">全部</button>
              <button type="button" :aria-pressed="activityFilter === 'ledger'" @click="activityFilter = 'ledger'">账本</button>
              <button type="button" :aria-pressed="activityFilter === 'automation'" @click="activityFilter = 'automation'">任务</button>
              <button type="button" :aria-pressed="activityFilter === 'data'" @click="activityFilter = 'data'">数据</button>
            </div>
          </div>

          <div class="feed-list" :key="'feed-' + revealSeq + '-' + activityFilter">
            <button
              v-for="(item, idx) in activityItems"
              :key="item.id"
              type="button"
              class="feed-row"
              :style="{ animationDelay: idx * 35 + 'ms' }"
              @click="emit('navigate', item.targetPage)"
            >
              <span class="feed-kind-dot" :class="`is-${item.kind}`">
                <OpusIcon :name="item.kind === 'ledger' ? 'ledger' : item.kind === 'automation' ? 'tasks' : item.kind === 'data' ? 'data' : 'globe'" />
              </span>
              <span class="feed-main">
                <strong class="feed-title">{{ item.title }}</strong>
                <small class="feed-meta">{{ item.meta }}</small>
              </span>
              <span class="feed-badge num" :class="`is-${item.tone}`">{{ item.badge }}</span>
            </button>

            <div v-if="!activityItems.length" class="feed-empty">
              <span>暂无近期动态</span>
              <div class="feed-empty-actions">
                <button type="button" class="btn btn-sm btn-ghost" @click="emit('create', 'ledger')">+ 记一笔</button>
                <button type="button" class="btn btn-sm btn-ghost" @click="emit('create', 'website')">+ 收藏网站</button>
              </div>
            </div>
          </div>
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

/* 半圆弧表盘（绝对居中定位，随卡片同步放大不位移） */
.deliv-gauge-wrap {
  display: grid;
  justify-items: center;
  margin: auto 0;
}
.deliv-gauge-arc {
  position: relative;
  display: grid;
  place-items: center;
}
.deliv-gauge-svg { width: clamp(132px, 12cqi, 232px); height: auto; aspect-ratio: 132 / 72; overflow: visible; }
.gauge-track { fill: none; stroke: var(--surface-3); stroke-width: 11; stroke-linecap: butt; }
.gauge-fill {
  fill: none;
  stroke: var(--accent);
  stroke-width: 11;
  stroke-linecap: butt;
  transition: stroke-dashoffset 680ms var(--ease-out);
}
[data-motion="reduced"] .gauge-fill { transition: none; }
.deliv-gauge-val {
  position: absolute;
  bottom: 2px;
  left: 50%;
  translate: -50% 0;
  font-size: clamp(14px, 1.35cqi, 24px);
  font-weight: 750;
  color: var(--text);
  letter-spacing: -.02em;
  white-space: nowrap;
}
.deliv-gauge-cap { font-size: clamp(11px, 0.85cqi, 14px); color: var(--text-3); margin-top: 4px; }

/* 第二行宽卡与图表 */
.deliv-wide { min-height: 308px; }
.deliv-wide-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.chart-legend {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11.5px;
  color: var(--text-2);
}
.chart-legend span { display: inline-flex; align-items: center; gap: 5px; }
.dot-exp, .dot-inc { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.dot-exp { background: var(--accent); }
.dot-inc { background: var(--line-strong); }

.deliv-chart-area {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 10px;
  flex: 1;
  min-height: 224px;
  padding-top: 8px;
}
.chart-y {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding-bottom: 24px;
  font-size: 11px;
  color: var(--text-3);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.chart-plot {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chart-gridlines {
  position: absolute;
  inset: 0 0 24px 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}
.chart-gridlines span {
  border-top: 1px dashed var(--line);
}
.chart-gridlines span:last-child {
  border-top: 1px solid var(--line-strong);
}
.chart-cols {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  align-items: stretch;
  gap: 10px;
}
.chart-col-wrap {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}
.chart-stack {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  gap: 2px;
  padding-bottom: 6px;
}
.bar-exp, .bar-inc {
  display: block;
  width: clamp(14px, 42%, 26px);
  border-radius: 3px 3px 0 0;
  transform-origin: bottom;
  animation: colRise 460ms var(--ease-out) both;
}
.bar-exp { background: var(--accent); }
.bar-exp.is-empty { background: var(--surface-3); border-radius: 2px; }
.bar-inc { background: var(--line-strong); border-radius: 3px 3px 0 0; }
.bar-inc + .bar-exp { border-radius: 0; }
@keyframes colRise {
  from { transform: scaleY(0); opacity: .45; }
  to { transform: scaleY(1); opacity: 1; }
}
[data-motion="reduced"] .bar-exp,
[data-motion="reduced"] .bar-inc { animation: none; }

.chart-x {
  height: 18px;
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}
.chart-tooltip {
  position: absolute;
  top: 4px;
  z-index: 10;
  padding: 7px 9px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-strong);
  background: var(--solid);
  box-shadow: var(--shadow-2);
  font-size: 11px;
  white-space: nowrap;
  pointer-events: none;
}
.tt-title { font-weight: 650; color: var(--text); margin-bottom: 3px; }
.tt-row { display: flex; align-items: center; gap: 5px; color: var(--text-2); }

/* 右大卡：近期动态清单 */
.feed-tabs {
  display: inline-flex;
  padding: 2px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  gap: 2px;
}
.feed-tabs button {
  height: 24px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 11.5px;
  color: var(--text-2);
}
.feed-tabs button[aria-pressed="true"] {
  background: var(--solid);
  color: var(--text);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .06);
}
.feed-list {
  display: grid;
  gap: clamp(3px, 0.7vh, 10px);
  align-content: start;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.feed-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: clamp(7px, 1vh, 13px) 10px;
  border-radius: var(--r-sm);
  text-align: left;
  transition: background-color var(--dur-1);
  animation: rowFade 320ms var(--ease-out) both;
}
.feed-row:hover { background: var(--surface-2); }
@keyframes rowFade {
  from { opacity: 0; translate: 0 4px; }
  to { opacity: 1; translate: none; }
}
[data-motion="reduced"] .feed-row { animation: none; }
.feed-kind-dot {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--text-2);
  flex: none;
}
.feed-kind-dot svg { width: 14px; height: 14px; }
.feed-main { flex: 1; min-width: 0; display: grid; gap: 1px; }
.feed-title { font-size: 13px; font-weight: 550; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-meta { font-size: 11.5px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-badge { font-size: 12px; font-weight: 600; color: var(--text-2); white-space: nowrap; }
.feed-badge.is-ok { color: var(--ok); }
.feed-badge.is-danger { color: var(--danger); }
.feed-badge.is-warn { color: var(--warn); }

.feed-empty {
  display: grid;
  place-items: center;
  gap: 10px;
  padding: 44px 16px;
  color: var(--text-3);
  font-size: 12.5px;
}
.feed-empty-actions { display: flex; gap: 8px; }

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
  height: 200px;
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

/* 移动端极简顶部角落设置按钮 */
.mhead-minimal {
  display: flex;
  justify-content: flex-end;
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
</style>
