<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { version } from '../../../package.json'
import ActionButton from '../ui/ActionButton.vue'
import Input from '../ui/Input.vue'
import SettingsSection from './SettingsSection.vue'
import { desktopPlatform } from '../../desktop/platform'
import { useCoreSync } from '../../composables/useCoreSync'
import { syncErrorMessage } from '../../services/coreSyncErrors'
import type { CorePlatform } from '../../api/core'

const emit = defineEmits<{ action: [message: string] }>()
const { connection, connectionTest, syncStatus, syncResult, connectionLoading, syncLoading,
  action, busy, connectionError, syncError, refresh, connect, test, disconnect, sync } = useCoreSync(message => emit('action', message))
const platform = desktopPlatform()
const platformLabels: Record<CorePlatform, string> = { windows: 'Windows', macos: 'macOS', linux: 'Linux', android: 'Android', ios: 'iOS', web: 'Web' }
const coreUrl = ref('')
const username = ref('')
const password = ref('')
const clientName = ref(`Nexa ${platformLabels[platform]}`)
const validationError = ref('')
const testStatus = computed(() => connectionTest.value?.status ?? (connection.value?.connected ? 'connected' : 'disconnected'))
const statusLabels = { connected: '已连接', disconnected: '未连接', unauthorized: '凭证失效', unreachable: '无法访问 Core' }

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
  <SettingsSection title="同步" description="本地修改先保存在这台设备，连接 Nexa Core 后可手动同步。">
    <div class="settings-card" :aria-busy="connectionLoading || (!!action && action !== 'sync')">
      <div class="settings-card__heading">
        <span>Core 连接</span>
        <span v-if="connection" class="core-status" :class="`core-status--${testStatus}`" role="status"><i aria-hidden="true" />{{ statusLabels[testStatus] }}</span>
      </div>
      <p v-if="connectionLoading" class="sync-note" role="status">正在加载连接…</p>
      <p v-if="connectionError || validationError" class="sync-error" role="alert">{{ validationError || connectionError }}</p>

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
            <dt>Client ID</dt><dd>{{ connection.clientId }}</dd>
            <dt>Installation ID</dt><dd>{{ connection.installationId }}</dd>
            <dt>Workspace ID</dt><dd>{{ connection.workspaceId }}</dd>
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

    <div class="settings-card" :aria-busy="syncLoading || action === 'sync'">
      <div class="settings-card__heading"><span>数据同步</span><small>手动同步</small></div>
      <p v-if="syncLoading" class="sync-note" role="status">正在加载同步状态…</p>
      <p v-if="syncError" class="sync-error" role="alert">{{ syncError }}</p>
      <template v-if="syncStatus">
        <dl class="sync-counts">
          <div><dt>待同步</dt><dd class="count-pending">{{ syncStatus.pending }}</dd></div>
          <div><dt>冲突</dt><dd :class="{ 'count-warning': syncStatus.conflicts > 0 }">{{ syncStatus.conflicts }}</dd></div>
          <div><dt>处理中</dt><dd>{{ syncStatus.inFlight }}</dd></div>
          <div><dt>已拒绝</dt><dd :class="{ 'count-warning': syncStatus.rejected > 0 }">{{ syncStatus.rejected }}</dd></div>
        </dl>
        <dl class="connection-details sync-details">
          <dt>Cursor</dt><dd>{{ syncStatus.cursor }}</dd>
          <dt>上次成功同步</dt><dd>{{ formatTime(syncStatus.lastSuccessAt) }}</dd>
          <dt>最后错误</dt><dd :class="{ 'sync-error': syncStatus.lastError }">{{ syncStatus.lastError ? syncErrorMessage(syncStatus.lastError) : '无' }}</dd>
        </dl>
        <p v-if="syncStatus.conflicts > 0" class="sync-note count-warning">存在 {{ syncStatus.conflicts }} 个同步冲突，当前版本暂不支持在界面解决。</p>
      </template>
      <p v-if="connection && !connection.connected" class="sync-note">未连接 Core。本地修改已安全保存。连接 Core 后可以同步到其他设备。</p>
      <p v-if="syncResult" class="sync-result" :class="{ 'sync-error': syncResult.status === 'error' }" role="status">
        {{ syncResult.status === 'ok' ? '同步完成' : '同步未完成' }}：上传 {{ syncResult.pushed }} 项，接收 {{ syncResult.pulled }} 项。
        <span v-if="syncResult.status === 'error'">{{ syncErrorMessage(syncResult.lastError) }}</span>
      </p>
      <div class="settings-button-row sync-actions"><ActionButton :disabled="busy || !connection?.connected || !syncStatus || !!connectionError" @click="sync"><RefreshCw :size="15" :class="{ 'sync-spin': action === 'sync' }" />{{ action === 'sync' ? '正在同步…' : '立即同步' }}</ActionButton></div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.core-status { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 11px; font-weight: 670; }
.core-status i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.core-status--connected { color: #29846f; }
.core-status--unauthorized, .core-status--unreachable, .sync-error, .count-warning { color: #b14e65; }
.connection-details { display: grid; grid-template-columns: minmax(90px, auto) minmax(0, 1fr); gap: 10px 18px; margin: 0; font-size: 12px; line-height: 1.5; }
.connection-details dt { color: var(--text-secondary); }
.connection-details dd { margin: 0; overflow-wrap: anywhere; color: var(--text-primary); }
.technical-details { margin-top: 15px; font-size: 11px; color: var(--text-secondary); }
.technical-details summary { cursor: pointer; }
.technical-details .connection-details { margin-top: 12px; font-size: 11px; }
.sync-note, .sync-error, .sync-result { margin: 12px 0; font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
.sync-note { color: var(--text-secondary); }
.sync-counts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 20px; }
.sync-counts div { padding: 12px; border: 1px solid var(--line); border-radius: 11px; background: var(--glass-tile-background); }
.sync-counts dt { color: var(--text-secondary); font-size: 11px; }
.sync-counts dd { margin: 6px 0 0; font-size: 22px; font-weight: 700; }
.count-pending { color: var(--accent-deep); }
.sync-details .sync-error { color: #b14e65; }
.sync-actions { justify-content: flex-end; }
.sync-spin { animation: sync-rotate 1s linear infinite; }
@keyframes sync-rotate { to { transform: rotate(360deg); } }
@media (max-width: 560px) { .sync-counts { grid-template-columns: repeat(2, minmax(0, 1fr)); } .connection-details { grid-template-columns: 80px minmax(0, 1fr); gap: 10px; } }
@media (prefers-reduced-motion: reduce) { .sync-spin { animation: none; } }
</style>
