export const navigation = [
  { section: '', items: [{ page: 'Home', label: '今天', icon: 'today' }] },
  { section: '资料', items: [
    { page: 'Ledger', label: '账本', icon: 'ledger' },
    { page: 'Websites', label: '网站', icon: 'globe' },
    { page: 'Data', label: '数据', icon: 'data' },
    { page: 'Devices', label: '设备', icon: 'device' },
  ] },
  { section: '协同', items: [
    { page: 'Space', label: '共享空间', icon: 'shield' },
    { page: 'Chat', label: 'Agent', icon: 'chat' },
    { page: 'Automation', label: '任务', icon: 'tasks' },
  ] },
] as const

export const footer = [
  { page: 'API', label: '集成与 API', icon: 'api' },
  { page: 'Settings', label: '设置', icon: 'settings' },
] as const

export const mobileTabs = [
  { page: 'Home', label: '今天', icon: 'today' },
  { page: 'Chat', label: '对话', icon: 'chat' },
  { page: '+', label: '快速新增', icon: 'plus' },
  { page: 'Ledger', label: '资料', icon: 'layers' },
  { page: 'Automation', label: '任务', icon: 'tasks' },
] as const

export const libraryItems = navigation[1].items
