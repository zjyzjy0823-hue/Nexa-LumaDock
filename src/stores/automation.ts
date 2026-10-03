import { defineStore } from 'pinia'
import { ref } from 'vue'
import { automationService } from '../services/automation'
import type { Workflow, WorkflowInput, Execution } from '../types/automation'
export const useAutomationStore = defineStore('automation', () => {
  const items = ref<Workflow[]>([]), executions = ref<Execution[]>([]), loading = ref(false), loaded = ref(false), loadedAt = ref(0), error = ref('')
  let sequence = 0
  async function mutate<T>(action: () => Promise<T>): Promise<T> {
    if (loading.value) throw new Error('操作正在进行中')
    const current = sequence; loading.value = true; error.value = ''
    try { return await action() }
    catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : '操作失败'; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function load(token: string, force = false) {
    if (!force && (loading.value || (loaded.value && Date.now() - loadedAt.value < 60_000))) return
    const current = ++sequence; loading.value = true; error.value = ''
    try { const result = await automationService.list(token); const history = await Promise.all(result.map(item => automationService.executions(token, item.id))); if (current === sequence) { items.value = result; executions.value = history.flat(); loaded.value = true; loadedAt.value = Date.now() } }
    catch (cause) { if (current === sequence) { items.value = []; executions.value = []; loaded.value = false; error.value = cause instanceof Error ? cause.message : '加载失败' }; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function create(token: string, payload: WorkflowInput) { return mutate(async () => { const current = sequence; const item = await automationService.create(token, payload); if (current === sequence) items.value.unshift(item); return item }) }
  async function update(token: string, id: string, payload: Partial<WorkflowInput>) { return mutate(async () => { const current = sequence; const item = await automationService.update(token, id, payload); if (current === sequence) items.value = items.value.map(old => old.id === id ? item : old) }) }
  async function remove(token: string, id: string) { return mutate(async () => { const current = sequence; await automationService.remove(token, id); if (current === sequence) { items.value = items.value.filter(item => item.id !== id); executions.value = executions.value.filter(item => item.workflowId !== id) } }) }
  async function testRun(token: string, id: string) { return mutate(async () => { const current = sequence; const item = await automationService.testRun(token, id); if (current === sequence) executions.value.unshift(item) }) }
  function reset() { ++sequence; items.value = []; executions.value = []; loading.value = false; loaded.value = false; loadedAt.value = 0; error.value = '' }
  function invalidate() { loaded.value = false; loadedAt.value = 0 }
  return { items, executions, loading, loaded, error, load, create, update, remove, testRun, reset, invalidate }
})
