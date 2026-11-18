import type icons from '../../styles/opus-icons'
import type { AdapterProvider, NodePlatform } from '../../types/fleet'

export type OpusIconName = keyof typeof icons

export interface ProviderVisual {
  label: string
  shortCode: string
  icon: OpusIconName
  accentClass: string
  shortDesc: string
}

export const PROVIDER_META: Record<AdapterProvider, ProviderVisual> = {
  codex: { label: 'Codex', shortCode: 'CX', icon: 'api', accentClass: 'oc-studiolo', shortDesc: 'OpenAI Codex app-server' },
  opencode: { label: 'OpenCode', shortCode: 'OC', icon: 'terminal', accentClass: 'oc-openclaw', shortDesc: 'opencode serve HTTP+SSE' },
  hermes: { label: 'Hermes', shortCode: 'HM', icon: 'hermes', accentClass: 'oc-hermes', shortDesc: 'Hermes ACP / Gateway' },
  antigravity: { label: 'Antigravity', shortCode: 'AG', icon: 'sparkle', accentClass: 'oc-studiolo', shortDesc: 'agy 命令行代理' },
  dsh: { label: 'DSH / Claude', shortCode: 'DS', icon: 'bot', accentClass: 'oc-hermes', shortDesc: 'Claude Code CLI' },
  openclaw: { label: 'OpenClaw', shortCode: 'CL', icon: 'claw', accentClass: 'oc-openclaw', shortDesc: 'OpenClaw Gateway' },
  mock: { label: 'Mock', shortCode: 'MK', icon: 'shield', accentClass: 'oc-studiolo', shortDesc: '沙箱联调模拟代理' },
}

export function getProviderMeta(provider: AdapterProvider): ProviderVisual {
  return PROVIDER_META[provider] ?? PROVIDER_META.mock
}

export function getPlatformIcon(platform: NodePlatform | string): OpusIconName {
  if (platform === 'android' || platform === 'ios') return 'phone'
  if (platform === 'linux') return 'server'
  return 'device'
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}
