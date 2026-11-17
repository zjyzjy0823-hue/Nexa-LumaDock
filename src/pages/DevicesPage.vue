<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { HardDrive, Laptop, Monitor, Server, Smartphone, Tablet } from 'lucide-vue-next'
import OpusIcon from '../components/ui/OpusIcon.vue'
import Modal from '../components/ui/Modal.vue'
import { useAuthStore } from '../stores/auth'
import { useDevicesStore } from '../stores/devices'
import type { Device, DeviceKind } from '../types/device'

type DeviceFilter = 'all' | 'online' | 'offline'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ mobile?: boolean; search?: string }>()
const emit = defineEmits<{ action: [message: string]; mobileDetail: [active: boolean] }>()
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

function runViewTransition(update: () => Promise<void> | void, types: string[]) {
  if (props.mobile && typeof document !== 'undefined' && document.startViewTransition && document.documentElement?.dataset.motion !== 'reduced') {
    document.startViewTransition({ update, types })
  } else {
    void update()
  }
}

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
onUnmounted(() => {
  if (statusRefresh) clearInterval(statusRefresh)
  emit('mobileDetail', false)
})

const detailOpen = ref(false)
const filteredDevices = computed(() => devices.value.filter(device =>
  (activeFilter.value === 'all' || (activeFilter.value === 'online' ? device.online : !device.online))
  && [device.name, device.hostname, device.system].some(value => value?.toLowerCase().includes(props.search?.trim().toLowerCase() ?? ''))))
function showDevice(id: string) {
  runViewTransition(async () => {
    selectedId.value = id
    detailOpen.value = true
    if (props.mobile) emit('mobileDetail', true)
    await nextTick()
  }, ['forward'])
}
function closeDetail() {
  runViewTransition(async () => {
    detailOpen.value = false
    if (props.mobile) emit('mobileDetail', false)
    await nextTick()
  }, ['backward'])
}
const selectedDevice = computed(() => devices.value.find(device => device.id === selectedId.value) ?? devices.value[0])
const selectedMetrics = computed(() => selectedDevice.value ? [
  { label: 'CPU', value: selectedDevice.value.cpu, display: `${selectedDevice.value.cpu}%` },
  { label: '内存', value: selectedDevice.value.memory, display: `${selectedDevice.value.memory}%` },
  { label: '磁盘', value: selectedDevice.value.disk, display: `${selectedDevice.value.disk}%` },
  { label: '电量', value: selectedDevice.value.battery ?? 0, display: selectedDevice.value.battery === null ? '—' : `${selectedDevice.value.battery}%` },
] : [])

function deviceIcon(kind: DeviceKind) {
  return { desktop: Monitor, laptop: Laptop, phone: Smartphone, tablet: Tablet, server: Server, nas: HardDrive }[kind]
}

function sparkline(values: number[], width = 390, height = 43) {
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
  if (!auth.token || !item || !(await confirmAction(`删除「${item.name}」？`))) return
  try {
    await store.remove(auth.token, item.id)
    closeDetail()
    emit('action', '设备已删除。')
  } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') }
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
async function revokeToken() {
  const item = selectedDevice.value
  if (!auth.token || !item?.tokenLast4 || tokenBusy.value || !(await confirmAction(`撤销「${item.name}」的 Device Token？当前客户端将无法继续上报。`))) return
  tokenBusy.value = true
  tokenError.value = ''
  try {
    await store.revokeToken(auth.token, item.id)
    closeTokenDialog()
    emit('action', 'Device Token 已撤销，当前客户端将无法继续上报。')
  } catch (error) { tokenError.value = error instanceof Error ? error.message : '撤销失败' }
  finally { tokenBusy.value = false }
}
async function copyToken() {
  try { await navigator.clipboard.writeText(generatedToken.value); emit('action', 'Device Token 已复制。') }
  catch { tokenError.value = '复制失败，请手动复制。' }
}
</script>

<template>
  <div v-if="mobile && detailOpen && selectedDevice" class="mpage push">
    <div class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="closeDetail"><OpusIcon name="chevL" /></button>
      <div class="t">设备详情</div>
      <button class="icon-btn" type="button" aria-label="编辑设备" @click="openEdit"><OpusIcon name="pencil" /></button>
    </div>
    <div class="dhero">
      <div class="tile-icon"><component :is="deviceIcon(selectedDevice.kind)" class="i" /></div>
      <h2>{{ selectedDevice.name }}</h2>
      <span class="conn" :class="selectedDevice.online ? 'online' : 'offline'">{{ selectedDevice.online ? '在线' : '离线' }} · {{ selectedDevice.online ? '最近心跳' : selectedDevice.lastSeen }}</span>
    </div>
    <div class="kvl mat-solid">
      <div><span>系统</span><span>{{ selectedDevice.osVersion || selectedDevice.os || selectedDevice.system }}</span></div>
      <div><span>架构</span><span>{{ selectedDevice.architecture || '—' }}</span></div>
      <div><span>IP 地址</span><span class="mono">{{ selectedDevice.localIp || selectedDevice.ip || '—' }}</span></div>
      <div><span>位置</span><span>{{ selectedDevice.location || '未设置' }}</span></div>
      <div><span>Client</span><span>{{ selectedDevice.clientVersion || '—' }}</span></div>
      <div><span>Token</span><span class="mono">{{ selectedDevice.tokenLast4 ? `nd_live_••${selectedDevice.tokenLast4}` : '未生成' }}</span></div>
    </div>
    <div class="sec-t">资源使用</div>
    <div class="kvl mat-solid">
      <div v-for="metric in selectedMetrics" :key="metric.label">
        <span>{{ metric.label }}</span>
        <span class="num">{{ selectedDevice.lastSeenAt ? metric.display : '—' }}</span>
      </div>
    </div>
    <div class="mbtns">
      <button class="btn btn-ghost" type="button" @click="openTokenDialog"><OpusIcon name="key" />Token</button>
      <button class="btn btn-danger" type="button" @click="removeDevice"><OpusIcon name="trash" />删除设备</button>
    </div>
  </div>
  <div v-else class="devices-page">
    <div v-if="mobile" class="sec-t" style="margin-top:4px">已授权设备<span class="spacer"></span><button class="btn btn-sm btn-subtle" type="button" @click="openCreate"><OpusIcon name="plus" />设备</button></div>
    <header v-else class="ph"><div><h1>设备</h1><div class="sub">已授权的 Studiolo 客户端与遥测设备 · 每台设备独立绑定、可单独吊销</div></div>
      <div class="actions"><button class="icon-btn" type="button" aria-label="刷新状态" :disabled="store.loading" @click="refreshDevices"><OpusIcon :name="justUpdated ? 'check' : 'sync'" /></button><button class="btn btn-primary" type="button" @click="openCreate"><OpusIcon name="plus" />添加设备</button></div>
    </header>
    <div v-if="store.loading && !devices.length" class="cleared" role="status">正在加载设备…</div>
    <div v-else-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-sm btn-ghost" type="button" @click="refreshDevices">重试</button></div>
    <div v-if="mobile" class="mlist mat-solid">
      <button v-for="device in filteredDevices" :key="device.id" class="mrow" type="button" @click="showDevice(device.id)"><span class="tile-icon"><component :is="deviceIcon(device.kind)" class="i" /></span><span class="grow"><div class="title">{{ device.name }}</div><div class="sub">{{ device.system }} · {{ device.location || device.hostname || device.ip }}</div></span><span class="conn" :class="device.online ? 'online' : 'offline'">{{ device.online ? '在线' : '离线' }}</span><OpusIcon name="chevR" /></button>
      <div v-if="!filteredDevices.length && !store.loading" class="mrow faint">暂无设备</div>
    </div>
    <div v-else class="dev-grid">
      <section v-for="device in filteredDevices" :key="device.id" class="dev-card mat">
        <div class="top"><span class="tile-icon" style="width:40px;height:40px"><component :is="deviceIcon(device.kind)" class="i" /></span>
          <div class="grow" style="min-width:0"><div style="font-weight:650">{{ device.name }}</div><div class="faint" style="font-size:12px">{{ device.system }}</div></div>
          <span class="conn" :class="device.online ? 'online' : 'offline'">{{ device.online ? '在线' : '离线' }}</span>
        </div>
        <div class="faint" style="font-size:12.5px">{{ [device.hostname, device.location, device.ip].filter(Boolean).join(' · ') || '等待上报信息' }}</div>
        <div class="btn-row"><button class="btn btn-sm btn-ghost" type="button" @click="showDevice(device.id)">详情</button><button class="btn btn-sm btn-subtle" type="button" @click="selectedId = device.id; openTokenDialog()">Token</button></div>
      </section>
      <div v-if="!filteredDevices.length && !store.loading" class="cleared" style="grid-column:1/-1"><OpusIcon name="device" />暂无设备</div>
    </div>
    <button v-if="mobile" class="btn btn-ghost" type="button" @click="openCreate"><OpusIcon name="plus" />添加设备</button>

    <section v-if="!mobile && detailOpen && selectedDevice" :key="selectedDevice.id" class="card mat enter" style="margin-top:14px">
      <h2 class="card-h">
        <component :is="deviceIcon(selectedDevice.kind)" class="i" />
        {{ selectedDevice.name }} · 详情
        <span class="conn" :class="selectedDevice.online ? 'online' : 'offline'">{{ selectedDevice.online ? '最近心跳' : `最后更新 ${selectedDevice.lastSeen}` }}</span>
        <span class="spacer"></span>
        <button class="icon-btn" type="button" aria-label="关闭详情" @click="closeDetail"><OpusIcon name="x" /></button>
      </h2>
      <div class="dev-detail">
        <div>
          <dl class="meta-grid">
            <dt>主机名</dt><dd>{{ selectedDevice.hostname || '等待设备上报' }}</dd>
            <dt>操作系统</dt><dd>{{ selectedDevice.osVersion || selectedDevice.os || selectedDevice.system }}</dd>
            <dt>架构</dt><dd>{{ selectedDevice.architecture || '—' }}</dd>
            <dt>局域网 IP</dt><dd class="mono">{{ selectedDevice.localIp || selectedDevice.ip || '—' }}</dd>
            <dt>设备位置</dt><dd>{{ selectedDevice.location || '未设置' }}</dd>
            <dt>Client</dt><dd>{{ selectedDevice.clientVersion || '—' }}</dd>
            <dt>Token</dt><dd class="mono">{{ selectedDevice.tokenLast4 ? `nd_live_••••${selectedDevice.tokenLast4}` : '尚未生成' }}</dd>
          </dl>
          <div class="btn-row" style="margin-top:14px">
            <button class="btn btn-sm btn-ghost" type="button" @click="openEdit"><OpusIcon name="pencil" />编辑设备</button>
            <button class="btn btn-sm btn-ghost" type="button" @click="openTokenDialog"><OpusIcon name="key" />{{ selectedDevice.tokenLast4 ? '管理 Token' : '生成 Token' }}</button>
            <button class="btn btn-sm btn-danger" type="button" @click="removeDevice"><OpusIcon name="trash" />删除设备</button>
          </div>
        </div>
        <div class="dev-detail__metrics">
          <div class="dev-metrics-grid">
            <div v-for="metric in selectedMetrics" :key="metric.label" class="dev-metric">
              <div class="dev-metric__head"><span class="muted">{{ metric.label }}</span><b class="num">{{ selectedDevice.lastSeenAt ? metric.display : '—' }}</b></div>
              <div class="meter" style="margin:6px 0 0"><i :style="{ width: selectedDevice.lastSeenAt ? `${metric.value}%` : '0%' }"></i></div>
            </div>
          </div>
          <div class="dev-trend">
            <span class="faint" style="font-size:12px">活动趋势</span>
            <svg viewBox="0 0 390 43" preserveAspectRatio="none" aria-hidden="true"><polyline :points="sparkline(selectedDevice.activity, 390, 43)" /></svg>
            <span class="faint" style="font-size:12px">最近 14 次心跳</span>
          </div>
        </div>
      </div>
    </section>
  </div>

  <Modal :open="tokenDialog" :title="selectedDevice?.tokenLast4 ? '管理 Device Token' : '生成 Device Token'" description="此令牌只允许这台设备发送心跳。" @close="closeTokenDialog">
    <template v-if="generatedToken">
      <div class="notice warn"><OpusIcon name="alert" /><div>该 Token 仅显示一次，请立即保存。重新生成后旧 Token 立即失效。</div></div>
      <input class="input mono" :value="generatedToken" readonly aria-label="新生成的 Device Token" @focus="($event.target as HTMLInputElement).select()" />
    </template>
    <template v-else>
      <div class="notice"><OpusIcon name="key" /><div>{{ selectedDevice?.tokenLast4 ? `当前 Token：nd_live_••••${selectedDevice.tokenLast4}。重新生成会立即停用旧 Token。` : '生成后请将 Token 保存到客户端配置中。' }}</div></div>
    </template>
    <p v-if="tokenError" class="dlg-error" role="alert">{{ tokenError }}</p>
    <template #footer>
      <template v-if="generatedToken">
        <button class="btn btn-ghost" type="button" @click="copyToken"><OpusIcon name="copy" />复制</button>
        <button class="btn btn-primary" type="button" @click="closeTokenDialog">完成</button>
      </template>
      <template v-else>
        <button v-if="selectedDevice?.tokenLast4" class="btn btn-danger" type="button" :disabled="tokenBusy" @click="revokeToken">撤销 Token</button>
        <button class="btn btn-ghost" type="button" @click="closeTokenDialog">取消</button>
        <button class="btn btn-primary" type="button" :disabled="tokenBusy" @click="generateToken">{{ tokenBusy ? '生成中…' : selectedDevice?.tokenLast4 ? '重新生成' : '生成 Token' }}</button>
      </template>
    </template>
  </Modal>

  <Modal :open="showAddDialog" :title="dialogMode === 'edit' ? '编辑设备' : '添加设备'" description="设备状态由心跳接口提供，不会自动探测地址。" @close="showAddDialog = false">
    <form id="device-editor-form" @submit.prevent="saveDevice">
      <div class="field"><label for="dev-name">设备名称</label><input id="dev-name" v-model="draft.name" class="input" required placeholder="例如：我的笔记本" data-initial-focus /></div>
      <div class="field-grid">
        <div class="field"><label for="dev-sys">操作系统</label><input id="dev-sys" v-model="draft.system" class="input" required placeholder="例如：Windows 11" /></div>
        <div class="field"><label for="dev-ip">IP 地址</label><input id="dev-ip" v-model="draft.ip" class="input" required placeholder="例如：192.168.31.120" /></div>
      </div>
      <div class="field-grid">
        <div class="field"><label for="dev-loc">设备位置</label><input id="dev-loc" v-model="draft.location" class="input" placeholder="例如：书房" /></div>
        <div class="field"><label for="dev-kind">设备类型</label><select id="dev-kind" v-model="draft.kind" class="input"><option value="desktop">台式电脑</option><option value="laptop">笔记本电脑</option><option value="phone">手机</option><option value="tablet">平板电脑</option><option value="server">服务器</option><option value="nas">NAS</option></select></div>
      </div>
      <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
    </form>
    <template #footer>
      <button class="btn btn-ghost" type="button" :disabled="saving" @click="showAddDialog = false">取消</button>
      <button class="btn btn-primary" type="submit" form="device-editor-form" :disabled="saving"><OpusIcon name="check" />{{ saving ? '保存中…' : dialogMode === 'edit' ? '保存修改' : '添加设备' }}</button>
    </template>
  </Modal>
</template>

<style scoped>
.devices-page { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.dev-detail { display: grid; grid-template-columns: minmax(220px, .9fr) minmax(0, 1.1fr); gap: 20px; align-items: start; }
.dev-detail__metrics { padding-left: 20px; border-left: 1px solid var(--line); display: grid; gap: 16px; }
.dev-metrics-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; }
.dev-metric__head { display: flex; justify-content: space-between; font-size: 12.5px; }
.dev-trend { display: flex; align-items: center; gap: 12px; padding-top: 12px; border-top: 1px solid var(--line); }
.dev-trend svg { flex: 1; height: 36px; min-width: 0; }
.dev-trend polyline { fill: none; stroke: var(--accent); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
@media (max-width: 850px) {
  .dev-detail { grid-template-columns: 1fr; }
  .dev-detail__metrics { padding: 16px 0 0; border-left: 0; border-top: 1px solid var(--line); }
}
</style>
