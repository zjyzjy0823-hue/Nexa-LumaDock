import { invoke, isTauri } from '@tauri-apps/api/core'

export type DesktopPlatform = 'web' | 'windows' | 'macos' | 'linux'
let platform: DesktopPlatform = 'web'

export async function initializeDesktopPlatform(): Promise<DesktopPlatform> {
  platform = isTauri() ? await invoke<DesktopPlatform>('desktop_platform') : 'web'
  return platform
}

export function desktopPlatform(): DesktopPlatform {
  return platform
}
