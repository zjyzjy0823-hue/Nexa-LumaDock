export type AgentStatus = 'running' | 'idle' | 'error' | 'offline' | 'disabled'
export type AgentTaskStatus = 'running' | 'completed' | 'queued' | 'failed'
export type AgentCapabilityIcon = 'search' | 'file' | 'globe' | 'database' | 'code' | 'calendar'

export interface AgentTask {
  id: string
  title: string
  description: string
  time: string
  status: AgentTaskStatus
  createdAt: string
  updatedAt: string
  claimedAt: string | null
  completedAt: string | null
  result: { text?: string } | null
  errorMessage: string | null
}

export interface AgentCapability {
  title: string
  description: string
  icon: AgentCapabilityIcon
  tone: 'blue' | 'violet' | 'mint' | 'amber'
}

export interface AgentLog {
  time: string
  createdAt: string
  eventType: string | null
  taskId: string | null
  level: 'success' | 'info' | 'warning' | 'error'
  message: string
}

export interface AgentApiCall {
  method: string
  endpoint: string
  time: string
  duration: string
  status: number
}

export interface Agent {
  dataScopes: string[]
  id: string
  name: string
  role: string
  description: string
  status: AgentStatus
  enabled: boolean
  avatar: 'spark' | 'orbit' | 'wave' | 'chart' | 'sun'
  model: string
  workspace: string
  successRate: string
  callsToday: number
  tasksToday: number
  uptime: string
  lastActive: string
  lastSeenAt: string | null
  runtimeType: string | null
  runtimeVersion: string | null
  runtimeInstance: string | null
  currentTaskId: string | null
  lastError: string | null
  tokenLast4: string | null
  tokenCreatedAt: string | null
  capabilities: AgentCapability[]
  tasks: AgentTask[]
  logs: AgentLog[]
  apiCalls: AgentApiCall[]
  createdAt: string
  updatedAt: string
}

export type AgentInput = Pick<Agent, 'name' | 'role' | 'description' | 'model' | 'workspace' | 'avatar' | 'dataScopes'>
