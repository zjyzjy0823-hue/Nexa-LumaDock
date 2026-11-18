<script setup lang="ts">
import { ref } from 'vue'
import type { ArtifactRef } from '../../types/fleet'
import { useFleetStore } from '../../stores/fleet'
import OpusIcon from '../ui/OpusIcon.vue'
import { formatBytes } from './providerMeta'

const props = defineProps<{ artifact: ArtifactRef; compact?: boolean }>()
const emit = defineEmits<{ handoff: [artifact: ArtifactRef]; status: [message: string] }>()

const fleet = useFleetStore()
const downloading = ref(false)
const usedTransport = ref<string | null>(props.artifact.downloadedTransport ?? null)

const transportLabel: Record<string, string> = {
  lan: 'LAN 直连',
  xtcp: 'FRP P2P',
  edge_relay: 'Edge Relay',
  core: 'Core 回落',
}

async function handleDownload() {
  if (downloading.value) return
  downloading.value = true
  try {
    const t = await fleet.downloadArtifactToBrowser(props.artifact)
    usedTransport.value = t
    emit('status', `已通过 ${transportLabel[t] ?? t} 解密保存 ${props.artifact.fileName}`)
  } catch (err) {
    emit('status', err instanceof Error ? err.message : '加密文件解密下载失败')
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <div class="artifact-pill" :class="{ compact }">
    <span class="artifact-ic"><OpusIcon name="file" /></span>
    <div class="artifact-meta">
      <div class="artifact-name" :title="artifact.fileName">{{ artifact.fileName }}</div>
      <div class="artifact-sub">
        <span>{{ formatBytes(artifact.plaintextSize) }}</span>
        <span>·</span>
        <span>AES-256-GCM</span>
        <template v-if="usedTransport || artifact.storageRole">
          <span>·</span>
          <span>{{ transportLabel[usedTransport || artifact.storageRole || 'core'] ?? artifact.storageRole }}</span>
        </template>
      </div>
    </div>
    <button
      type="button"
      class="btn btn-ghost btn-sm"
      :disabled="downloading"
      title="在本地浏览器端解密下载"
      @click="handleDownload"
    >
      <OpusIcon name="download" />
      <span>{{ downloading ? '解密中' : '下载' }}</span>
    </button>
    <button
      v-if="!compact"
      type="button"
      class="btn btn-subtle btn-sm"
      title="带着此加密产物交给其他机器的 Agent 继续处理"
      @click="emit('handoff', artifact)"
    >
      @Handoff
    </button>
  </div>
</template>

<style scoped>
.artifact-pill {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  box-shadow: inset 0 0 0 1px var(--line);
}
.artifact-pill.compact { padding: 6px 8px; }
.artifact-ic {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  flex: none;
}
.artifact-ic .i { width: 15px; height: 15px; }
.artifact-meta { flex: 1; min-width: 0; }
.artifact-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.artifact-sub {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-3);
}
</style>
