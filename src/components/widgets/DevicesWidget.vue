<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Apple, HardDrive, Server, Tablet } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { useAuthStore } from '../../stores/auth'
import { useDevicesStore } from '../../stores/devices'

const auth = useAuthStore()
const store = useDevicesStore()
const deviceSnapshots = computed(() => store.devices.slice(0, 4).map(device => ({
  id: device.id, name: device.name, platform: device.system,
  icon: device.kind,
  online: device.online, cpu: device.cpu, ram: device.memory,
  battery: device.battery ?? undefined, activity: device.activity, lastSeenAt: device.lastSeenAt,
})))
onMounted(() => { if (auth.token) void store.load(auth.token) })

function activityPoints(values: number[]) {
  return values.map((value, index) => `${(index * 72) / Math.max(values.length - 1, 1)},${26 - value * .23}`).join(' ')
}
</script>

<template>
  <GlassCard title="设备" class="devices-card">
    <template #action><span class="view-all">查看全部 ({{ store.devices.length }})</span></template>

    <div class="device-list">
      <p v-if="!deviceSnapshots.length" class="widget-empty">{{ store.loading ? '正在加载设备…' : store.error || '暂无设备，前往设备页添加。' }}</p>
      <div v-for="device in deviceSnapshots" :key="device.id" class="device-row">
        <span class="device-icon" :class="`device-icon--${device.icon}`" aria-hidden="true">
          <span v-if="device.icon === 'desktop'" class="windows-mark"><i /><i /><i /><i /></span>
          <Apple v-else-if="device.icon === 'mac'" :size="27" :stroke-width="1.45" fill="currentColor" />
          <svg v-else-if="device.icon === 'phone'" class="android-mark" viewBox="0 0 36 36">
            <path d="m8 13 3-5m17 5-3-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <path d="M7 15a11 11 0 0 1 22 0Z" fill="currentColor" />
            <rect x="7" y="16" width="22" height="13" rx="2" fill="currentColor" />
            <rect x="3" y="17" width="3" height="11" rx="1.5" fill="currentColor" /><rect x="30" y="17" width="3" height="11" rx="1.5" fill="currentColor" />
            <rect x="10" y="27" width="3" height="6" rx="1.5" fill="currentColor" /><rect x="23" y="27" width="3" height="6" rx="1.5" fill="currentColor" />
            <circle cx="13" cy="12" r=".9" fill="#e7f5da" /><circle cx="23" cy="12" r=".9" fill="#e7f5da" />
          </svg>
          <Tablet v-else-if="device.icon === 'tablet'" :size="27" :stroke-width="1.6" />
          <HardDrive v-else-if="device.icon === 'nas'" :size="27" :stroke-width="1.6" />
          <Server v-else :size="27" :stroke-width="1.6" />
        </span>

        <span class="device-identity"><strong>{{ device.name }}</strong><small>{{ device.platform }}</small></span>

        <span class="connection-status" :class="{ 'connection-status--offline': !device.online }"><i />{{ device.online ? '在线' : '离线' }}</span>

        <span class="device-metrics">
          <span v-if="!device.lastSeenAt">等待心跳</span>
          <span v-else-if="device.battery !== undefined">电量 <strong>{{ device.battery }}%</strong></span>
          <template v-else><span>CPU <strong>{{ device.cpu }}%</strong></span><span>内存 <strong>{{ device.ram }}%</strong></span></template>
        </span>

        <span class="device-visual" aria-hidden="true">
          <span v-if="device.battery !== undefined" class="battery"><i :style="{ width: `${device.battery}%` }" /></span>
          <svg v-else class="device-sparkline" viewBox="0 0 72 28" preserveAspectRatio="none"><polyline :points="activityPoints(device.activity)" /></svg>
        </span>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.devices-card { min-width: 0; padding: 19px 19px 1px; }
.devices-card :deep(.glass-card__header) { margin-bottom: 12px; }
.devices-card :deep(.glass-card__title) { color: #fff; font-size: 18px; font-weight: 580; text-shadow: 0 1px 10px rgba(37,52,94,.16); }
.devices-card :deep(.glass-card__title)::after { content: '›'; margin-left: 11px; font-size: 25px; font-weight: 300; vertical-align: -1px; }
.view-all { color: rgba(255,255,255,.96); font-size: 14px; font-weight: 450; white-space: nowrap; }
.devices-card :deep(.glass-card__body) { min-height: 0; }
.device-list { display: grid; height: 100%; grid-template-rows: repeat(4, minmax(42px, 1fr)); gap: 4px; }
.widget-empty { grid-row: 1 / -1; align-self: center; margin: 0; color: rgba(255,255,255,.9); font-size: 12px; text-align: center; }
.device-row { display: grid; grid-template-columns: 37px minmax(0,1fr) 62px 72px 60px; align-items: center; gap: 7px; min-width: 0; min-height: 0; padding: 5px 11px; border: 1px solid rgba(255,255,255,.5); border-radius: 15px; background: linear-gradient(110deg, rgba(247,249,255,.76), rgba(231,238,255,.64)); box-shadow: inset 0 1px 0 rgba(255,255,255,.58); transition: transform .2s ease, background .2s ease; }
.device-row:hover { transform: translateX(2px); background: rgba(255,255,255,.85); }
.device-icon { display: grid; width: 34px; height: 34px; place-items: center; }
.device-icon--mac { color: #353a48; }
.device-icon--phone { color: #61bb38; }
.android-mark { width: 32px; height: 32px; }
.windows-mark { display: grid; width: 25px; height: 25px; grid-template-columns: repeat(2,1fr); gap: 2px; transform: perspective(35px) rotateY(-9deg); }
.windows-mark i { background: #0b9bee; }
.windows-mark i:nth-child(2), .windows-mark i:nth-child(4) { background: #087aca; }
.minecraft-mark { width: 34px; height: 34px; filter: drop-shadow(0 2px 2px rgba(38,63,32,.24)); }
.device-identity { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.device-identity strong, .device-identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.device-identity strong { color: #111a2b; font-size: 13px; font-weight: 680; letter-spacing: -.025em; }
.device-identity small { color: #536176; font-size: 11px; font-weight: 500; }
.connection-status { display: flex; align-items: center; gap: 5px; color: #24844f; font-size: 11px; font-weight: 540; white-space: nowrap; }
.connection-status i { width: 7px; height: 7px; flex: none; border-radius: 50%; background: #1c9856; }
.connection-status--offline { color: #7b8392; }
.connection-status--offline i { background: #9199a6; }
.device-metrics { display: flex; min-width: 0; flex-direction: column; gap: 2px; padding-left: 9px; border-left: 1px solid rgba(119,139,178,.25); }
.device-metrics span { color: #637087; font-size: 11px; line-height: 1.22; white-space: nowrap; }
.device-metrics strong { float: right; margin-left: 4px; color: #202a3b; font-weight: 680; font-variant-numeric: tabular-nums; }
.device-visual { display: flex; align-items: center; justify-content: center; min-width: 0; }
.device-sparkline { width: 60px; height: 28px; overflow: visible; filter: drop-shadow(0 2px 3px rgba(26,129,247,.18)); }
.device-sparkline polyline { fill: none; stroke: #278dff; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.battery { position: relative; display: block; width: 35px; height: 15px; padding: 2px; border: 1.5px solid #5c6677; border-radius: 3px; }
.battery::after { position: absolute; top: 4px; right: -4px; width: 2px; height: 5px; border-radius: 0 2px 2px 0; background: #5c6677; content: ''; }
.battery i { display: block; height: 100%; border-radius: 1px; background: #28b861; }
@container (max-width: 440px) {
  .devices-card { padding: 13px 13px 9px; }
  .devices-card :deep(.glass-card__header) { margin-bottom: 8px; }
  .view-all { font-size: 11px; }
  .device-row { grid-template-columns: 30px minmax(0, 1fr) 50px 56px; gap: 5px; padding-inline: 7px; }
  .device-icon, .minecraft-mark, .android-mark { width: 28px; height: 28px; }
  .windows-mark { width: 22px; height: 22px; }
  .device-visual { display: none; }
  .device-identity strong { font-size: 11px; }
  .device-identity small, .connection-status, .device-metrics span { font-size: 9px; }
  .device-metrics { padding-left: 5px; }
}
@container (max-width: 300px) {
  .device-row { grid-template-columns: 28px minmax(0, 1fr) 52px; }
  .device-metrics { display: none; }
}
@container (max-height: 220px) {
  .device-list { grid-template-rows: repeat(4, minmax(38px, 1fr)); }
  .device-row { padding-block: 3px; }
}
@media (max-width: 480px) { .devices-card { padding-inline: 12px; } .device-row { grid-template-columns: 29px minmax(0,1fr) 51px 60px 40px; gap: 5px; padding-inline: 7px; } .device-icon, .minecraft-mark, .android-mark { width: 27px; height: 27px; } .windows-mark { width: 22px; height: 22px; } .device-identity strong { font-size: 11px; } .device-identity small, .connection-status, .device-metrics span { font-size: 9px; } .device-metrics { padding-left: 5px; } .device-sparkline { width: 40px; } .battery { width: 29px; } }
</style>
