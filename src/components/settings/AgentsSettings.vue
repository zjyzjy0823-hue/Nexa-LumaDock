<script setup lang="ts">
import { computed, onMounted } from 'vue'
import SettingsSection from './SettingsSection.vue'
import SettingRow from './SettingRow.vue'
import OpusIcon from '../ui/OpusIcon.vue'
import { useAuthStore } from '../../stores/auth'
import { useAgentsStore } from '../../stores/agents'

const emit = defineEmits<{ navigate: [page: string] }>()
const auth = useAuthStore()
const agentsStore = useAgentsStore()

onMounted(() => {
  if (auth.token && !agentsStore.agents.length && !agentsStore.loading) {
    void agentsStore.load(auth.token).catch(() => {})
  }
})

const runningCount = computed(() => agentsStore.agents.filter(item => item.status === 'running').length)
</script>

<template>
  <SettingsSection title="Agent 与连接" description="管理已绑定的本地 Agent 身份，以及即将接入的 Agent Chat 网关。">
    <div class="settings-card settings-card--rows">
      <SettingRow label="本地 Agent 运行时（na_live_）" :description="`已登记 ${agentsStore.agents.length} 个身份 · 运行中 ${runningCount} 个 · 用于任务派发与 Data Actions`">
        <button type="button" class="btn btn-primary btn-sm" @click="emit('navigate', 'Agents')">前往 Agent 配置</button>
      </SettingRow>
      <SettingRow label="新建智能体或令牌" description="在配置页发放或撤销 na_live_ 凭证，并管理数据作用域">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('navigate', 'Agents')"><OpusIcon name="settings" />打开管理</button>
      </SettingRow>
    </div>

    <div class="settings-card settings-card--rows">
      <div class="settings-card__heading" style="padding:14px 16px;margin:0;border-bottom:1px solid var(--line)">
        <span>Agent Chat 网关</span>
        <small>由 Agent 提供历史，Studiolo 不持久化正文</small>
      </div>
      <SettingRow label="OpenClaw Gateway" description="与本地 na_live_ 工具代理独立隔离，后续用于实时会话与原生 Cron"><span class="conn offline">待接入</span></SettingRow>
      <SettingRow label="Hermes Agent Gateway" description="支持上游会话查询、流式回复与原生 Cron 聚合"><span class="conn offline">待接入</span></SettingRow>
    </div>
  </SettingsSection>
</template>
