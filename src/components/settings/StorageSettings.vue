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
      <div class="storage-overview__header"><div class="settings-icon-tile"><HardDrive :size="19" /></div><div><span>USED STORAGE</span><strong v-if="info.totalGb">{{ info.usedGb.toFixed(1) }} GB <small>/ {{ info.totalGb }} GB</small></strong><strong v-else>暂不可用</strong></div><b v-if="info.totalGb">{{ usedPercent() }}%</b></div>
      <div class="storage-progress" role="meter" :aria-valuenow="info.usedGb" :aria-valuemax="info.totalGb" aria-valuemin="0" aria-label="已使用存储空间">
        <span v-for="segment in info.segments" :key="segment.id" :style="{ width: `${segment.bytes / info.totalGb * 100}%`, backgroundColor: segment.color }" />
      </div>
      <div v-if="info.totalGb" class="storage-overview__footer"><span>已用 {{ info.usedGb.toFixed(1) }} GB</span><span>可用 {{ (info.totalGb - info.usedGb).toFixed(1) }} GB</span></div>
    </div>
    <div class="settings-card">
      <div class="settings-card__heading">存储明细</div>
      <div class="storage-segments">
        <div v-for="segment in info.segments" :key="segment.id" class="storage-segment"><span class="storage-segment__dot" :style="{ backgroundColor: segment.color }" /><span>{{ segment.label }}</span><strong>{{ segment.display }}</strong></div>
      </div>
    </div>
    <div class="settings-button-row storage-actions">
      <ActionButton variant="secondary" @click="emit('clear')"><Trash2 :size="15" />清理缓存</ActionButton>
      <ActionButton variant="secondary" @click="emit('export')"><Download :size="15" />导出设置</ActionButton>
      <label class="storage-import-button"><Upload :size="15" />导入设置<input type="file" accept="application/json,.json" @change="onImport" /></label>
      <ActionButton @click="emit('backup')"><Archive :size="15" />备份设置</ActionButton>
    </div>
    <p class="storage-help"><RotateCcw :size="12" />存储用量暂不可用；导入与备份仅包含账户设置。</p>
  </SettingsSection>
</template>

<style scoped>
.storage-overview__header { display: flex; align-items: center; gap: 12px; }
.storage-overview__header > div:nth-child(2) { display: flex; flex-direction: column; gap: 3px; }
.storage-overview__header span { color: #8998b2; font-size: 9px; font-weight: 760; letter-spacing: .13em; }
.storage-overview__header strong { color: var(--text-primary); font-size: 22px; font-weight: 730; letter-spacing: -.04em; }
.storage-overview__header strong small { color: var(--text-secondary); font-size: 14px; font-weight: 550; }
.storage-overview__header b { margin-left: auto; color: var(--accent-deep); font-size: 14px; }
.storage-progress { display: flex; width: 100%; height: 12px; overflow: hidden; margin-top: 23px; border-radius: 99px; background: rgba(132,157,206,.19); box-shadow: inset 0 1px 3px rgba(59,84,136,.12); }
.storage-progress > span { flex: none; height: 100%; }
.storage-progress > span + span { border-left: 1px solid rgba(255,255,255,.7); }
.storage-overview__footer { display: flex; justify-content: space-between; margin-top: 8px; color: var(--text-secondary); font-size: 10px; }
.storage-segments { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }
.storage-segment { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 10px 12px; border: 1px solid rgba(150,174,218,.16); border-radius: 10px; background: rgba(255,255,255,.38); color: var(--text-secondary); font-size: 11px; }
.storage-segment__dot { width: 9px; height: 9px; flex: none; border-radius: 3px; }
.storage-segment strong { margin-left: auto; color: var(--text-primary); font-size: 11px; white-space: nowrap; }
.storage-import-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 39px; padding: 0 15px; border: 1px solid rgba(158,177,221,.37); border-radius: 12px; color: #4d6190; background: rgba(255,255,255,.68); box-shadow: inset 0 1px 0 rgba(255,255,255,.9); cursor: pointer; font-size: 12px; font-weight: 690; transition: transform .18s,background .18s; }
.storage-import-button:hover { transform: translateY(-2px); background: white; }
.storage-import-button input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; }
.storage-help { display: flex; align-items: center; gap: 6px; margin: 13px 2px 0; color: rgba(255,255,255,.74); font-size: 10px; }
@media (max-width: 560px) { .storage-segments { grid-template-columns: 1fr; } .storage-overview__header strong { font-size: 18px; } .storage-actions > * { flex: 1 1 calc(50% - 5px); } }
</style>
