<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useAgentsStore } from '../../stores/agents'
import { useAuthStore } from '../../stores/auth'
import FleetNodesSection from '../chat/FleetNodesSection.vue'
import OpusIcon from '../ui/OpusIcon.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'

const emit = defineEmits<{ navigate: [page: string]; action: [message: string] }>()
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
  <SettingsSection title="Agent 与连接" description="管理已绑定的本地 Data Actions 代理，以及多设备协同控制节点（sn_live_）下接入的各对话智能体。">
    <FleetNodesSection
      :embedded-in-settings="true"
      @navigate="emit('navigate', $event)"
      @action="emit('action', $event)"
    />

    <div class="settings-card settings-card--rows">
      <SettingRow label="本地 Agent 运行时（na_live_）" :description="`已登记 ${agentsStore.agents.length} 个身份 · 运行中 ${runningCount} 个 · 用于任务派发与 Data Actions`">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('navigate', 'Agents')">前往 Agent 配置</button>
      </SettingRow>
      <SettingRow label="新建智能体或令牌" description="在配置页发放或撤销 na_live_ 凭证，并管理数据作用域">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('navigate', 'Agents')"><OpusIcon name="settings" />打开管理</button>
      </SettingRow>
    </div>
  </SettingsSection>
</template>
