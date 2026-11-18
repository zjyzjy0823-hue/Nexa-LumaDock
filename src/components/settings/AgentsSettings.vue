<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAgentsStore } from '../../stores/agents'
import { useAuthStore } from '../../stores/auth'
import { useFleetStore } from '../../stores/fleet'
import type { NodePlatform } from '../../types/fleet'
import { getPlatformIcon } from '../chat/providerMeta'
import OpusIcon from '../ui/OpusIcon.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'

const emit = defineEmits<{ navigate: [page: string]; action: [message: string] }>()
const auth = useAuthStore()
const agentsStore = useAgentsStore()
const fleet = useFleetStore()

const showCreate = ref(false)
const newName = ref('')
const newPlatform = ref<NodePlatform>('macos')
const creating = ref(false)
const issuedToken = ref<{ nodeName: string; nodeToken: string } | null>(null)

onMounted(() => {
  if (auth.token && !agentsStore.agents.length && !agentsStore.loading) {
    void agentsStore.load(auth.token).catch(() => {})
  }
  if (auth.token) {
    void fleet.loadNodes()
    fleet.connectSocket()
  }
})

const runningCount = computed(() => agentsStore.agents.filter(item => item.status === 'running').length)

async function createNode() {
  const clean = newName.value.trim()
  if (!clean || creating.value) return
  creating.value = true
  try {
    const res = await fleet.registerNode({ name: clean, platform: newPlatform.value })
    issuedToken.value = { nodeName: res.node.name, nodeToken: res.nodeToken }
    newName.value = ''
    showCreate.value = false
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '注册节点失败')
  } finally {
    creating.value = false
  }
}

async function rotateToken(nodeId: string) {
  try {
    const res = await fleet.rotateNode(nodeId)
    issuedToken.value = { nodeName: res.node.name, nodeToken: res.nodeToken }
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '轮换节点凭证失败')
  }
}

async function revokeToken(nodeId: string) {
  try {
    await fleet.revokeNode(nodeId)
    emit('action', '已吊销该节点凭证并断开其连接')
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '吊销节点失败')
  }
}

async function removeNode(nodeId: string) {
  try {
    await fleet.removeNode(nodeId)
    emit('action', '已删除控制节点')
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '删除节点失败')
  }
}

async function copyText(text: string, tip: string) {
  try {
    await navigator.clipboard.writeText(text)
    emit('action', tip)
  } catch {
    emit('action', '请手动复制上方文本框中的凭证')
  }
}
</script>

<template>
  <SettingsSection title="Agent 与连接" description="管理已绑定的本地 Data Actions 代理，以及多设备 Agent Fleet 控制节点（sn_live_）。">
    <div class="settings-card settings-card--rows">
      <div class="settings-card__heading" style="padding:14px 16px;margin:0;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px">
        <div style="flex:1;min-width:0">
          <span>Agent Fleet 控制节点（sn_live_）</span>
          <small style="display:block">支持从 Mac / Windows / Linux 宿主机接入 Codex、OpenCode、Hermes、Antigravity、DSH 与 OpenClaw，聊天与文件明文不在 Core 落盘</small>
        </div>
        <button type="button" class="btn btn-primary btn-sm" @click="showCreate = true"><OpusIcon name="plus" />新增节点</button>
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('navigate', 'Chat')">进入协同终端</button>
      </div>

      <SettingRow
        v-for="node in fleet.nodes"
        :key="node.id"
        :label="`${node.name} (${node.platform})`"
        :description="`凭证末四位 ${node.tokenLast4 || '已吊销'} · 允许目录 ${node.allowedRoots.length} 个 · 适配器 ${node.adapters.filter(a => a.status === 'ready').length}/${node.adapters.length}`"
      >
        <div class="node-ops">
          <span class="conn" :class="node.status === 'online' ? 'online' : 'offline'">
            {{ node.status === 'online' ? '在线' : node.status === 'revoked' ? '已吊销' : '离线' }}
          </span>
          <OpusIcon :name="getPlatformIcon(node.platform)" style="width:14px;height:14px;color:var(--text-3)" />
          <button type="button" class="btn btn-ghost btn-sm" @click="rotateToken(node.id)">轮换</button>
          <button v-if="node.status !== 'revoked'" type="button" class="btn btn-ghost btn-sm" @click="revokeToken(node.id)">吊销</button>
          <button type="button" class="btn btn-danger btn-sm" @click="removeNode(node.id)">删除</button>
        </div>
      </SettingRow>

      <div v-if="!fleet.nodes.length" style="padding:16px;font-size:12.5px;color:var(--text-3)">
        尚未登记任何 Fleet 节点。点击右上角「新增节点」获取一次性 `sn_live_` 启动凭证。
      </div>
    </div>

    <div class="settings-card settings-card--rows">
      <SettingRow label="本地 Agent 运行时（na_live_）" :description="`已登记 ${agentsStore.agents.length} 个身份 · 运行中 ${runningCount} 个 · 用于任务派发与 Data Actions`">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('navigate', 'Agents')">前往 Agent 配置</button>
      </SettingRow>
      <SettingRow label="新建智能体或令牌" description="在配置页发放或撤销 na_live_ 凭证，并管理数据作用域">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('navigate', 'Agents')"><OpusIcon name="settings" />打开管理</button>
      </SettingRow>
    </div>

    <!-- 新建 Fleet 节点弹窗 -->
    <div v-if="showCreate" class="fleet-modal-scrim" @click.self="showCreate = false">
      <div class="fleet-modal card">
        <h3>新增 Fleet 控制节点</h3>
        <div class="field">
          <label>节点名称</label>
          <input v-model="newName" class="input" placeholder="例如 Mac-Studio / Win-Workstation" @keyup.enter="createNode" />
        </div>
        <div class="field">
          <label>操作系统平台</label>
          <select v-model="newPlatform" class="input">
            <option value="macos">macOS</option>
            <option value="windows">Windows</option>
            <option value="linux">Linux</option>
          </select>
        </div>
        <div class="fleet-modal-foot">
          <button type="button" class="btn btn-ghost" @click="showCreate = false">取消</button>
          <button type="button" class="btn btn-primary" :disabled="creating || !newName.trim()" @click="createNode">生成凭证</button>
        </div>
      </div>
    </div>

    <!-- 一次性显示 sn_live_ 凭证 -->
    <div v-if="issuedToken" class="fleet-modal-scrim" @click.self="issuedToken = null">
      <div class="fleet-modal card">
        <h3>节点凭证已生成（仅展示这一次）</h3>
        <p class="faint" style="margin:0;font-size:12.5px">请保存 <b>{{ issuedToken.nodeName }}</b> 的独立节点凭证，服务端仅存哈希，关闭弹窗后无法再次查看明文。</p>
        <code class="token-box">{{ issuedToken.nodeToken }}</code>
        <code class="cmd-box">STUDIOLO_NODE_TOKEN={{ issuedToken.nodeToken }} python -m agent_node --config config.json</code>
        <div class="fleet-modal-foot">
          <button type="button" class="btn btn-ghost" @click="copyText(issuedToken.nodeToken, '已复制 sn_live_ 凭证')"><OpusIcon name="copy" />复制 Token</button>
          <button type="button" class="btn btn-primary" @click="issuedToken = null">我已妥善保存</button>
        </div>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.node-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fleet-modal-scrim {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: grid;
  place-items: center;
  background: var(--scrim);
  padding: 20px;
}
.fleet-modal {
  width: min(460px, 100%);
  display: grid;
  gap: 12px;
  background: var(--solid);
  box-shadow: var(--shadow-pop);
}
.fleet-modal h3 { margin: 0; font-size: 16px; }
.fleet-modal-foot { display: flex; justify-content: flex-end; gap: 8px; }
.token-box,
.cmd-box {
  display: block;
  padding: 9px 10px;
  border-radius: var(--r-sm);
  background: var(--surface-2);
  font-size: 12px;
  word-break: break-all;
}
</style>
