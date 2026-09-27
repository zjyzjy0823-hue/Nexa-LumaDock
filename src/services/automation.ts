import { apiRequest } from '../api/client'
import type { Workflow, WorkflowInput, Execution } from '../types/automation'
const root = '/api/v1/automations'
export const automationService = {
  list(token: string) { return apiRequest<Workflow[]>(root, {}, token) },
  create(token: string, data: WorkflowInput) { return apiRequest<Workflow>(root, { method: 'POST', body: JSON.stringify(data) }, token) },
  update(token: string, id: string, data: Partial<WorkflowInput>) { return apiRequest<Workflow>(`${root}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/${id}`, { method: 'DELETE' }, token) },
  executions(token: string, id: string) { return apiRequest<Execution[]>(`${root}/${id}/executions`, {}, token) },
  testRun(token: string, id: string) { return apiRequest<Execution>(`${root}/${id}/test-run`, { method: 'POST' }, token) },
}
