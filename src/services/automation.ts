import { apiRequest } from '../api/client'
import type { Workflow, WorkflowInput, Execution, AutomationRuntime } from '../types/automation'
const root = '/api/v1/automations'
export const automationService = {
  list(token: string) { return apiRequest<Workflow[]>(root, {}, token) },
  create(token: string, data: WorkflowInput) { return apiRequest<Workflow>(root, { method: 'POST', body: JSON.stringify(data) }, token) },
  update(token: string, id: string, data: Partial<WorkflowInput>) { return apiRequest<Workflow>(`${root}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/${id}`, { method: 'DELETE' }, token) },
  executions(token: string, id: string) { return apiRequest<Execution[]>(`${root}/${id}/executions?runtime=true`, {}, token) },
  runtime(token: string, id: string) { return apiRequest<AutomationRuntime>(`${root}/${id}/runtime`, {}, token) },
  detail(token: string, id: string, executionId: string) { return apiRequest<Execution>(`${root}/${id}/executions/${executionId}`, {}, token) },
  run(token: string, id: string, requestId: string) { return apiRequest<Execution>(`${root}/${id}/run`, { method: 'POST', body: JSON.stringify({ request_id: requestId }) }, token) },
  testRun(token: string, id: string) { return apiRequest<Execution>(`${root}/${id}/test-run`, { method: 'POST' }, token) },
}
