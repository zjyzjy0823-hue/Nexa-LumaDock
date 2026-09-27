import { apiRequest } from '../api/client'
import type { Agent, AgentInput, AgentTask, AgentTaskStatus } from '../types/agent'

const root = '/api/v1/agents'
export const agentService = {
  list(token: string) { return apiRequest<Agent[]>(root, {}, token) },
  get(token: string, id: string) { return apiRequest<Agent>(`${root}/${id}`, {}, token) },
  create(token: string, data: AgentInput) { return apiRequest<Agent>(root, { method: 'POST', body: JSON.stringify(data) }, token) },
  update(token: string, id: string, data: Partial<AgentInput> & { enabled?: boolean }) { return apiRequest<Agent>(`${root}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/${id}`, { method: 'DELETE' }, token) },
  generateToken(token: string, id: string) { return apiRequest<{ agentId: string; token: string; last4: string; createdAt: string }>(`${root}/${id}/token`, { method: 'POST' }, token) },
  revokeToken(token: string, id: string) { return apiRequest<void>(`${root}/${id}/token`, { method: 'DELETE' }, token) },
  createTask(token: string, id: string, data: { title: string; description: string }) { return apiRequest<AgentTask>(`${root}/${id}/tasks`, { method: 'POST', body: JSON.stringify(data) }, token) },
  updateTask(token: string, id: string, taskId: string, data: { status: AgentTaskStatus }) { return apiRequest<AgentTask>(`${root}/${id}/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  removeTask(token: string, id: string, taskId: string) { return apiRequest<void>(`${root}/${id}/tasks/${taskId}`, { method: 'DELETE' }, token) },
}
