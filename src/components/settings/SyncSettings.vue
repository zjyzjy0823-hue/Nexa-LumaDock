<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { version } from '../../../package.json'
import ActionButton from '../ui/ActionButton.vue'
import Input from '../ui/Input.vue'
import SettingsSection from './SettingsSection.vue'
import ConflictCenter from './ConflictCenter.vue'
import { decideSyncRejected, getSyncRejected, type RejectedEntry } from '../../api/sync'
import { conflictEntityLabel } from '../../services/conflictPresentation'
import { useAuthStore } from '../../stores/auth'
import { desktopPlatform } from '../../desktop/platform'
import { useCoreSync } from '../../composables/useCoreSync'
import { syncErrorMessage, syncStatusDisplay } from '../../services/coreSyncErrors'
import type { CorePlatform } from '../../api/core'

defineOptions({ inheritAttrs: false })
const emit = defineEmits<{ action: [message: string] }>()
const { connection, connectionTest, syncStatus, syncResult, connectionLoading, syncLoading,
  action, busy, connectionError, syncError, refresh, connect, test, disconnect, sync } = useCoreSync(message => emit('action', message))
const platform = desktopPlatform()
const platformLabels: Record<CorePlatform, string> = { windows: 'Windows', macos: 'macOS', linux: 'Linux', android: 'Android', ios: 'iOS', web: 'Web' }
const coreUrl = ref('')
const username = ref('')
const password = ref('')
const clientName = ref(`Studiolo ${platformLabels[platform]}`)
const validationError = ref('')
const conflictsOpen = ref(false)
const testStatus = computed(() => connectionTest.value?.status ?? (connection.value?.connected ? 'connected' : 'disconnected'))
const statusLabels = { connected: '已连接', disconnected: '未连接', unauthorized: '凭证失效', unreachable: '无法访问 Core' }
const syncDisplay = computed(() => syncStatus.value ? syncStatusDisplay(syncStatus.value) : null)
const auth = useAuthStore()
const rejectedEntries = ref<RejectedEntry[]>([])
const rejectedBusy = ref<string | null>(null)

async function loadRejected() {
  if (!auth.token || !syncStatus.value?.rejected) { rejectedEntries.value = []; return }
  try { rejectedEntries.value = await getSyncRejected(auth.token) } catch { rejectedEntries.value = [] }
}

async function decideRejected(entry: RejectedEntry, decision: 'dismiss' | 'retry') {
  if (!auth.token || rejectedBusy.value) return
  rejectedBusy.value = entry.id
  try {
    await decideSyncRejected(auth.token, entry.id, decision)
    emit('action', decision === 'dismiss' ? '已放弃这条被拒绝的写入。' : '已按当前数据重新排队。')
    await refresh(false)
    await loadRejected()
  } catch {
    emit('action', '操作失败，请稍后重试。')
  } finally { rejectedBusy.value = null }
}

watch(() => syncStatus.value?.rejected, () => { void loadRejected() })
onMounted(() => { void loadRejected() })

function formatTime(value: string | null) {
  if (!value) return '尚无成功同步'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间不可用' : date.toLocaleString()
}

async function submitConnection() {
  if (busy.value) return
  validationError.value = ''
  try {
    const url = new URL(coreUrl.value.trim())
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname) throw new Error()
  } catch {
    validationError.value = '请输入有效的 Core HTTP 或 HTTPS 地址'
    return
  }
  if (!username.value.trim() || !password.value || !clientName.value.trim()) {
    validationError.value = '请填写用户名、密码和设备名称'
    return
  }
  const payload = { coreUrl: coreUrl.value.trim(), username: username.value.trim(), password: password.value,
    clientName: clientName.value.trim(), platform, appVersion: version }
  password.value = ''
  try {
    await connect(payload)
  } finally { password.value = '' }
}
onUnmounted(() => { password.value = '' })
</script>

<template>
  <SettingsSection title="同步" description="本地修改立即保存在这台设备，连接 Studiolo Core 后会在后台自动同步。">
    <div class="settings-card" :aria-busy="connectionLoading || (!!action && action !== 'sync')">
      <div class="settings-card__heading">
        <span>Core 连接</span>
        <span v-if="connection" class="conn" :class="testStatus === 'connected' ? 'online' : 'offline'" role="status">{{ statusLabels[testStatus] }}</span>
      </div>
      <p v-if="connectionLoading" class="sync-note" role="status">正在加载连接…</p>
      <div v-if="connectionError || validationError" class="notice danger" role="alert">{{ validationError || connectionError }}</div>

      <template v-if="connection?.connected">
        <dl class="connection-details">
          <dt>Core 地址</dt><dd>{{ connection.coreUrl }}</dd>
          <dt>设备名称</dt><dd>{{ connection.clientName }}</dd>
          <dt>平台</dt><dd>{{ platformLabels[connection.platform] }}</dd>
          <dt>客户端版本</dt><dd>{{ connection.appVersion }}</dd>
          <dt>连接时间</dt><dd>{{ formatTime(connection.connectedAt) }}</dd>
        </dl>
        <details class="technical-details"><summary>技术信息</summary>
          <dl class="connection-details">
            <dt>Client ID</dt><dd class="mono">{{ connection.clientId }}</dd>
            <dt>Installation ID</dt><dd class="mono">{{ connection.installationId }}</dd>
            <dt>Workspace ID</dt><dd class="mono">{{ connection.workspaceId }}</dd>
          </dl>
        </details>
        <p v-if="connectionTest" class="sync-note" role="status">{{ { connected: '连接正常', disconnected: '尚未连接', unreachable: '无法访问 Core，请检查服务和网络。', unauthorized: 'Client 凭证无效，需要重新连接或修复。当前版本不支持自动修复。' }[connectionTest.status] }}</p>
        <div class="settings-button-row">
          <ActionButton variant="secondary" :disabled="busy" @click="test">{{ action === 'test' ? '测试中…' : '测试连接' }}</ActionButton>
          <ActionButton variant="danger" :disabled="busy" @click="disconnect">{{ action === 'disconnect' ? '断开中…' : '断开连接' }}</ActionButton>
        </div>
      </template>

      <form v-else-if="connection && !connectionLoading" autocomplete="off" @submit.prevent="submitConnection">
        <div class="settings-field-grid">
          <label class="settings-field"><span>Core 地址</span><Input v-model="coreUrl" type="url" aria-label="Core 地址" placeholder="https://core.example.com" :disabled="busy" required /></label>
          <label class="settings-field"><span>设备名称</span><Input v-model="clientName" aria-label="设备名称" :maxlength="120" :disabled="busy" required /></label>
          <label class="settings-field"><span>用户名</span><Input v-model="username" aria-label="Core 用户名" autocomplete="off" :disabled="busy" required /></label>
          <label class="settings-field"><span>密码</span><Input v-model="password" type="password" aria-label="Core 密码" autocomplete="off" :disabled="busy" required /></label>
        </div>
        <p class="sync-note">可信局域网开发环境可使用 HTTP，例如 http://192.168.1.50:8000。密码仅用于本次连接，不会保存。</p>
        <div class="settings-button-row"><ActionButton type="submit" :disabled="busy">{{ action === 'connect' ? '连接中…' : '连接 Core' }}</ActionButton></div>
      </form>
      <div class="settings-button-row"><ActionButton variant="ghost" :disabled="busy" @click="refresh()"><RefreshCw :size="14" />刷新状态</ActionButton></div>
    </div>

    <div class="settings-card" :aria-busy="syncLoading || action === 'sync' || syncStatus?.running">
      <div class="settings-card__heading"><span>数据同步</span><small>后台自动同步</small></div>
      <p v-if="syncLoading" class="sync-note" role="status">正在加载同步状态…</p>
      <div v-if="syncError" class="notice danger" role="alert">{{ syncError }}</div>
      <template v-if="syncStatus">
        <div v-if="syncDisplay" class="auto-sync-status" :class="`auto-sync-status--${syncDisplay.tone}`" role="status">
          <RefreshCw v-if="syncStatus.running" :size="15" class="sync-spin" aria-hidden="true" />
          <i v-else aria-hidden="true" />
          <button v-if="syncStatus.conflicts > 0" type="button" class="sync-conflict-status" @click="conflictsOpen = true"><strong>{{ syncDisplay.label }}</strong><span>{{ syncDisplay.detail }} · 查看冲突</span></button>
          <div v-else><strong>{{ syncDisplay.label }}</strong><p>{{ syncDisplay.detail }}</p></div>
        </div>
        <dl class="sync-counts">
          <div><dt>待同步</dt><dd class="count-pending num">{{ syncStatus.pending }}</dd></div>
          <div><dt>冲突</dt><dd class="num" :class="{ 'count-warning': syncStatus.conflicts > 0 }"><button v-if="syncStatus.conflicts > 0" class="sync-conflict-count" type="button" :aria-label="`查看 ${syncStatus.conflicts} 个同步冲突`" @click="conflictsOpen = true">{{ syncStatus.conflicts }}</button><template v-else>{{ syncStatus.conflicts }}</template></dd></div>
          <div><dt>处理中</dt><dd class="num">{{ syncStatus.inFlight }}</dd></div>
          <div><dt>已拒绝</dt><dd class="num" :class="{ 'count-warning': syncStatus.rejected > 0 }">{{ syncStatus.rejected }}</dd></div>
        </dl>
        <dl class="connection-details sync-details">
          <dt>Cursor</dt><dd class="mono">{{ syncStatus.cursor }}</dd>
          <dt>上次成功同步</dt><dd>{{ formatTime(syncStatus.lastSuccessAt) }}</dd>
          <template v-if="syncStatus.nextRetryAt && !syncStatus.blocked"><dt>下次自动重试</dt><dd>{{ formatTime(syncStatus.nextRetryAt) }}</dd></template>
          <dt>最后错误</dt><dd :class="{ 'sync-error': syncStatus.lastError }">{{ syncStatus.lastError ? syncErrorMessage(syncStatus.lastError) : '无' }}</dd>
        </dl>
        <div v-if="syncStatus.conflicts > 0" class="settings-button-row"><ActionButton variant="secondary" @click="conflictsOpen = true">同步冲突 {{ syncStatus.conflicts }} · 查看并处理</ActionButton></div>
      </template>
      <p v-if="connection && !connection.connected" class="sync-note">未连接 Core。本地修改已安全保存。连接 Core 后可以同步到其他设备。</p>
      <p v-if="syncResult" class="sync-result" :class="{ 'sync-error': syncResult.status === 'error' }" role="status">
        {{ syncResult.status === 'ok' ? '同步完成' : '同步未完成' }}：上传 {{ syncResult.pushed }} 项，接收 {{ syncResult.pulled }} 项。
        <span v-if="syncResult.status === 'error'">{{ syncErrorMessage(syncResult.lastError) }}</span>
      </p>
      <div class="settings-button-row sync-actions"><ActionButton :disabled="busy || !connection?.connected || !syncStatus || !!connectionError" @click="sync"><RefreshCw :size="15" :class="{ 'sync-spin': action === 'sync' || syncStatus?.running }" />{{ action === 'sync' ? '正在同步…' : '立即同步' }}</ActionButton></div>
    </div>

    <div v-if="rejectedEntries.length" class="settings-card">
      <div class="settings-card__heading"><span>被拒绝的写入</span><small>{{ rejectedEntries.length }} 条</small></div>
      <p class="sync-note" style="margin-top:0">Core 拒绝了这些改动。可以放弃，或修正数据后按当前内容重新提交。</p>
      <ul class="sync-rejected-list">
        <li v-for="entry in rejectedEntries" :key="entry.id">
          <div><strong>{{ conflictEntityLabel(entry.entityType) }}</strong><span>{{ entry.reason || '未知原因' }} · {{ entry.operation === 'delete' ? '删除' : '写入' }}</span></div>
          <div class="btn-row">
            <ActionButton variant="secondary" size="sm" :disabled="!!rejectedBusy" @click="decideRejected(entry, 'dismiss')">放弃</ActionButton>
            <ActionButton size="sm" :disabled="!!rejectedBusy" @click="decideRejected(entry, 'retry')">重试</ActionButton>
          </div>
        </li>
      </ul>
    </div>
  </SettingsSection>
  <ConflictCenter :open="conflictsOpen" :refresh-status="() => refresh(false)" @close="conflictsOpen = false" @action="message => emit('action', message)" />
</template>

<style scoped>
.sync-error, .count-warning { color: var(--danger); }
.connection-details { display: grid; grid-template-columns: minmax(90px, auto) minmax(0, 1fr); gap: 8px 16px; margin: 0; font-size: 13px; line-height: 1.5; }
.connection-details dt { color: var(--text-3); }
.connection-details dd { margin: 0; overflow-wrap: anywhere; color: var(--text); }
.technical-details { margin-top: 12px; font-size: 12px; color: var(--text-3); }
.technical-details summary { cursor: pointer; }
.technical-details .connection-details { margin-top: 10px; font-size: 12px; }
.sync-note, .sync-error, .sync-result { margin: 10px 0; font-size: 12.5px; line-height: 1.55; overflow-wrap: anywhere; }
.sync-note { color: var(--text-2); }
.auto-sync-status { display: flex; align-items: flex-start; gap: 10px; margin: 0 0 14px; color: var(--text-2); }
.auto-sync-status > i { width: 7px; height: 7px; flex: 0 0 7px; margin-top: 6px; border-radius: 50%; background: currentColor; }
.auto-sync-status > svg { flex-shrink: 0; margin-top: 2px; }
.auto-sync-status strong { font-size: 13.5px; }
.auto-sync-status p { margin: 2px 0 0; color: var(--text-2); font-size: 12.5px; line-height: 1.5; }
.auto-sync-status--success { color: var(--ok); }
.auto-sync-status--active { color: var(--accent); }
.auto-sync-status--warning { color: var(--danger); }
.sync-conflict-status { display: block; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; }
.sync-conflict-status span { display: block; margin-top: 2px; font-size: 12.5px; }
.sync-conflict-status:hover span { text-decoration: underline; }
.sync-conflict-count { padding: 0; border: 0; color: inherit; background: transparent; font: inherit; }
.sync-counts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0 0 16px; }
.sync-counts div { padding: 10px 12px; border-radius: var(--r-md); background: var(--surface-3); }
.sync-counts dt { color: var(--text-3); font-size: 12px; }
.sync-counts dd { margin: 4px 0 0; font-size: 20px; font-weight: 700; }
.count-pending { color: var(--accent); }
.sync-actions { justify-content: flex-end; }
.sync-spin { animation: spin 1s linear infinite; }
.sync-rejected-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.sync-rejected-list li { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border-radius: var(--r-md); background: var(--surface-3); font-size: 12.5px; }
.sync-rejected-list li strong { display: block; font-size: 13px; }
.sync-rejected-list li span { color: var(--text-3); }
@media (max-width: 560px) { .sync-counts { grid-template-columns: repeat(2, minmax(0, 1fr)); } .connection-details { grid-template-columns: 80px minmax(0, 1fr); gap: 8px; } }
[data-motion="reduced"] .sync-spin { animation: none; }
</style>
