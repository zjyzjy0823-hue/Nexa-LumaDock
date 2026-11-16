import { apiRequest, ApiError } from '../api/client'
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
  async run(token: string, id: string, requestId: string) {
    try { return await apiRequest<Execution>(`${root}/${id}/run`, { method: 'POST', body: JSON.stringify({ request_id: requestId }) }, token) }
    catch (error) {
      if (error instanceof ApiError && error.status === 422) throw new ApiError(422, '此自动化暂时无法运行，请检查并完善执行动作配置后重试。')
      throw error
    }
  },
  testRun(token: string, id: string) { return apiRequest<Execution>(`${root}/${id}/test-run`, { method: 'POST' }, token) },
}
