/**
 * 零依赖轻量 Web Audio 提示音合成器（用于任务完成与审批请求轻提示，默认关闭、可随时开关）。
 */

const SOUND_PREF_KEY = 'studiolo:fleet-sound-enabled'

export function loadSoundPref(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(SOUND_PREF_KEY) === '1'
  } catch {
    return false
  }
}

export function saveSoundPref(enabled: boolean): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(SOUND_PREF_KEY, enabled ? '1' : '0')
  } catch {
    // 隐私模式下忽略
  }
}

let sharedAudioCtx: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return null
  try {
    if (!sharedAudioCtx) sharedAudioCtx = new Ctor()
    if (sharedAudioCtx.state === 'suspended') {
      void sharedAudioCtx.resume().catch(() => {})
    }
    return sharedAudioCtx
  } catch {
    return null
  }
}

/**
 * 合成极轻柔和短提示音：
 * - `complete`: 轻柔上行双音（任务完成）
 * - `approval`: 清脆温和提示音（待人工审批/提问）
 */
export function playCueSound(kind: 'complete' | 'approval'): void {
  const ctx = getAudioContext()
  if (!ctx) return
  try {
    const now = ctx.currentTime
    const notes = kind === 'approval' ? [660, 880] : [523.25, 659.25]
    notes.forEach((freq, idx) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(freq, now + idx * 0.085)
      gain.gain.setValueAtTime(0.0001, now + idx * 0.085)
      gain.gain.exponentialRampToValueAtTime(0.035, now + idx * 0.085 + 0.018)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.085 + 0.19)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now + idx * 0.085)
      osc.stop(now + idx * 0.085 + 0.21)
    })
  } catch {
    // 自动播放策略受限时静默忽略
  }
}
