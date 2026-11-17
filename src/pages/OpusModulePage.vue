<script setup lang="ts">
import { ref } from 'vue'
import OpusIcon from '../components/ui/OpusIcon.vue'

defineProps<{ page: string; mobile: boolean }>()
const emit = defineEmits<{ navigate: [page: string]; back: [] }>()
const agent = ref<'hermes' | 'openclaw'>('hermes')
const agents = [
  { id: 'openclaw', name: 'OpenClaw', icon: 'claw' },
  { id: 'hermes', name: 'Hermes', icon: 'hermes' },
] as const
</script>

<template>
  <div v-if="page === 'Space'" :class="mobile ? 'mpage push' : 'page full'">
    <div v-if="mobile" class="navbar"><button type="button" class="icon-btn" aria-label="返回" @click="emit('back')"><OpusIcon name="chevL" /></button><div class="t">共享空间</div><span style="width:40px"></span></div>
    <div :class="mobile ? undefined : 'vault-lock'">
      <div :class="mobile ? 'vault-m' : 'vault-card mat'">
        <div class="lk"><OpusIcon name="lock" /></div><h2>共享空间</h2>
        <p class="muted" style="margin:0;font-size:13px">每次查看内容都需要输入密码，离线时也一样。</p>
        <template v-if="mobile">
          <button class="btn btn-primary btn-lg" style="width:100%;margin-top:14px" type="button" disabled><OpusIcon name="unlock" />输入密码查看目录</button>
          <p class="faint" style="font-size:12.5px;margin:6px 0 0">共享空间待接入</p>
        </template>
        <template v-else>
          <div><div class="pw-field"><OpusIcon name="lock" /><input class="input" type="password" placeholder="共享空间密码" aria-label="共享空间密码" disabled></div>
            <button class="btn btn-primary btn-lg" style="width:100%;margin-top:10px" type="button" disabled><OpusIcon name="unlock" />查看目录</button>
          </div>
          <div class="faint">共享空间待接入</div>
        </template>
      </div>
    </div>
  </div>
  <div v-else-if="mobile" class="mpage">
    <div class="mhead"><h1>对话</h1><span class="spacer"></span><button class="icon-btn" type="button" aria-label="新会话" style="width:40px;height:40px" disabled><OpusIcon name="plus" /></button></div>
    <div class="agent-tabs">
      <button v-for="item in agents" :key="item.id" type="button" class="agent-tab" :class="'oc-' + item.id" :aria-pressed="agent === item.id" @click="agent = item.id">
        <span class="am"><OpusIcon :name="item.icon" /></span><span style="min-width:0"><div style="font-weight:650">{{ item.name }}</div><div class="conn offline" style="font-size:11.5px">待接入</div></span>
      </button>
    </div>
    <div class="notice"><OpusIcon name="chat" /><div><b>{{ agents.find(item => item.id === agent)?.name }} 对话待接入</b><br>会话由 Agent 提供。</div></div>
    <button class="btn btn-ghost" type="button" @click="emit('navigate', 'Agents')"><OpusIcon name="settings" />Agent 配置</button>
  </div>
  <div v-else class="page full">
    <div class="split opus-agent-split">
      <aside class="pane-side">
        <div class="pane-h"><h2>Agent</h2><span class="spacer"></span><button class="icon-btn" type="button" aria-label="新会话" disabled><OpusIcon name="plus" /></button></div>
        <div class="agent-switch">
          <button v-for="item in agents" :key="item.id" class="agent-card" :class="'oc-' + item.id" type="button" :aria-pressed="agent === item.id" @click="agent = item.id">
            <span class="am"><OpusIcon :name="item.icon" /></span><span class="grow"><div class="nm">{{ item.name }}</div><div class="in">待接入</div></span><span class="conn offline"></span>
          </button>
        </div>
        <div class="nav-sec" style="margin:8px 16px 4px">会话</div>
        <div class="notice" style="margin:0 12px"><OpusIcon name="info" /><div>连接后显示会话列表</div></div>
        <div class="src-note"><OpusIcon name="info" />会话列表由 {{ agents.find(item => item.id === agent)?.name }} 提供</div>
      </aside>
      <section style="min-width:0;overflow:hidden"><div class="cleared"><OpusIcon name="chat" />{{ agents.find(item => item.id === agent)?.name }} 对话待接入</div></section>
      <aside class="pane-inspector" style="padding:16px;display:grid;gap:18px;align-content:start">
        <div><div class="card-h"><OpusIcon name="server" /> 连接</div><dl class="meta-grid"><dt>状态</dt><dd><span class="conn offline">待接入</span></dd></dl><button class="btn btn-sm btn-ghost" type="button" @click="emit('navigate', 'Agents')">Agent 配置</button></div>
        <div class="notice"><OpusIcon name="shield" /><div>聊天记录由 Agent 提供。</div></div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.opus-agent-split { grid-template-columns:270px minmax(0,1fr) 280px; }
@container (max-width: 880px) { .opus-agent-split { grid-template-columns:210px minmax(0,1fr) 200px; } }
@container (max-width: 700px) { .opus-agent-split { grid-template-columns:175px minmax(0,1fr); } .opus-agent-split .pane-inspector { grid-column:1/-1; } }
</style>
