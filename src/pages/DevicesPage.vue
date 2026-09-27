<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity, Battery, Check, ChevronDown, CircleAlert, Clock3, Cpu,
  HardDrive, Laptop, MemoryStick, Monitor, MonitorSmartphone, Network,
  Plus, RotateCw, Server, Smartphone, Tablet, Wifi, X,
} from 'lucide-vue-next'
import ActionButton from '../components/ui/ActionButton.vue'
import GlassCard from '../components/ui/GlassCard.vue'
import SectionContainer from '../components/ui/SectionContainer.vue'
import StatCard from '../components/ui/StatCard.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'
import { useAuthStore } from '../stores/auth'
import { useDevicesStore } from '../stores/devices'
import type { Device, DeviceKind } from '../types/device'

type DeviceFilter = 'all' | 'online' | 'offline'

const emit = defineEmits<{ action: [message: string] }>()
const auth = useAuthStore()
const store = useDevicesStore()
const devices = computed(() => store.devices)
const activeFilter = ref<DeviceFilter>('all')
const selectedId = ref('')
const showAddDialog = ref(false)
const dialogMode = ref<'add' | 'edit'>('add')
const justUpdated = ref(false)
const saving = ref(false)
const formError = ref('')
const tokenDialog = ref(false)
const generatedToken = ref('')
const tokenBusy = ref(false)
const tokenError = ref('')
let statusRefresh: ReturnType<typeof setInterval> | undefined
const draft = ref({ name: '', system: '', ip: '', location: '', kind: 'desktop' as DeviceKind })

function openCreate() {
  dialogMode.value = 'add'
  draft.value = { name: '', system: '', ip: '', location: '', kind: 'desktop' }
  formError.value = ''
  showAddDialog.value = true
}
function openEdit() {
  const item = selectedDevice.value
  if (!item) return
  dialogMode.value = 'edit'
  draft.value = { name: item.name, system: item.system, ip: item.ip, location: item.location, kind: item.kind }
  formError.value = ''
  showAddDialog.value = true
}
defineExpose({ openCreate })
watch(devices, items => {
  if (!items.some(item => item.id === selectedId.value)) selectedId.value = items[0]?.id ?? ''
}, { immediate: true })
onMounted(() => {
  if (auth.token) void store.load(auth.token, true)
  statusRefresh = setInterval(() => { if (auth.token) void store.load(auth.token, true) }, 30_000)
})
onUnmounted(() => { if (statusRefresh) clearInterval(statusRefresh) })

const onlineDevices = computed(() => devices.value.filter(device => device.online))
const offlineCount = computed(() => devices.value.length - onlineDevices.value.length)
const averageCpu = computed(() => onlineDevices.value.length
  ? Math.round(onlineDevices.value.reduce((sum, device) => sum + device.cpu, 0) / onlineDevices.value.length)
  : 0)
const filteredDevices = computed(() => devices.value.filter(device =>
  activeFilter.value === 'all' || (activeFilter.value === 'online' ? device.online : !device.online)))
const selectedDevice = computed(() => devices.value.find(device => device.id === selectedId.value) ?? devices.value[0])
const selectedMetrics = computed(() => selectedDevice.value ? [
  { label: 'CPU', value: selectedDevice.value.cpu, display: `${selectedDevice.value.cpu}%`, icon: Cpu, tone: 'blue' },
  { label: '内存', value: selectedDevice.value.memory, display: `${selectedDevice.value.memory}%`, icon: MemoryStick, tone: 'violet' },
  { label: '磁盘', value: selectedDevice.value.disk, display: `${selectedDevice.value.disk}%`, icon: HardDrive, tone: 'cyan' },
  { label: '电量', value: selectedDevice.value.battery ?? 0, display: selectedDevice.value.battery === null ? '—' : `${selectedDevice.value.battery}%`, icon: Battery, tone: 'mint' },
] : [])

const filters: { label: string; value: DeviceFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '在线', value: 'online' },
  { label: '离线', value: 'offline' },
]

function deviceIcon(kind: DeviceKind) {
  return { desktop: Monitor, mac: Laptop, phone: Smartphone, tablet: Tablet, server: Server, nas: HardDrive }[kind]
}

function sparkline(values: number[], width = 130, height = 35) {
  const step = width / Math.max(values.length - 1, 1)
  return values.map((value, index) => `${Math.round(index * step)},${Math.round(height - 4 - value * (height - 8) / 100)}`).join(' ')
}

async function refreshDevices() {
  if (!auth.token) return
  await store.load(auth.token, true)
  if (!store.error) {
    justUpdated.value = true
    window.setTimeout(() => { justUpdated.value = false }, 2200)
  }
}

function setFilter(filter: DeviceFilter) {
  activeFilter.value = filter
  const visible = devices.value.filter(device => filter === 'all' || (filter === 'online' ? device.online : !device.online))
  if (visible.length && !visible.some(device => device.id === selectedId.value)) selectedId.value = visible[0].id
}

async function saveDevice() {
  if (!auth.token || saving.value) return
  const name = draft.value.name.trim()
  const system = draft.value.system.trim()
  const ip = draft.value.ip.trim()
  if (!name || !system || !ip) { formError.value = '请填写设备名称、系统和地址。'; return }
  saving.value = true
  formError.value = ''
  try {
    const data = { name, system, ip, location: draft.value.location.trim(), kind: draft.value.kind }
    const item = dialogMode.value === 'edit' && selectedId.value
      ? await store.update(auth.token, selectedId.value, data)
      : await store.create(auth.token, data)
    selectedId.value = item.id
    activeFilter.value = 'all'
    showAddDialog.value = false
    emit('action', dialogMode.value === 'edit' ? '设备已更新。' : '设备已添加，等待首次心跳。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}

async function removeDevice() {
  const item = selectedDevice.value
  if (!auth.token || !item || !window.confirm(`删除「${item.name}」？`)) return
  try { await store.remove(auth.token, item.id); emit('action', '设备已删除。') }
  catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') }
}

function closeTokenDialog() { tokenDialog.value = false; generatedToken.value = ''; tokenError.value = '' }
function openTokenDialog() { generatedToken.value = ''; tokenError.value = ''; tokenDialog.value = true }
async function generateToken() {
  if (!auth.token || !selectedDevice.value || tokenBusy.value) return
  tokenBusy.value = true
  tokenError.value = ''
  try { generatedToken.value = (await store.generateToken(auth.token, selectedDevice.value.id)).token }
  catch (error) { tokenError.value = error instanceof Error ? error.message : '生成失败' }
  finally { tokenBusy.value = false }
}
async function copyToken() {
  try { await navigator.clipboard.writeText(generatedToken.value); emit('action', 'Device Token 已复制。') }
  catch { tokenError.value = '复制失败，请手动复制。' }
}
</script>

<template>
  <div class="devices-page">
    <h1 class="visually-hidden">设备</h1>
    <div class="device-page-actions" aria-label="设备操作">
      <ActionButton variant="secondary" size="sm" :disabled="store.loading" @click="refreshDevices">
        <Check v-if="justUpdated" :size="16" /><RotateCw v-else :size="16" />
        {{ justUpdated ? '已更新' : '刷新状态' }}
      </ActionButton>
      <ActionButton variant="primary" size="sm" @click="openCreate"><Plus :size="17" />添加设备</ActionButton>
    </div>

    <div class="device-stats" aria-label="设备概览">
      <StatCard label="设备总数" :value="String(devices.length).padStart(2, '0')" detail="已添加的设备" tone="blue">
        <template #icon><MonitorSmartphone :size="20" /></template>
      </StatCard>
      <StatCard label="当前在线" :value="String(onlineDevices.length).padStart(2, '0')" detail="最近收到状态的设备" tone="mint">
        <template #icon><Wifi :size="20" /></template>
      </StatCard>
      <StatCard label="平均 CPU" :value="onlineDevices.length ? `${averageCpu}%` : '—'" detail="最近心跳中的设备" tone="violet">
        <template #icon><Activity :size="20" /></template>
      </StatCard>
      <StatCard label="需要关注" :value="String(offlineCount).padStart(2, '0')" detail="当前离线设备" tone="amber">
        <template #icon><CircleAlert :size="20" /></template>
      </StatCard>
    </div>

    <SectionContainer title="我的设备" class="devices-section">
      <template #action>
        <div class="device-toolbar">
          <span class="sync-note"><span class="sync-dot" />{{ store.loadedAt ? `最近同步于 ${store.loadedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '尚未同步' }}</span>
          <div class="filter-segment" role="group" aria-label="筛选设备">
            <button v-for="filter in filters" :key="filter.value" type="button"
              :class="{ 'is-active': activeFilter === filter.value }"
              :aria-pressed="activeFilter === filter.value"
              @click="setFilter(filter.value)">{{ filter.label }}</button>
          </div>
        </div>
      </template>

      <div v-if="store.loading" class="device-empty" role="status">正在加载设备…</div>
      <div v-else-if="store.error" class="device-empty" role="alert">{{ store.error }} <button type="button" @click="refreshDevices">重试</button></div>
      <div v-else class="device-grid">
        <GlassCard v-for="device in filteredDevices" :key="device.id" class="device-card"
          :class="{ 'device-card--selected': selectedId === device.id, 'device-card--offline': !device.online }"
          role="button" tabindex="0" :aria-pressed="selectedId === device.id"
          :aria-label="`查看${device.name}详情`"
          @click="selectedId = device.id"
          @keydown.enter.prevent="selectedId = device.id"
          @keydown.space.prevent="selectedId = device.id">
          <div class="device-card__top">
            <span class="device-glyph" :class="`device-glyph--${device.kind}`"><component :is="deviceIcon(device.kind)" :size="24" :stroke-width="1.8" /></span>
            <StatusBadge :label="device.online ? '在线' : '离线'" :tone="device.online ? 'success' : 'neutral'" />
          </div>
          <div class="device-card__identity">
            <h3>{{ device.name }}</h3>
            <p>{{ device.hostname || device.system }}</p>
          </div>
          <div class="device-card__ip"><Network :size="13" /><span>{{ device.ip }}</span></div>
          <div class="device-card__divider" />
          <div class="device-card__metrics">
            <div><span>CPU</span><strong>{{ device.lastSeenAt ? `${device.cpu}%` : '—' }}</strong></div>
            <div><span>内存</span><strong>{{ device.lastSeenAt ? `${device.memory}%` : '—' }}</strong></div>
            <div><span>磁盘</span><strong>{{ device.lastSeenAt ? `${device.disk}%` : '—' }}</strong></div>
            <div><span>电量</span><strong>{{ device.lastSeenAt && device.battery !== null ? `${device.battery}%` : '—' }}</strong></div>
          </div>
          <div class="device-card__activity">
            <span>{{ device.online ? '最近心跳' : `最后在线 · ${device.lastSeen}` }}</span>
            <svg viewBox="0 0 130 35" preserveAspectRatio="none" aria-hidden="true">
              <polyline :points="sparkline(device.activity)" />
            </svg>
          </div>
        </GlassCard>
        <div v-if="!filteredDevices.length" class="device-empty">{{ devices.length ? '这个分类下还没有设备。' : '还没有设备。添加设备后，向心跳接口发送指标即可显示在线状态。' }}</div>
      </div>
    </SectionContainer>

    <SectionContainer v-if="selectedDevice" title="设备详情" class="detail-section">
      <template #action><span class="detail-caption"><Clock3 :size="14" />{{ selectedDevice.online ? '最近心跳' : `最后更新 ${selectedDevice.lastSeen}` }}</span></template>
      <div class="detail-panel">
        <div class="detail-panel__identity">
          <span class="detail-icon" :class="`device-glyph--${selectedDevice.kind}`"><component :is="deviceIcon(selectedDevice.kind)" :size="31" :stroke-width="1.7" /></span>
          <div class="detail-name"><div class="detail-name__title"><h3>{{ selectedDevice.name }}</h3><StatusBadge :label="selectedDevice.online ? '在线' : '离线'" :tone="selectedDevice.online ? 'success' : 'neutral'" /></div><p>{{ selectedDevice.hostname || '等待设备上报主机名' }}</p></div>
          <div class="detail-meta"><div><span>Windows</span><strong>{{ selectedDevice.osVersion || selectedDevice.system }}</strong></div><div><span>架构</span><strong>{{ selectedDevice.architecture || '—' }}</strong></div><div><span>局域网 IP</span><strong>{{ selectedDevice.localIp || '—' }}</strong></div><div><span>设备位置</span><strong>{{ selectedDevice.location || '未设置' }}</strong></div><div><span>最后活跃</span><strong>{{ selectedDevice.lastSeen }}</strong></div><div><span>Client</span><strong>{{ selectedDevice.clientVersion || '—' }}</strong></div></div>
          <div class="device-detail-actions"><ActionButton variant="secondary" size="sm" @click="openEdit">编辑设备</ActionButton><ActionButton variant="secondary" size="sm" @click="openTokenDialog">{{ selectedDevice.tokenLast4 ? '重新生成 Device Token' : '生成 Device Token' }}</ActionButton><ActionButton variant="secondary" size="sm" @click="removeDevice">删除设备</ActionButton></div>
          <p class="device-token-mask">{{ selectedDevice.tokenLast4 ? `当前 Token：nd_live_••••${selectedDevice.tokenLast4}` : '尚未生成 Device Token' }}</p>
        </div>
        <div class="detail-panel__resources">
          <div class="detail-resources__head"><span>资源使用</span><span>{{ selectedDevice.lastSeenAt ? '最近一次心跳' : '等待首次心跳' }}</span></div>
          <div class="resource-grid">
            <div v-for="metric in selectedMetrics" :key="metric.label" class="resource-item" :class="`resource-item--${metric.tone}`">
              <div class="resource-item__head"><span><component :is="metric.icon" :size="14" />{{ metric.label }}</span><strong>{{ selectedDevice.lastSeenAt ? metric.display : '—' }}</strong></div>
              <div class="resource-item__track"><i :style="{ width: selectedDevice.lastSeenAt ? `${metric.value}%` : '0%' }" /></div>
            </div>
          </div>
          <div class="detail-trend"><span>活动趋势</span><svg viewBox="0 0 390 43" preserveAspectRatio="none" aria-hidden="true"><polyline :points="sparkline(selectedDevice.activity, 390, 43)" /></svg><span>24 小时</span></div>
        </div>
      </div>
    </SectionContainer>

    <div v-if="tokenDialog" class="device-dialog-backdrop" @click.self="closeTokenDialog">
      <div class="device-dialog" role="dialog" aria-modal="true" aria-labelledby="device-token-title" @keydown.esc="closeTokenDialog">
        <div class="device-dialog__header"><div><span>DEVICE TOKEN</span><h2 id="device-token-title">{{ selectedDevice?.tokenLast4 ? '管理 Device Token' : '生成 Device Token' }}</h2><p>此令牌只允许这台设备发送心跳。</p></div><button type="button" class="device-dialog__close" aria-label="关闭" @click="closeTokenDialog"><X :size="18" /></button></div>
        <template v-if="generatedToken"><p class="device-token-warning">该 Token 仅显示一次，请立即保存。重新生成后旧 Token 立即失效。</p><input class="device-token-value" :value="generatedToken" readonly aria-label="新生成的 Device Token" @focus="($event.target as HTMLInputElement).select()" /><div class="device-dialog__actions"><ActionButton variant="secondary" type="button" @click="copyToken">复制</ActionButton><ActionButton variant="primary" type="button" @click="closeTokenDialog">完成</ActionButton></div></template>
        <template v-else><p class="device-token-warning">{{ selectedDevice?.tokenLast4 ? `当前 Token：nd_live_••••${selectedDevice.tokenLast4}。重新生成会立即停用旧 Token。` : '生成后请将 Token 保存到 Windows Client 的 config.json。' }}</p><div class="device-dialog__actions"><ActionButton variant="secondary" type="button" @click="closeTokenDialog">取消</ActionButton><ActionButton variant="primary" type="button" :disabled="tokenBusy" @click="generateToken">{{ tokenBusy ? '生成中…' : selectedDevice?.tokenLast4 ? '重新生成' : '生成 Token' }}</ActionButton></div></template>
        <p v-if="tokenError" class="device-form-error" role="alert">{{ tokenError }}</p>
      </div>
    </div>

    <div v-if="showAddDialog" class="device-dialog-backdrop" @click.self="showAddDialog = false">
      <form class="device-dialog" role="dialog" aria-modal="true" aria-labelledby="add-device-title" @submit.prevent="saveDevice" @keydown.esc="showAddDialog = false">
        <div class="device-dialog__header"><div><span>CONNECT DEVICE</span><h2 id="add-device-title">{{ dialogMode === 'edit' ? '编辑设备' : '添加设备' }}</h2><p>设备状态由心跳接口提供，不会自动探测地址。</p></div><button type="button" class="device-dialog__close" aria-label="关闭" @click="showAddDialog = false"><X :size="18" /></button></div>
        <div class="device-dialog__fields">
          <label>设备名称<input v-model="draft.name" required placeholder="例如：我的笔记本" autofocus /></label>
          <label>操作系统<input v-model="draft.system" required placeholder="例如：Windows 11" /></label>
          <label>IP 地址<input v-model="draft.ip" required placeholder="例如：192.168.31.120" /></label>
          <label>设备位置<input v-model="draft.location" placeholder="例如：书房" /></label>
          <label>设备类型<span class="device-dialog__select"><select v-model="draft.kind"><option value="desktop">台式电脑</option><option value="mac">笔记本电脑</option><option value="phone">手机</option><option value="tablet">平板电脑</option><option value="server">服务器</option><option value="nas">NAS</option></select><ChevronDown :size="16" /></span></label>
        </div>
        <p v-if="formError" class="device-form-error" role="alert">{{ formError }}</p>
        <div class="device-dialog__actions"><ActionButton variant="secondary" type="button" :disabled="saving" @click="showAddDialog = false">取消</ActionButton><ActionButton variant="primary" type="submit" :disabled="saving"><Plus :size="16" />{{ saving ? '保存中…' : dialogMode === 'edit' ? '保存修改' : '添加设备' }}</ActionButton></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.devices-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; padding-bottom: 28px; }
.visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.device-page-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; min-height: 31px; }
.device-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 15px; }
.device-toolbar { display: flex; align-items: center; gap: 18px; }
.sync-note { display: inline-flex; align-items: center; gap: 7px; color: rgba(255,255,255,.83); font-size: 12px; white-space: nowrap; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.sync-dot { width: 6px; height: 6px; border-radius: 50%; background: #47bb91; box-shadow: 0 0 0 3px rgba(71,187,145,.14); }
.filter-segment { display: inline-flex; gap: 3px; padding: 4px; border: 1px solid rgba(255,255,255,.48); border-radius: 12px; background: rgba(217,229,255,.22); box-shadow: inset 0 1px 3px rgba(88,109,159,.07); backdrop-filter:blur(var(--glass-blur)); }
.filter-segment button { min-width: 45px; padding: 5px 10px; border: 0; border-radius: 8px; background: transparent; color: rgba(255,255,255,.84); font-size: 12px; font-weight: 600; text-shadow:0 1px 6px rgba(25,38,76,.3); transition: background .2s, color .2s, box-shadow .2s; }
.filter-segment button:hover { color: #fff; }
.filter-segment button.is-active { background: rgba(255,255,255,.68); color: #365488; box-shadow: 0 2px 7px rgba(68,86,142,.11); text-shadow:none; }
.device-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 15px; }
.device-card { min-height: 235px; height: auto; padding: 19px 19px 15px; border-radius: 15px; border: var(--glass-tile-border); background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); cursor: pointer; }
.device-card:hover { transform: translateY(-3px) scale(1.02); background: var(--glass-tile-hover-background); box-shadow: var(--glass-tile-hover-shadow); }
.device-card--selected { border-color: rgba(108,137,235,.68); box-shadow: 0 10px 30px rgba(76,111,217,.15), 0 0 0 2px rgba(112,142,238,.09), inset 0 1px 0 rgba(255,255,255,.95); }
.device-card--offline { background: linear-gradient(105deg,rgba(248,249,255,.58),rgba(238,239,255,.48)); }
.device-card :deep(.glass-card__body) { display: flex; flex-direction: column; overflow: visible; }
.device-card__top { display: flex; justify-content: space-between; align-items: flex-start; }
.device-glyph { display: grid; width: 45px; height: 45px; flex: none; place-items: center; border: 1px solid rgba(136,163,244,.20); border-radius: 14px; background: linear-gradient(145deg, #eff3ff, #e3eaff); color: #6281d8; box-shadow: inset 0 1px 0 #fff; }
.device-glyph--mac { background: linear-gradient(145deg, #f4f1ff, #eae5ff); color: #8a75cb; }
.device-glyph--phone, .device-glyph--tablet { background: linear-gradient(145deg, #effbf9, #e0f3f1); color: #4baea3; }
.device-glyph--server, .device-glyph--nas { background: linear-gradient(145deg, #f0f3ff, #e4ebf8); color: #637caa; }
.device-card__identity { margin-top: 14px; }
.device-card__identity h3 { margin: 0; color: #263653; font-size: 16px; font-weight: 710; letter-spacing: -.025em; line-height: 1.25; }
.device-card__identity p { margin: 4px 0 0; color: #52617a; font-size: 12px; }
.device-card__ip { display: flex; align-items: center; gap: 6px; margin-top: 10px; color: #52617a; font-size: 11px; font-variant-numeric: tabular-nums; }
.device-card__ip svg { color: #9aa8c0; }
.device-card__divider { height: 1px; margin: 15px 0 12px; background: linear-gradient(90deg, rgba(132,153,195,.2), rgba(132,153,195,.08)); }
.device-card__metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 5px; }
.device-card__metrics div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.device-card__metrics span { color: #586781; font-size: 10px; }
.device-card__metrics strong { color: #344460; font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.device-card__activity { display: flex; align-items: end; justify-content: space-between; gap: 5px; margin-top: auto; padding-top: 8px; }
.device-card__activity span { padding-bottom: 2px; color: #596984; font-size: 10px; white-space: nowrap; }
.device-card__activity svg { width: 43%; max-width: 130px; height: 35px; overflow: visible; }
.device-card__activity polyline { fill: none; stroke: #7c99e8; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 2px 3px rgba(103,137,231,.18)); }
.device-card--offline .device-card__activity polyline { stroke: #adb7ca; }
.device-empty { grid-column: 1 / -1; padding: 48px; border: 1px dashed rgba(133,153,195,.35); border-radius: 18px; color: #8090ac; text-align: center; font-size: 13px; }
.detail-caption { display: inline-flex; align-items: center; gap: 6px; color: rgba(255,255,255,.82); font-size: 12px; white-space: nowrap; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.detail-panel { display: grid; grid-template-columns: minmax(230px, .8fr) minmax(0, 1.2fr); gap: 22px; padding: 22px; border: var(--glass-tile-border); border-radius: 15px; background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.detail-panel__identity { min-width: 0; }
.detail-icon { display: grid; width: 57px; height: 57px; place-items: center; border: 1px solid rgba(136,163,244,.23); border-radius: 17px; background: linear-gradient(145deg, #eff3ff, #e3eaff); color: #6281d8; }
.detail-name { margin-top: 11px; }
.detail-name__title { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.detail-name h3 { margin: 0; color: #263653; font-size: 20px; font-weight: 730; letter-spacing: -.03em; }
.detail-name p { margin: 4px 0 0; color: #52617a; font-size: 12px; }
.detail-meta { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 8px; margin-top: 22px; }
.detail-meta div { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.detail-meta span { color: #586781; font-size: 10px; }
.detail-meta strong { overflow: hidden; color: #4d5d79; font-size: 11px; font-weight: 630; text-overflow: ellipsis; white-space: nowrap; }
.device-detail-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 17px; }
.detail-panel__resources { min-width: 0; padding-left: 22px; border-left: 1px solid rgba(130,150,190,.17); }
.detail-resources__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; color: #3a4a69; font-size: 13px; font-weight: 680; }
.detail-resources__head span:last-child { color: #5b6b83; font-size: 11px; font-weight: 500; }
.resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 15px 20px; }
.resource-item__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 7px; }
.resource-item__head span { display: inline-flex; align-items: center; gap: 5px; color: #586781; font-size: 11px; }
.resource-item__head strong { color: #344460; font-size: 12px; font-weight: 700; white-space: nowrap; }
.resource-item__track { height: 5px; overflow: hidden; border-radius: 99px; background: rgba(135,158,203,.15); }
.resource-item__track i { display: block; height: 100%; border-radius: inherit; background: #7e9bea; }
.resource-item--violet .resource-item__track i { background: #a395e8; }
.resource-item--cyan .resource-item__track i { background: #7dc0d1; }
.resource-item--mint .resource-item__track i { background: #71c9ad; }
.detail-trend { display: flex; align-items: center; gap: 12px; margin-top: 14px; padding-top: 11px; border-top: 1px solid rgba(130,150,190,.15); }
.detail-trend span { color: #586781; font-size: 10px; white-space: nowrap; }
.detail-trend svg { width: 100%; height: 35px; }
.detail-trend polyline { fill: none; stroke: #879eec; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.device-dialog-backdrop { position: fixed; z-index: 100; inset: 0; display: grid; place-items: center; padding: 20px; background: rgba(33,49,92,.27); backdrop-filter: blur(9px); }
.device-dialog { width: min(100%, 470px); padding: 25px; border: 1px solid rgba(255,255,255,.86); border-radius: 25px; background: linear-gradient(145deg, rgba(251,253,255,.98), rgba(236,242,255,.97)); box-shadow: 0 25px 75px rgba(26,44,97,.25), inset 0 1px 0 #fff; }
.device-dialog__header { display: flex; justify-content: space-between; align-items: start; }
.device-dialog__header span { color: #8a9ad0; font-size: 10px; font-weight: 740; letter-spacing: .16em; }
.device-dialog__header h2 { margin: 6px 0 5px; color: #263653; font-size: 23px; letter-spacing: -.035em; }
.device-dialog__header p { margin: 0; color: #8290a8; font-size: 12px; }
.device-dialog__close { display: grid; width: 31px; height: 31px; place-items: center; border: 1px solid rgba(137,157,198,.18); border-radius: 10px; background: rgba(255,255,255,.7); color: #71809a; }
.device-dialog__fields { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 15px; margin-top: 25px; }
.device-dialog__fields label { display: flex; flex-direction: column; gap: 7px; color: #53627e; font-size: 11px; font-weight: 660; }
.device-dialog__fields input, .device-dialog__fields select { width: 100%; height: 39px; padding: 0 11px; border: 1px solid rgba(131,151,197,.25); border-radius: 11px; outline: none; background: rgba(255,255,255,.83); color: #354665; font-size: 12px; }
.device-dialog__fields input:focus, .device-dialog__fields select:focus { border-color: #839eec; box-shadow: 0 0 0 3px rgba(118,150,231,.13); }
.device-dialog__fields input::placeholder { color: #b3bfd0; }
.device-dialog__select { position: relative; }
.device-dialog__select select { appearance: none; }
.device-dialog__select svg { position: absolute; right: 12px; top: 12px; color: #8b99b0; pointer-events: none; }
.device-dialog__actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 27px; }
.device-form-error { margin: 14px 0 0; color: #b73e55; font-size: 12px; }
.device-token-mask { margin: 10px 0 0; color: #586781; font-size: 11px; }
.device-token-warning { margin: 20px 0 8px; color: #53627e; font-size: 12px; line-height: 1.5; }
.device-token-value { width: 100%; padding: 10px; border: 1px solid rgba(131,151,197,.35); border-radius: 10px; background: white; color: #263653; font-size: 12px; }
@media (max-width: 1180px) { .device-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } .sync-note { display: none; } }
@media (max-width: 850px) { .device-stats { grid-template-columns: repeat(2, minmax(0,1fr)); } .detail-panel { grid-template-columns: 1fr; } .detail-panel__resources { padding: 20px 0 0; border-left: 0; border-top: 1px solid rgba(130,150,190,.17); } }
@media (max-width: 610px) { .devices-page { gap: 18px; } .device-grid { grid-template-columns: 1fr; } .detail-meta { grid-template-columns: repeat(2, minmax(0,1fr)); } .device-dialog__fields { grid-template-columns: 1fr; } }
@media (max-width: 410px) { .device-stats { gap: 9px; } .filter-segment button { min-width: 38px; padding-inline: 7px; } .detail-panel { padding: 16px; } }
</style>
