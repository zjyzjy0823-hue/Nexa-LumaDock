import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { isTauri } from '@tauri-apps/api/core'
import { installDesktopInteractions } from './desktop/desktopInteractions'
import App from './App.vue'
import './styles/main.css'
import './desktop/desktop.css'

const app = createApp(App).use(createPinia())
if (isTauri()) {
  document.documentElement.classList.add('nexa-desktop')
  app.onUnmount(installDesktopInteractions())
}
app.mount('#app')
