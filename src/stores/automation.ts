import { defineStore } from 'pinia'
import { ref } from 'vue'
import { automationService } from '../services/automation'
import type { Workflow, WorkflowInput, Execution, AutomationRuntime } from '../types/automation'
export const useAutomationStore = defineStore('automation', () => {
  const items = ref<Workflow[]>([]), executions = ref<Execution[]>([]), loading = ref(false), loaded = ref(false), loadedAt = ref(0), error = ref('')
  let sequence = 0
  const runtimeError = ref(''), runtimes = ref<Record<string, AutomationRuntime>>({}), refreshing = ref(false)
  const requestIds = new Map<string, string>()
  async function refreshRuntime(token: string) {
    if (refreshing.value) return
    const current = sequence, definitions = [...items.value]; refreshing.value = true
    try {
      const results = await Promise.allSettled(definitions.map(async item => ({ id: item.id,
        history: await automationService.executions(token, item.id), runtime: await automationService.runtime(token, item.id) })))
      if (current !== sequence) return
      const histories: Execution[] = [], states: Record<string, AutomationRuntime> = {}; let unavailable = false
      for (const result of results) {
        if (result.status === 'fulfilled') { histories.push(...result.value.history); states[result.value.id] = result.value.runtime }
        else unavailable = true
      }
      executions.value = histories.sort((a, b) => b.createdAt.localeCompare(a.createdAt)); runtimes.value = states
      runtimeError.value = unavailable ? 'Core 当前不可用，执行记录无法刷新。自动化定义仍可在本地编辑；连接恢复后可刷新。' : ''
    } finally { if (current === sequence) refreshing.value = false }
  }
  async function mutate<T>(action: () => Promise<T>): Promise<T> {
    if (loading.value) throw new Error('操作正在进行中')
    const current = sequence; loading.value = true; error.value = ''
    try { return await action() }
    catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : '操作失败'; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function load(token: string, force = false) {
    if (!force && (loading.value || (loaded.value && Date.now() - loadedAt.value < 60_000))) return
    const current = ++sequence; loading.value = true; refreshing.value = false; error.value = ''
    try { const result = await automationService.list(token); if (current === sequence) { items.value = result; loaded.value = true; loadedAt.value = Date.now(); await refreshRuntime(token) } }
    catch (cause) { if (current === sequence) { items.value = []; executions.value = []; loaded.value = false; error.value = cause instanceof Error ? cause.message : '加载失败' }; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function create(token: string, payload: WorkflowInput) { return mutate(async () => { const current = sequence; const item = await automationService.create(token, payload); if (current === sequence) items.value.unshift(item); return item }) }
  async function update(token: string, id: string, payload: Partial<WorkflowInput>) { return mutate(async () => { const current = sequence; const item = await automationService.update(token, id, payload); if (current === sequence) items.value = items.value.map(old => old.id === id ? item : old) }) }
  async function remove(token: string, id: string) { return mutate(async () => { const current = sequence; await automationService.remove(token, id); if (current === sequence) { items.value = items.value.filter(item => item.id !== id); executions.value = executions.value.filter(item => item.workflowId !== id) } }) }
  async function testRun(token: string, id: string) { return mutate(async () => { const current = sequence; const item = await automationService.testRun(token, id); if (current === sequence) executions.value.unshift(item) }) }
  async function run(token: string, id: string) { return mutate(async () => {
    const current = sequence, requestId = requestIds.get(id) ?? crypto.randomUUID(); requestIds.set(id, requestId)
    const item = await automationService.run(token, id, requestId)
    if (current === sequence) { requestIds.delete(id); executions.value = [item, ...executions.value.filter(old => old.id !== item.id)] }
    return item
  }) }
  function reset() { ++sequence; items.value = []; executions.value = []; loading.value = false; loaded.value = false; loadedAt.value = 0; error.value = ''; runtimeError.value = ''; runtimes.value = {}; refreshing.value = false; requestIds.clear() }
  function invalidate() { loaded.value = false; loadedAt.value = 0 }
  return { items, executions, loading, loaded, error, load, create, update, remove, testRun, run, reset, invalidate, runtimeError, runtimes, refreshRuntime, refreshing }
})
