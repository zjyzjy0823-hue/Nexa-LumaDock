<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { MapPin, Sun } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { getLocationWeather } from '../../services/weather'

const now = ref(new Date())
const city = ref('定位中…')
const temperature = ref<number | null>(null)
const condition = ref('天气加载中')
const locating = ref(false)
let clockInterval: number | undefined

async function locate(force = false) {
  if (locating.value) return
  locating.value = true
  try {
    const weather = await getLocationWeather(force)
    city.value = weather.approximate ? `约 ${weather.city}` : weather.city
    temperature.value = weather.temperature
    condition.value = weather.condition
  } catch {
    city.value = '点击获取位置'
    condition.value = '天气不可用'
  } finally { locating.value = false }
}

onMounted(() => {
  clockInterval = window.setInterval(() => { now.value = new Date() }, 15_000)
  void locate()
})

onUnmounted(() => {
  if (clockInterval !== undefined) window.clearInterval(clockInterval)
})

const time = computed(() => new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
}).format(now.value))

const date = computed(() => new Intl.DateTimeFormat('zh-CN', {
  weekday: 'long', month: 'short', day: 'numeric',
}).format(now.value))

const isNight = computed(() => now.value.getHours() < 6 || now.value.getHours() >= 18)
</script>

<template>
  <GlassCard class="clock-card">
    <div class="clock-content">
      <svg class="night-art" viewBox="0 0 320 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="clockSky" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#253964" /><stop offset=".6" stop-color="#4c6e9c" /><stop offset="1" stop-color="#b18e9b" /></linearGradient>
          <linearGradient id="clockWater" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#527092" /><stop offset="1" stop-color="#152f53" /></linearGradient>
          <linearGradient id="clockMount" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#8396b7" /><stop offset="1" stop-color="#35496e" /></linearGradient>
          <mask id="clockCrescent"><rect width="320" height="300" fill="white" /><circle cx="232" cy="53" r="31" fill="black" /></mask>
          <filter id="moonGlow"><feGaussianBlur stdDeviation="7" /></filter>
        </defs>
        <rect width="320" height="300" fill="url(#clockSky)" />
        <circle cx="256" cy="64" r="28" fill="#fff4dc" opacity=".45" filter="url(#moonGlow)" />
        <circle cx="256" cy="64" r="28" fill="#fff7e9" mask="url(#clockCrescent)" />
        <g fill="#e7edff" opacity=".6"><circle cx="44" cy="92" r=".8" /><circle cx="119" cy="34" r=".6" /><circle cx="166" cy="85" r=".8" /><circle cx="205" cy="19" r=".6" /><circle cx="285" cy="110" r=".7" /><circle cx="76" cy="61" r=".45" /><circle cx="296" cy="35" r=".45" /></g>
        <path d="M0 196 28 174 48 179 87 147 126 178 160 132 181 145 208 126 245 167 268 152 320 184v58H0Z" fill="url(#clockMount)" />
        <path d="M0 211 45 180 71 189 112 171 157 198 182 182 221 187 255 170 320 195v47H0Z" fill="#3d547c" opacity=".76" />
        <path d="M0 220c60 7 114 10 178 5 61-5 104-9 142-3v78H0Z" fill="url(#clockWater)" />
        <g fill="#243455"><path d="M182 211h12v-35h5v35h14v-56h7v56h8v-74h8v74h13v-46h8v46h11v-60h7v60h9v-28h8v28h25v32H182Z" /><path d="M228 137h8l-4-29Z" /></g>
        <g fill="#ffe1a6" opacity=".92"><rect x="187" y="186" width="2" height="3" /><rect x="190" y="198" width="2" height="3" /><rect x="203" y="177" width="2" height="3" /><rect x="216" y="167" width="2" height="3" /><rect x="217" y="185" width="2" height="3" /><rect x="230" y="148" width="2" height="3" /><rect x="230" y="163" width="2" height="3" /><rect x="238" y="193" width="2" height="3" /><rect x="251" y="179" width="2" height="3" /><rect x="261" y="194" width="2" height="3" /><rect x="273" y="170" width="2" height="3" /><rect x="273" y="185" width="2" height="3" /><rect x="285" y="197" width="2" height="3" /></g>
        <g fill="#eacba9" opacity=".42"><rect x="196" y="230" width="2" height="22" /><rect x="215" y="235" width="2" height="26" /><rect x="230" y="236" width="2" height="42" /><rect x="240" y="230" width="2" height="20" /><rect x="255" y="233" width="2" height="31" /><rect x="276" y="236" width="2" height="21" /></g>
        <g stroke="#afc2d7" stroke-width=".65" opacity=".3"><path d="M17 242h61m20 15h45m58 22h82M42 286h100m100-37h72M4 266h63" /></g>
      </svg>
      <div class="clock-scenery" :class="{ 'clock-scenery--day': !isNight }" aria-hidden="true" />
      <svg v-if="isNight" class="clock-feature-moon" viewBox="0 0 80 80" aria-hidden="true"><defs><mask id="clock-feature-moon-mask"><circle cx="41" cy="39" r="29" fill="white" /><circle cx="31" cy="36" r="29" fill="black" /></mask></defs><circle cx="41" cy="39" r="29" fill="#fff3dc" mask="url(#clock-feature-moon-mask)" /></svg>
      <div class="night-vignette" />
      <div class="clock-main">
        <span class="clock-time">{{ time }}</span>
        <span class="clock-date">{{ date }}</span>
      </div>
      <div class="weather-reading">
        <svg v-if="isNight" class="weather-symbol" viewBox="0 0 48 48" aria-hidden="true">
          <defs><mask id="weather-moon-cutout"><rect width="48" height="48" fill="white" /><circle cx="34" cy="12" r="18" fill="black" /></mask></defs>
          <circle cx="23" cy="24" r="18" fill="currentColor" mask="url(#weather-moon-cutout)" />
          <path d="m39 6 1.2 3.5L44 11l-3.8 1.3L39 16l-1.1-3.7L34 11l3.9-1.5Z" fill="currentColor" />
        </svg>
        <Sun v-else class="weather-symbol" :size="44" :stroke-width="1.5" />
        <span><strong>{{ temperature === null ? '--' : `${temperature}°C` }}</strong><small>{{ condition }}</small></span>
      </div>
      <button class="weather-location" type="button" :title="city === '点击获取位置' ? '重试定位' : '更新位置和天气'" @click="locate(true)"><MapPin :size="17" :stroke-width="2.1" />{{ city }}</button>
      <a v-if="temperature !== null" class="weather-credit" href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">天气数据 Open-Meteo</a>
    </div>
  </GlassCard>
</template>

<style scoped>
.clock-card { isolation: isolate; min-width: 0; padding: 0; border-color: rgba(255,255,255,.4); background: #334c7d; color: white; }
.clock-card::before, .clock-card::after { display: none; }
.clock-card :deep(.glass-card__body) { position: relative; z-index: 1; height: 100%; }
.clock-content { position: relative; display: flex; height: 100%; min-height: 0; flex-direction: column; overflow: hidden; padding: 20px 24px 26px; }
.night-art, .clock-scenery, .night-vignette { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.clock-feature-moon { position: absolute; z-index: 1; top: 17px; right: 16px; width: 69px; height: 69px; pointer-events: none; filter: drop-shadow(0 0 7px rgba(255,232,190,.28)); }
.clock-scenery { background: #344e7d url('/night-city.png') center center / cover no-repeat; }
.clock-scenery--day { background: #8bbce9 url('/day-city.png') center center / cover no-repeat; }
.night-vignette { background: linear-gradient(90deg, rgba(20,35,76,.23), transparent 75%), linear-gradient(180deg, rgba(11,25,59,.17) 0%, transparent 35%, rgba(14,27,57,.12) 63%, rgba(11,25,54,.55) 100%); }
.clock-main, .weather-reading, .weather-location { position: relative; z-index: 1; }
.clock-main { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.clock-time { font-size: clamp(44px, 3.3vw, 51px); font-weight: 430; line-height: 1; letter-spacing: -.045em; font-variant-numeric: tabular-nums; text-shadow: 0 2px 12px rgba(8,20,50,.2); }
.clock-date { font-size: 16px; font-weight: 450; letter-spacing: -.018em; text-shadow: 0 1px 8px rgba(8,20,50,.3); }
.weather-reading { display: flex; align-items: center; gap: 10px; margin-top: auto; color: #fff4dc; }
.weather-symbol { width: 44px; height: 44px; flex: none; }
.weather-reading span { display: flex; flex-direction: column; color: white; }
.weather-reading strong { font-size: 24px; font-weight: 490; line-height: 1; letter-spacing: -.045em; }
.weather-reading small { margin-top: 3px; font-size: 14px; font-weight: 450; }
.weather-location { display: flex; align-items: center; gap: 8px; align-self: flex-start; margin-top: 19px; padding: 0; color: white; border: 0; background: none; font: inherit; font-size: 14px; font-weight: 500; text-shadow: 0 1px 8px rgba(8,20,50,.35); cursor: pointer; }
.weather-location:focus-visible { outline: 2px solid white; outline-offset: 4px; }
.weather-credit { position: absolute; z-index: 2; right: 10px; bottom: 8px; color: rgba(255,255,255,.82); font-size: 9px; text-decoration: none; text-shadow: 0 1px 4px rgba(8,20,50,.5); }
.weather-credit:hover { color: white; text-decoration: underline; }
@container (max-width: 280px) {
  .clock-content { padding-inline: 16px; }
  .clock-time { font-size: clamp(37px, 17cqw, 48px); }
  .clock-date { font-size: 13px; }
  .clock-feature-moon { width: 51px; height: 51px; }
}
@container (max-height: 240px) {
  .clock-content { padding-block: 13px 15px; }
  .weather-symbol { width: 34px; height: 34px; }
  .weather-reading strong { font-size: 20px; }
  .weather-reading small, .weather-location { font-size: 12px; }
  .weather-location { margin-top: 8px; }
}
@media (max-width: 800px) { .clock-content { min-height: 275px; } }
</style>
