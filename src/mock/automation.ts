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

export const workflowOptions: Record<WorkflowNode['kind'], string[]> = {
  WHEN: ['电脑上线', '每天 08:00', '文件变化', '收到 Webhook', 'Agent 任务完成', '系统事件'],
  IF: ['时间 > 22:00', '设备已连接', '网络可用', '始终执行'],
  DO: ['启动备份', '发送通知', '同步 NAS', '运行 Agent'],
}

export const triggerLibrary: TriggerItem[] = [
  { id: 'device', title: '设备事件', description: '上线、离线与状态变化', icon: 'notification', example: '电脑上线' },
  { id: 'schedule', title: '定时任务', description: '按时间或周期启动', icon: 'calendar', example: '每天 08:00' },
  { id: 'webhook', title: 'Webhook', description: '接收外部应用事件', icon: 'webhook', example: '收到 Webhook' },
  { id: 'agent', title: 'Agent 事件', description: '任务完成与状态变化', icon: 'agent', example: 'Agent 任务完成' },
]
