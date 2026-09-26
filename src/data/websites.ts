export type WebsiteGroup = 'frequent' | 'workspace' | 'personal'
export type WebsiteCategory = 'all' | 'daily' | 'work' | 'ai' | 'media' | 'personal'

export type WebsiteLogo =
  | 'chatgpt' | 'github' | 'gmail' | 'notion' | 'youtube' | 'figma'
  | 'linear' | 'vercel' | 'cloudflare' | 'excalidraw' | 'nas'
  | 'home' | 'immich' | 'jellyfin' | 'generic'

export interface Website {
  id: string
  name: string
  subtitle: string
  group: WebsiteGroup
  category: Exclude<WebsiteCategory, 'all'>
  logo: WebsiteLogo
  href: string
}

export const websiteGroups: { id: WebsiteGroup; title: string; description: string }[] = [
  { id: 'frequent', title: '常用网站', description: '每天都会用到的快捷入口' },
  { id: 'workspace', title: '工作与创作', description: '想法、项目与发布工具' },
  { id: 'personal', title: '私人空间', description: '你自己的应用和服务' },
]

export const websiteCategories: { id: WebsiteCategory; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'daily', label: '日常' },
  { id: 'work', label: '工作' },
  { id: 'ai', label: 'AI 工具' },
  { id: 'media', label: '影音' },
  { id: 'personal', label: '私人服务' },
]

export const mockWebsites: Website[] = [
  { id: 'chatgpt', name: 'ChatGPT', subtitle: '随时开始新的对话', group: 'frequent', category: 'ai', logo: 'chatgpt', href: 'https://chatgpt.com' },
  { id: 'github', name: 'GitHub', subtitle: '代码、项目与灵感', group: 'frequent', category: 'work', logo: 'github', href: 'https://github.com' },
  { id: 'gmail', name: 'Gmail', subtitle: '收件箱与重要邮件', group: 'frequent', category: 'daily', logo: 'gmail', href: 'https://mail.google.com' },
  { id: 'notion', name: 'Notion', subtitle: '笔记与知识库', group: 'frequent', category: 'work', logo: 'notion', href: 'https://notion.so' },
  { id: 'youtube', name: 'YouTube', subtitle: '视频与订阅内容', group: 'frequent', category: 'media', logo: 'youtube', href: 'https://youtube.com' },
  { id: 'figma', name: 'Figma', subtitle: '设计文件与原型', group: 'frequent', category: 'work', logo: 'figma', href: 'https://figma.com' },
  { id: 'linear', name: 'Linear', subtitle: '产品计划与任务', group: 'workspace', category: 'work', logo: 'linear', href: 'https://linear.app' },
  { id: 'vercel', name: 'Vercel', subtitle: '部署与项目预览', group: 'workspace', category: 'work', logo: 'vercel', href: 'https://vercel.com' },
  { id: 'cloudflare', name: 'Cloudflare', subtitle: '域名与网络服务', group: 'workspace', category: 'work', logo: 'cloudflare', href: 'https://dash.cloudflare.com' },
  { id: 'excalidraw', name: 'Excalidraw', subtitle: '快速画出新想法', group: 'workspace', category: 'work', logo: 'excalidraw', href: 'https://excalidraw.com' },
  { id: 'nas', name: '家庭 NAS', subtitle: '文件、备份与共享', group: 'personal', category: 'personal', logo: 'nas', href: 'http://nas.local' },
  { id: 'home', name: 'Home Assistant', subtitle: '家的自动化控制台', group: 'personal', category: 'personal', logo: 'home', href: 'http://homeassistant.local:8123' },
  { id: 'immich', name: 'Immich', subtitle: '私人照片与回忆', group: 'personal', category: 'personal', logo: 'immich', href: 'http://immich.local' },
  { id: 'jellyfin', name: 'Jellyfin', subtitle: '我的影音资料库', group: 'personal', category: 'media', logo: 'jellyfin', href: 'http://jellyfin.local' },
]
