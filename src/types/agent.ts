export type AgentStatus = 'running' | 'idle' | 'offline'
export type AgentTaskStatus = 'running' | 'completed' | 'queued'
export type AgentCapabilityIcon = 'search' | 'file' | 'globe' | 'database' | 'code' | 'calendar'

export interface AgentTask {
  id: string
  title: string
  description: string
  time: string
  status: AgentTaskStatus
  createdAt: string
  updatedAt: string
}

export interface AgentCapability {
  title: string
  description: string
  icon: AgentCapabilityIcon
  tone: 'blue' | 'violet' | 'mint' | 'amber'
}

export interface AgentLog {
  time: string
  level: 'success' | 'info' | 'warning'
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
  capabilities: AgentCapability[]
  tasks: AgentTask[]
  logs: AgentLog[]
  apiCalls: AgentApiCall[]
  createdAt: string
  updatedAt: string
}

export type AgentInput = Pick<Agent, 'name' | 'role' | 'description' | 'model' | 'workspace' | 'avatar'>
