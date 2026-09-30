import { version } from '../../package.json'
import type {
  AboutInfo, AccentColor, AppearanceConfig, BackgroundChoice, GlassTheme,
  NotificationChannel, NotificationConfig, NotificationEvent, SecurityConfig,
  SettingsSectionId, StorageInfo, SyncConfig, SyncMode, UserProfile,
} from '../types/settings'

export const settingsNavigation: { id: SettingsSectionId; label: string; icon: string }[] = [
  { id: 'account', label: '账户', icon: 'UserRound' },
  { id: 'appearance', label: '外观', icon: 'Palette' },
  { id: 'sync', label: '同步', icon: 'RefreshCw' },
  { id: 'storage', label: '存储', icon: 'HardDrive' },
  { id: 'security', label: '安全', icon: 'ShieldCheck' },
  { id: 'notifications', label: '通知', icon: 'Bell' },
  { id: 'about', label: '关于', icon: 'Info' },
]

export const timezoneOptions = ['Asia/Shanghai', 'UTC', 'America/New_York']
export const languageOptions = ['zh-CN', 'en-US']

export const themeOptions: { id: GlassTheme; label: string; detail: string }[] = [
  { id: 'light', label: 'Light Glass', detail: '明亮柔和' },
  { id: 'dark', label: 'Dark Glass', detail: '深色沉浸' },
  { id: 'auto', label: 'Auto', detail: '跟随系统' },
]

export const accentOptions: { id: AccentColor; label: string; color: string }[] = [
  { id: 'blue', label: 'Blue', color: '#7498ee' },
  { id: 'purple', label: 'Purple', color: '#a48be9' },
  { id: 'mint', label: 'Mint', color: '#68c5af' },
  { id: 'pink', label: 'Pink', color: '#e899be' },
  { id: 'orange', label: 'Orange', color: '#ecac79' },
]

export const backgroundOptions: { id: BackgroundChoice; label: string }[] = [
  { id: 'sky', label: 'Sky' },
  { id: 'aurora', label: 'Aurora' },
  { id: 'minimal', label: 'Minimal' },
  { id: 'custom', label: 'Custom' },
]


export const syncModeOptions: { id: SyncMode; label: string; detail: string }[] = [
  { id: 'cloud', label: 'Cloud', detail: '安全云端同步' },
  { id: 'local', label: 'Local', detail: '仅此设备' },
  { id: 'hybrid', label: 'Hybrid', detail: '兼顾云端与本地' },
]




export const notificationEventOptions: { id: NotificationEvent; label: string; description: string }[] = [
  { id: 'agentComplete', label: 'Agent 任务完成', description: '任务完成时提醒我' },
  { id: 'deviceOffline', label: '设备离线', description: '连接中断时立即提醒' },
  { id: 'automationFailure', label: '自动化失败', description: '流程出错时接收通知' },
  { id: 'budgetAlert', label: '预算提醒', description: '接近预设预算时提醒' },
  { id: 'securityAlert', label: '安全通知', description: '账户安全动态' },
]

export const notificationChannelOptions: { id: NotificationChannel; label: string }[] = [
  { id: 'desktop', label: 'Desktop' },
  { id: 'email', label: 'Email' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'webhook', label: 'Webhook' },
]


export const aboutInfo: AboutInfo = { product: 'Nexa', version, build: '2026.09.30' }
