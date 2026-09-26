export type AutomationIcon =
  | 'backup' | 'nas' | 'notification' | 'agent' | 'server' | 'calendar'
  | 'file' | 'webhook' | 'workflow' | 'shield' | 'cloud' | 'database'

export type AutomationStatus = 'success' | 'failed' | 'never'

export interface AutomationItem {
  id: string
  title: string
  description: string
  icon: AutomationIcon
  enabled: boolean
  trigger: string
  lastExecution: string
  lastExecutionStatus: AutomationStatus
}

export interface WorkflowNode {
  kind: 'WHEN' | 'IF' | 'DO'
  label: string
  text: string
  detail: string
}

export interface ExecutionItem {
  id: string
  title: string
  description: string
  time: string
  status: 'success' | 'failed'
}

export interface TriggerItem {
  id: string
  title: string
  description: string
  icon: AutomationIcon
  example: string
}

export const automationSummary = {
  todayExecutions: 42,
  successRate: 98,
  errorCount: 1,
} as const

export const automations: AutomationItem[] = [
  { id: 'daily-backup', title: '每日备份', description: '每天自动备份数据到 NAS', icon: 'backup', enabled: true, trigger: '每天 22:30', lastExecution: '今天 22:30', lastExecutionStatus: 'success' },
  { id: 'nas-sync', title: '同步 NAS', description: '同步工作文件与家庭存储', icon: 'nas', enabled: true, trigger: '文件变化时', lastExecution: '今天 21:45', lastExecutionStatus: 'success' },
  { id: 'device-online', title: '设备上线通知', description: '新设备上线时发送即时提醒', icon: 'notification', enabled: true, trigger: '设备上线时', lastExecution: '今天 19:28', lastExecutionStatus: 'success' },
  { id: 'agent-finished', title: 'Agent 任务完成提醒', description: '在智能体完成任务后推送结果', icon: 'agent', enabled: true, trigger: 'Agent 任务完成', lastExecution: '今天 18:06', lastExecutionStatus: 'success' },
  { id: 'server-check', title: '服务器巡检', description: '定时检查服务器运行状态', icon: 'server', enabled: true, trigger: '每小时', lastExecution: '今天 17:00', lastExecutionStatus: 'failed' },
  { id: 'calendar-brief', title: '日程摘要', description: '每天早晨汇总当天的日程', icon: 'calendar', enabled: true, trigger: '每天 08:00', lastExecution: '今天 08:00', lastExecutionStatus: 'success' },
  { id: 'file-organize', title: '文件自动归档', description: '整理下载文件夹中的新文件', icon: 'file', enabled: true, trigger: '文件变化时', lastExecution: '昨天 23:15', lastExecutionStatus: 'success' },
  { id: 'cloud-export', title: '云端数据导出', description: '将重要数据同步至云端', icon: 'cloud', enabled: true, trigger: '每周日', lastExecution: '周日 20:00', lastExecutionStatus: 'success' },
  { id: 'webhook-alert', title: 'Webhook 通知', description: '接收外部服务的事件通知', icon: 'webhook', enabled: false, trigger: 'Webhook 请求', lastExecution: '3 天前', lastExecutionStatus: 'success' },
  { id: 'security-audit', title: '安全检查', description: '检查设备的登录与异常事件', icon: 'shield', enabled: false, trigger: '每天 09:00', lastExecution: '4 天前', lastExecutionStatus: 'success' },
  { id: 'database-clean', title: '数据整理', description: '清理重复记录与失效链接', icon: 'database', enabled: false, trigger: '每月 1 日', lastExecution: '尚未执行', lastExecutionStatus: 'never' },
  { id: 'weekly-report', title: '每周报告', description: '汇总本周的个人数字活动', icon: 'workflow', enabled: false, trigger: '每周五', lastExecution: '尚未执行', lastExecutionStatus: 'never' },
]

export const workflowExample: WorkflowNode[] = [
  { kind: 'WHEN', label: '触发条件', text: '电脑上线', detail: '设备事件' },
  { kind: 'IF', label: '判断条件', text: '时间 > 22:00', detail: '仅在夜间执行' },
  { kind: 'DO', label: '执行动作', text: '启动备份', detail: '备份至 NAS' },
]

export const workflowOptions: Record<WorkflowNode['kind'], string[]> = {
  WHEN: ['电脑上线', '每天 08:00', '文件变化', '收到 Webhook', 'Agent 任务完成', '系统事件'],
  IF: ['时间 > 22:00', '设备已连接', '网络可用', '始终执行'],
  DO: ['启动备份', '发送通知', '同步 NAS', '运行 Agent'],
}

export const executions: ExecutionItem[] = [
  { id: 'ex-1', title: '每日备份', description: '所有文件已安全备份', time: '今天 22:30', status: 'success' },
  { id: 'ex-2', title: 'NAS 同步', description: '工作空间同步完成', time: '今天 21:45', status: 'success' },
  { id: 'ex-3', title: '服务器巡检', description: '连接超时，等待下次重试', time: '今天 17:00', status: 'failed' },
  { id: 'ex-4', title: '日程摘要', description: '今日摘要已发送', time: '今天 08:00', status: 'success' },
]

export const triggerLibrary: TriggerItem[] = [
  { id: 'device', title: '设备事件', description: '上线、离线与状态变化', icon: 'notification', example: '电脑上线' },
  { id: 'schedule', title: '定时任务', description: '按时间或周期启动', icon: 'calendar', example: '每天 08:00' },
  { id: 'file', title: '文件变化', description: '监控文件与目录', icon: 'file', example: '文件变化' },
  { id: 'webhook', title: 'Webhook', description: '接收外部应用事件', icon: 'webhook', example: '收到 Webhook' },
  { id: 'agent', title: 'Agent 事件', description: '任务完成与状态变化', icon: 'agent', example: 'Agent 任务完成' },
  { id: 'system', title: '系统事件', description: '系统与网络状态', icon: 'server', example: '系统事件' },
]
