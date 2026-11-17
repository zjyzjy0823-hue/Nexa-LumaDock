<script setup lang="ts">
import { Archive, Download, HardDrive, RotateCcw, Trash2, Upload } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import SettingsSection from './SettingsSection.vue'
import type { StorageInfo } from '../../types/settings'

const props = defineProps<{ info: StorageInfo }>()
const emit = defineEmits<{ clear: []; export: []; import: [file: File]; backup: [] }>()

const usedPercent = () => props.info.totalGb ? Math.min(100, Math.round(props.info.usedGb / props.info.totalGb * 100)) : 0
function onImport(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) emit('import', file)
  input.value = ''
}
</script>

<template>
  <SettingsSection title="存储" description="查看本地数据、附件与缓存的空间占用。">
    <div class="settings-card storage-overview">
      <div class="storage-overview__header"><div class="settings-icon-tile"><HardDrive :size="18" /></div><div><span class="faint" style="font-size:12px">已用存储</span><strong v-if="info.totalGb">{{ info.usedGb.toFixed(1) }} GB <small>/ {{ info.totalGb }} GB</small></strong><strong v-else>暂不可用</strong></div><b v-if="info.totalGb">{{ usedPercent() }}%</b></div>
      <div class="storage-progress" role="meter" :aria-valuenow="info.usedGb" :aria-valuemax="info.totalGb" aria-valuemin="0" aria-label="已使用存储空间">
        <span v-for="segment in info.segments" :key="segment.id" :style="{ width: `${segment.bytes / info.totalGb * 100}%`, backgroundColor: segment.color }" />
      </div>
      <div v-if="info.totalGb" class="storage-overview__footer"><span>已用 {{ info.usedGb.toFixed(1) }} GB</span><span>可用 {{ (info.totalGb - info.usedGb).toFixed(1) }} GB</span></div>
    </div>
    <div v-if="info.segments.length" class="settings-card">
      <div class="settings-card__heading">存储明细</div>
      <div class="storage-segments">
        <div v-for="segment in info.segments" :key="segment.id" class="storage-segment"><span class="storage-segment__dot" :style="{ backgroundColor: segment.color }" /><span>{{ segment.label }}</span><strong>{{ segment.display }}</strong></div>
      </div>
    </div>
    <div class="settings-button-row storage-actions" style="margin-top:0">
      <ActionButton variant="secondary" disabled title="本版本不管理缓存"><Trash2 :size="15" />清理缓存（未启用）</ActionButton>
      <ActionButton variant="secondary" @click="emit('export')"><Download :size="15" />导出设置</ActionButton>
      <label class="btn btn-ghost storage-import-button"><Upload :size="15" />导入设置<input type="file" accept="application/json,.json" @change="onImport" /></label>
      <ActionButton @click="emit('backup')"><Archive :size="15" />备份设置</ActionButton>
    </div>
    <p class="storage-help"><RotateCcw :size="13" />存储用量与缓存清理尚未实现；导入与备份仅包含账户设置。</p>
  </SettingsSection>
</template>

<style scoped>
.storage-overview__header { display: flex; align-items: center; gap: 12px; }
.storage-overview__header > div:nth-child(2) { display: flex; flex-direction: column; gap: 2px; }
.storage-overview__header strong { color: var(--text); font-size: 18px; font-weight: 700; }
.storage-overview__header strong small { color: var(--text-3); font-size: 13px; font-weight: 500; }
.storage-overview__header b { margin-left: auto; color: var(--accent); font-size: 14px; }
.storage-progress { display: flex; width: 100%; height: 8px; overflow: hidden; margin-top: 14px; border-radius: 99px; background: var(--surface-3); }
.storage-progress > span { flex: none; height: 100%; }
.storage-overview__footer { display: flex; justify-content: space-between; margin-top: 8px; color: var(--text-3); font-size: 12px; }
.storage-segments { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.storage-segment { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 10px 12px; border-radius: var(--r-md); background: var(--surface-3); color: var(--text-2); font-size: 13px; }
.storage-segment__dot { width: 8px; height: 8px; flex: none; border-radius: 2px; }
.storage-segment strong { margin-left: auto; color: var(--text); font-size: 13px; white-space: nowrap; }
.storage-import-button { position: relative; cursor: pointer; }
.storage-import-button input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; }
.storage-help { display: flex; align-items: center; gap: 6px; margin: 0; color: var(--text-3); font-size: 12px; }
@media (max-width: 560px) { .storage-segments { grid-template-columns: 1fr; } }
</style>
