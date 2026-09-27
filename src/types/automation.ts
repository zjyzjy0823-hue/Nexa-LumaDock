export type AutomationIcon = 'backup' | 'nas' | 'notification' | 'agent' | 'server' | 'calendar' | 'file' | 'webhook' | 'workflow' | 'shield' | 'cloud' | 'database'
export interface WorkflowNode { kind: 'WHEN' | 'IF' | 'DO'; label: string; text: string; detail: string }
export interface AutomationItem { id: string; title: string; description: string; icon: AutomationIcon; enabled: boolean; trigger: string; lastExecution: string; lastExecutionStatus: 'success' | 'failed' | 'never' }
export interface ExecutionItem { id: string; title: string; description: string; time: string; status: 'success' | 'failed' }
export interface TriggerItem { id: string; title: string; description: string; icon: AutomationIcon; example: string }
export interface Workflow { id: string; name: string; description: string; enabled: boolean; triggerType: 'manual' | 'schedule' | 'device_status' | 'agent_event' | 'webhook'; triggerConfigJson: Record<string, unknown>; workflowJson: WorkflowNode[]; createdAt: string; updatedAt: string }
export interface Execution { id: string; workflowId: string; status: 'queued' | 'running' | 'success' | 'failed'; startedAt: string; finishedAt: string | null; message: string; resultJson: Record<string, unknown> }
export interface WorkflowInput { name: string; description: string; enabled: boolean; trigger_type: Workflow['triggerType']; trigger_config_json: Record<string, unknown>; workflow_json: WorkflowNode[] }
