import { invoke, isTauri } from '@tauri-apps/api/core'

export async function openExternal(value: string): Promise<void> {
  let url: URL
  try { url = new URL(value) }
  catch { throw new Error('网址格式不正确。') }
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('只能在浏览器中打开 HTTP 或 HTTPS 网站。')
  }

  if (isTauri()) {
    console.info('[external-link] invoking desktop command')
    try {
      await invoke('open_external_url', { url: url.href })
      console.info('[external-link] system open request accepted')
    } catch {
      console.warn('[external-link] desktop command failed; see logs/desktop.log')
      throw new Error('无法打开默认浏览器，请检查 Windows 默认应用设置；诊断信息见 logs/desktop.log。')
    }
  } else {
    // Keep this synchronous with the user gesture, before any visit API request.
    window.open(url.href, '_blank', 'noopener,noreferrer')
  }
}
