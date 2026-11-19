<script setup lang="ts">
import { computed } from 'vue'
import { useFleetStore } from '../../stores/fleet'
import OpusIcon from '../ui/OpusIcon.vue'
import AgentChatThread from './AgentChatThread.vue'

const props = defineProps<{
  mode: 'side' | 'subagent'
  sessionKey: string
  subtitle?: string
  embedded?: boolean
}>()

const emit = defineEmits<{
  close: []
  promoteToMain: [sessionKey: string]
  action: [message: string]
  openDiff: [focusFile?: string]
  openFile: [path: string, line?: number]
  openSubagent: [sessionId: string]
}>()

const fleet = useFleetStore()
const session = computed(() => (props.sessionKey ? fleet.sessionsByKey[props.sessionKey] ?? null : null))
</script>

<template>
  <section class="side-drawer" :aria-label="mode === 'side' ? '临时侧边问答 (/btw)' : '子代理聚焦视图'">
    <header class="side-hdr">
      <div class="side-meta">
        <OpusIcon :name="mode === 'side' ? 'sparkle' : 'bot'" class="side-ic" />
        <div class="side-titles">
          <span class="side-title">{{ mode === 'side' ? '侧边问答 · /btw' : (session?.title || '子代理执行') }}</span>
          <span class="side-sub">
            {{ subtitle || (mode === 'side' ? '共享主会话只读参考，不污染主任务上下文' : '聚焦查看子代理步骤，关闭即可回到主会话') }}
          </span>
        </div>
      </div>
      <div class="side-actions">
        <button
          v-if="sessionKey"
          type="button"
          class="btn btn-subtle btn-sm"
          title="在主标签页打开此会话"
          @click="emit('promoteToMain', sessionKey)"
        >
          <span>移至主标签</span>
        </button>
        <button
          v-if="!embedded"
          type="button"
          class="icon-btn"
          aria-label="关闭侧边视图"
          title="返回主会话"
          @click="emit('close')"
        >
          <OpusIcon name="x" />
        </button>
      </div>
    </header>

    <div class="side-body">
      <AgentChatThread
        v-if="sessionKey"
        :session-key="sessionKey"
        :compact="true"
        @action="emit('action', $event)"
        @open-diff="emit('openDiff', $event)"
        @open-file="(p, l) => emit('openFile', p, l)"
        @open-subagent="emit('openSubagent', $event)"
      />
      <div v-else class="side-empty faint">
        正在初始化独立上下文会话…
      </div>
    </div>
  </section>
</template>

<style scoped>
.side-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--surface-1);
}

.side-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}

.side-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.side-ic {
  width: 15px;
  height: 15px;
  color: var(--accent);
  flex: none;
}

.side-titles {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}

.side-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-sub {
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}

.side-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.side-empty {
  padding: 32px 16px;
  text-align: center;
  font-size: 12.5px;
}
</style>
