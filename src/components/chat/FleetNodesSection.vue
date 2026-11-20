<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { confirmAction } from '../../composables/useConfirm'
import { useCopyFeedback } from '../../composables/useCopyFeedback'
import { resolveSavedModelPref } from '../../services/modelPrefs'
import { useAuthStore } from '../../stores/auth'
import { sessionKey, useFleetStore } from '../../stores/fleet'
import type { AdapterInfo, AdapterProvider, AgentNode, NodePlatform } from '../../types/fleet'
import Modal from '../ui/Modal.vue'
import OpusIcon from '../ui/OpusIcon.vue'
import FleetCoreSignIn from './FleetCoreSignIn.vue'
import { getPlatformIcon, getProviderMeta } from './providerMeta'

defineProps<{
  mobile?: boolean
  embeddedInSettings?: boolean
}>()

const emit = defineEmits<{
  navigate: [page: string]
  action: [message: string]
}>()

const auth = useAuthStore()
const fleet = useFleetStore()

const showCreate = ref(false)
const newName = ref('')
const newPlatform = ref<NodePlatform>('macos')
const creating = ref(false)
const issuedToken = ref<{ nodeName: string; nodeToken: string } | null>(null)
const prefRevision = ref(0)

onMounted(() => {
  if (auth.token) {
    void fleet.loadNodes()
    fleet.connectSocket()
  }
})

function openCreateModal() {
  if (fleet.coreSignInUrl) return
  newName.value = ''
  showCreate.value = true
}

defineExpose({ openCreateModal })

function sortedAdapters(node: AgentNode): AdapterInfo[] {
  const rank = (s: AdapterInfo['status']) => (s === 'ready' ? 0 : s === 'unavailable' ? 1 : 2)
  return [...node.adapters].sort((a, b) => rank(a.status) - rank(b.status))
}

function adapterStatusText(status: AdapterInfo['status']): string {
  if (status === 'ready') return '已就绪'
  if (status === 'error') return '异常'
  return '未安装'
}

function savedModelLabel(nodeId: string, provider: AdapterProvider): string {
  void prefRevision.value
  const pref = resolveSavedModelPref(nodeId, provider)
  if (!pref?.model) return ''
  return pref.effort ? `${pref.model} · ${pref.effort}` : pref.model
}

function sessionCountFor(nodeId: string, provider: AdapterProvider): number {
  return fleet.allSessions.filter(s => s.nodeId === nodeId && s.provider === provider).length
}

function openChatWith(nodeId: string, provider?: AdapterProvider) {
  fleet.selectNode(nodeId)
  if (provider) {
    fleet.selectProvider(provider)
    const match = fleet.allSessions.find(s => s.nodeId === nodeId && s.provider === provider)
    if (match) {
      fleet.activateSession(sessionKey(match.nodeId, match.provider, match.sessionId))
    }
  }
  emit('navigate', 'Chat')
}

function clearSavedPref(nodeId: string, provider: AdapterProvider) {
  fleet.setModelPreference(nodeId, provider, '', undefined)
  prefRevision.value += 1
  emit('action', `已重置 ${getProviderMeta(provider).label} 默认模型偏好`)
}

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

async function rotateToken(node: AgentNode) {
  try {
    const res = await fleet.rotateNode(node.id)
    issuedToken.value = { nodeName: res.node.name, nodeToken: res.nodeToken }
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '轮换节点凭证失败')
  }
}

async function revokeToken(node: AgentNode) {
  if (!(await confirmAction(`吊销控制节点「${node.name}」的凭证并断开连接？`))) return
  try {
    await fleet.revokeNode(node.id)
    emit('action', '已吊销该节点凭证并断开其连接')
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '吊销节点失败')
  }
}

async function removeNode(node: AgentNode) {
  if (!(await confirmAction(`删除控制节点「${node.name}」及其注册记录？`))) return
  try {
    await fleet.removeNode(node.id)
    emit('action', '已删除控制节点')
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '删除节点失败')
  }
}

const { copy: copyWithFeedback, isCopied } = useCopyFeedback()

async function copyText(text: string, tip: string, key = 'node-token') {
  const ok = await copyWithFeedback(text, key)
  if (ok) {
    emit('action', tip)
  } else {
    emit('action', '请手动复制文本框中的内容')
  }
}

const totalReadyAdapters = computed(() =>
  fleet.nodes.reduce((sum, n) => sum + n.adapters.filter(a => a.status === 'ready').length, 0),
)
</script>

<template>
  <section class="fleet-sec" :class="{ 'is-settings': embeddedInSettings, 'is-mobile': mobile }">
    <FleetCoreSignIn v-if="fleet.coreSignInUrl" />
    <template v-else>
    <div class="card mat fleet-panel">
      <header class="fleet-panel-head">
        <div class="fleet-panel-title-wrap">
          <div class="fleet-panel-title">
            <OpusIcon name="server" class="fph-ic" />
            <h3>已接入对话节点与智能体（{{ fleet.nodes.length }} 节点 · {{ totalReadyAdapters }} 就绪引擎）</h3>
          </div>
          <p class="faint fleet-panel-sub">
            展示在协同对话中可调用的主机控制节点（sn_live_）及各节点上已配置的 CLI / 代理智能体与默认模型记忆。
          </p>
        </div>
        <div class="fleet-panel-actions">
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            title="刷新控制节点与引擎在线状态"
            @click="fleet.loadNodes(); fleet.connectSocket()"
          >
            <OpusIcon name="sync" />
            <span>刷新</span>
          </button>
          <button type="button" class="btn btn-primary btn-sm" @click="openCreateModal">
            <OpusIcon name="plus" />
            <span>新增控制节点</span>
          </button>
        </div>
      </header>

      <div v-if="!fleet.nodes.length" class="fleet-empty">
        <OpusIcon name="server" class="fleet-empty-ic" />
        <p class="faint">
          尚未添加任何对话控制节点。点击右上角「新增控制节点」获取一次性 <code>sn_live_</code> 凭证并在目标机器启动守护进程，即可自动识别并展示可用的智能体。
        </p>
      </div>

      <div v-else class="fleet-nodes-list">
        <article v-for="node in fleet.nodes" :key="node.id" class="fleet-node-card">
          <div class="fleet-node-top">
            <div class="fleet-node-id">
              <span class="fleet-node-ic">
                <OpusIcon :name="getPlatformIcon(node.platform)" />
              </span>
              <div class="fleet-node-meta">
                <div class="fleet-node-name-row">
                  <strong>{{ node.name }}</strong>
                  <span class="conn" :class="node.status === 'online' ? 'online' : 'offline'">
                    {{ node.status === 'online' ? '在线' : node.status === 'revoked' ? '已吊销' : '离线' }}
                  </span>
                  <span class="fn-chip num">{{ node.platform }}{{ node.hostname ? ` · ${node.hostname}` : '' }}</span>
                </div>
                <div class="faint fleet-node-sub">
                  <span>凭证：<code>{{ node.tokenLast4 ? `sn_live_••••${node.tokenLast4}` : '已吊销' }}</code></span>
                  <span>·</span>
                  <span>就绪智能体 {{ node.adapters.filter(a => a.status === 'ready').length }}/{{ node.adapters.length }}</span>
                  <template v-if="node.allowedRoots.length">
                    <span>·</span>
                    <span class="fn-roots" :title="node.allowedRoots.join('\n')">允许目录 {{ node.allowedRoots.length }} 个（{{ node.allowedRoots[0] }}）</span>
                  </template>
                </div>
              </div>
            </div>

            <div class="fleet-node-ops">
              <button type="button" class="btn btn-subtle btn-sm" @click="openChatWith(node.id)">
                <OpusIcon name="chat" />
                <span>对话</span>
              </button>
              <button type="button" class="btn btn-ghost btn-sm" @click="rotateToken(node)">轮换凭证</button>
              <button v-if="node.status !== 'revoked'" type="button" class="btn btn-ghost btn-sm" @click="revokeToken(node)">吊销</button>
              <button type="button" class="btn btn-danger btn-sm" @click="removeNode(node)">删除</button>
            </div>
          </div>

          <!-- 该节点下挂载的每一个对话智能体引擎 -->
          <div v-if="node.adapters.length" class="fleet-adapters-grid">
            <div
              v-for="ad in sortedAdapters(node)"
              :key="`${node.id}-${ad.provider}`"
              class="adapter-card"
              :class="[`is-${ad.status}`]"
            >
              <div class="adapter-card-head">
                <span class="adapter-ic" :class="getProviderMeta(ad.provider).accentClass">
                  <OpusIcon :name="getProviderMeta(ad.provider).icon" />
                </span>
                <div class="adapter-copy">
                  <div class="adapter-title-row">
                    <span class="adapter-name">{{ getProviderMeta(ad.provider).label }}</span>
                    <span class="adapter-badge" :class="`is-${ad.status}`">{{ adapterStatusText(ad.status) }}</span>
                    <span v-if="sessionCountFor(node.id, ad.provider)" class="adapter-sess num">
                      {{ sessionCountFor(node.id, ad.provider) }} 会话
                    </span>
                  </div>
                  <div class="faint adapter-desc">
                    {{ ad.version ? `${ad.version} · ` : '' }}{{ getProviderMeta(ad.provider).shortDesc }}
                  </div>
                </div>
              </div>

              <div v-if="ad.capabilities.length && ad.status === 'ready'" class="adapter-caps">
                <span v-for="cap in ad.capabilities.slice(0, 4)" :key="cap" class="adapter-cap-chip">{{ cap }}</span>
              </div>

              <div class="adapter-foot">
                <div v-if="savedModelLabel(node.id, ad.provider)" class="adapter-pref">
                  <span class="ap-lbl">默认模型：</span>
                  <code class="ap-val" :title="savedModelLabel(node.id, ad.provider)">{{ savedModelLabel(node.id, ad.provider) }}</code>
                  <button
                    type="button"
                    class="ap-clear"
                    title="清除记住的默认模型，恢复由节点决定"
                    @click="clearSavedPref(node.id, ad.provider)"
                  >×</button>
                </div>
                <span v-else class="faint adapter-pref-empty">跟随节点默认模型</span>

                <button
                  v-if="ad.status === 'ready'"
                  type="button"
                  class="btn btn-subtle btn-sm adapter-chat-btn"
                  @click="openChatWith(node.id, ad.provider)"
                >
                  <OpusIcon name="send" />
                  <span>使用对话</span>
                </button>
              </div>
            </div>
          </div>
          <p v-else class="faint fleet-no-adapters">
            {{ node.status === 'online' ? '节点暂未上报可用智能体适配器。' : '节点当前离线；接入启动后将自动汇报该机器上安装的 Codex / OpenCode / Hermes 等智能体列表。' }}
          </p>
        </article>
      </div>
    </div>

    <Modal
      :open="showCreate"
      title="新增 Fleet 控制节点"
      description="生成一次性 sn_live_ 启动凭证，用于将主机上的 Agent 运行时安全接入协同对话。"
      @close="showCreate = false"
    >
      <form id="fleet-node-create-form" @submit.prevent="createNode">
        <div class="field">
          <label for="fn-name">节点名称</label>
          <input
            id="fn-name"
            v-model="newName"
            class="input"
            required
            placeholder="例如 Mac-Studio / Win-Workstation"
            data-initial-focus
          />
        </div>
        <div class="field">
          <label for="fn-platform">操作系统平台</label>
          <select id="fn-platform" v-model="newPlatform" class="input">
            <option value="macos">macOS</option>
            <option value="windows">Windows</option>
            <option value="linux">Linux</option>
          </select>
        </div>
      </form>
      <template #footer>
        <button type="button" class="btn btn-ghost" @click="showCreate = false">取消</button>
        <button
          type="submit"
          form="fleet-node-create-form"
          class="btn btn-primary"
          :disabled="creating || !newName.trim()"
        >{{ creating ? '生成中…' : '生成凭证' }}</button>
      </template>
    </Modal>

    <Modal
      :open="Boolean(issuedToken)"
      title="节点凭证已生成（仅展示这一次）"
      description="服务端仅保存凭证哈希，关闭后无法再次查看明文，请立即复制保存。"
      @close="issuedToken = null"
    >
      <div v-if="issuedToken" class="issued-token-body">
        <div class="faint" style="font-size:12.5px">节点 <b>{{ issuedToken.nodeName }}</b> 的独立凭证：</div>
        <code class="token-box">{{ issuedToken.nodeToken }}</code>
        <code class="cmd-box">STUDIOLO_NODE_TOKEN={{ issuedToken.nodeToken }} python -m agent_node --config config.json</code>
      </div>
      <template #footer>
        <button
          v-if="issuedToken"
          type="button"
          class="btn btn-ghost"
          :class="{ 'is-copied': isCopied('node-token') }"
          @click="copyText(issuedToken.nodeToken, '已复制 sn_live_ 凭证', 'node-token')"
        ><OpusIcon :name="isCopied('node-token') ? 'check' : 'copy'" />{{ isCopied('node-token') ? '已复制' : '复制 Token' }}</button>
        <button type="button" class="btn btn-primary" @click="issuedToken = null">我已妥善保存</button>
      </template>
    </Modal>
    </template>
  </section>
</template>

<style scoped>
.fleet-sec {
  margin-bottom: 16px;
}
.fleet-sec.is-settings {
  margin-bottom: 14px;
}
.fleet-panel {
  display: grid;
  gap: 14px;
  padding: 16px;
}
.fleet-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.fleet-panel-title-wrap {
  flex: 1;
  min-width: 240px;
}
.fleet-panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fleet-panel-title h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}
.fph-ic {
  width: 17px;
  height: 17px;
  color: var(--accent);
}
.fleet-panel-sub {
  margin: 4px 0 0;
  font-size: 12.5px;
}
.fleet-panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.fleet-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  font-size: 13px;
}
.fleet-empty p { margin: 0; }
.fleet-empty-ic { width: 20px; height: 20px; color: var(--text-3); flex: none; }
.fleet-nodes-list {
  display: grid;
  gap: 12px;
}
.fleet-node-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border-radius: var(--r-md);
  border: 1px solid var(--line);
  background: var(--solid);
}
.fleet-node-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.fleet-node-id {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
  flex: 1;
}
.fleet-node-ic {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: var(--surface-2);
  color: var(--accent);
  flex: none;
}
.fleet-node-ic .i { width: 17px; height: 17px; }
.fleet-node-meta { min-width: 0; flex: 1; display: grid; gap: 3px; }
.fleet-node-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fleet-node-name-row strong { font-size: 14.5px; }
.fn-chip {
  padding: 1px 7px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 11px;
}
.fleet-node-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
}
.fn-roots {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fleet-node-ops {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.fleet-adapters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}
.adapter-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line);
  background: var(--surface-1);
}
.adapter-card.is-ready {
  border-color: color-mix(in srgb, var(--accent-line) 55%, var(--line));
}
.adapter-card.is-unavailable,
.adapter-card.is-error {
  opacity: 0.72;
}
.adapter-badge.is-error {
  background: var(--warn-soft);
  color: var(--warn);
}
.adapter-card-head {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}
.adapter-ic {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--surface-2);
  color: var(--accent);
  flex: none;
}
.adapter-ic .i { width: 14px; height: 14px; }
.adapter-copy { min-width: 0; flex: 1; }
.adapter-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.adapter-name { font-size: 13px; font-weight: 650; color: var(--text); }
.adapter-badge {
  padding: 1px 6px;
  border-radius: var(--r-full);
  font-size: 10px;
  font-weight: 600;
  background: var(--surface-3);
  color: var(--text-3);
}
.adapter-badge.is-ready {
  background: color-mix(in srgb, var(--ok) 15%, transparent);
  color: var(--ok);
}
.adapter-sess {
  padding: 0 5px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10px;
}
.adapter-desc {
  margin-top: 2px;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.adapter-caps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.adapter-cap-chip {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-3);
  font-family: var(--mono);
  font-size: 10px;
}
.adapter-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--line);
}
.adapter-pref {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1;
  font-size: 11px;
}
.ap-lbl { color: var(--text-3); flex: none; }
.ap-val {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 10.5px;
}
.ap-clear {
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  padding: 0 3px;
  font-size: 13px;
}
.ap-clear:hover { color: var(--warn); }
.adapter-pref-empty { font-size: 11px; }
.adapter-chat-btn { flex: none; }
.fleet-no-adapters {
  margin: 0;
  font-size: 12px;
  padding: 8px 10px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
}
.issued-token-body {
  display: grid;
  gap: 10px;
}
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
