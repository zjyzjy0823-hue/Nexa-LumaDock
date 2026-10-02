import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { isTauri } from '@tauri-apps/api/core'
import { installDesktopInteractions } from './desktop/desktopInteractions'
import { initializeDesktopPlatform } from './desktop/platform'
import App from './App.vue'
import './styles/main.css'
import './desktop/desktop.css'

async function mountApp() {
  const app = createApp(App).use(createPinia())
  if (isTauri()) {
    const platform = await initializeDesktopPlatform()
    document.documentElement.classList.add('nexa-desktop', `nexa-${platform}`)
    app.onUnmount(installDesktopInteractions(document, platform))
  }
  app.mount('#app')
}
void mountApp()
