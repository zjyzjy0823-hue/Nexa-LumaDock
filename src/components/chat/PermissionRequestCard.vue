<script setup lang="ts">
import type { ApprovalDecision, PermissionRequestCard } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

defineProps<{ card: PermissionRequestCard }>()
const emit = defineEmits<{ respond: [callId: string, decision: ApprovalDecision] }>()

const riskText: Record<string, string> = {
  high: '高风险操作',
  medium: '需要确认',
  low: '常规请求',
}

const decisionLabel: Record<ApprovalDecision, string> = {
  allow_once: '已允许本次执行',
  allow_session: '已在当前会话放行',
  allow_trust: '已允许并加入信任白名单',
  deny: '已拒绝执行',
}
</script>

<template>
  <div class="perm-card" :class="[`risk-${card.risk}`, { resolved: card.decision !== 'pending' }]">
    <div class="perm-top">
      <OpusIcon name="shield" />
      <span class="perm-title">{{ card.title }}</span>
      <span class="perm-risk">{{ riskText[card.risk] ?? '需要确认' }}</span>
    </div>
    <code v-if="card.command" class="perm-cmd">{{ card.command }}</code>
    <div v-if="card.decision === 'pending'" class="perm-actions">
      <button type="button" class="btn btn-primary btn-sm" @click="emit('respond', card.callId, 'allow_once')">允许一次</button>
      <button type="button" class="btn btn-ghost btn-sm" @click="emit('respond', card.callId, 'allow_session')">本会话允许</button>
      <button
        v-if="card.command && card.risk !== 'high'"
        type="button"
        class="btn btn-ghost btn-sm"
        title="将同类命令前缀写入节点可信白名单，后续低中风险自动放行"
        @click="emit('respond', card.callId, 'allow_trust')"
      >始终信任此类命令</button>
      <button type="button" class="btn btn-danger btn-sm" @click="emit('respond', card.callId, 'deny')">拒绝</button>
    </div>
    <div v-else class="perm-done">
      <OpusIcon :name="card.decision === 'deny' ? 'x' : 'check'" />
      <span>{{ decisionLabel[card.decision] }}</span>
    </div>
  </div>
</template>

<style scoped>
.perm-card {
  display: grid;
  gap: 8px;
  margin-top: 8px;
  padding: 11px 12px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  box-shadow: inset 0 0 0 1px var(--line-strong);
}
.perm-card.risk-high:not(.resolved) {
  background: var(--warn-soft);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--warn) 45%, transparent);
}
.perm-top {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 620;
  color: var(--text);
}
.perm-top .i { width: 14px; height: 14px; color: var(--warn); flex: none; }
.perm-card.resolved .perm-top .i { color: var(--text-2); }
.perm-title { flex: 1; min-width: 0; }
.perm-risk {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: var(--r-pill);
  background: var(--surface-3);
  color: var(--text-2);
}
.perm-cmd {
  display: block;
  padding: 7px 9px;
  border-radius: var(--r-xs);
  background: var(--solid);
  color: var(--text);
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
}
.perm-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.perm-done {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-2);
}
.perm-done .i { width: 13px; height: 13px; }
</style>
