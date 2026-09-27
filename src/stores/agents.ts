import { defineStore } from 'pinia'
import { ref } from 'vue'
import { agentService } from '../services/agents'
import type { Agent, AgentInput, AgentTaskStatus } from '../types/agent'

export const useAgentsStore = defineStore('agents', () => {
  const agents = ref<Agent[]>([])
  const loading = ref(false)
  const error = ref('')
  let sequence = 0

  async function load(token: string) {
    const current = ++sequence
    loading.value = true
    error.value = ''
    try {
      const items = await agentService.list(token)
      if (current === sequence) agents.value = items
    } catch (cause) {
      if (current === sequence) error.value = cause instanceof Error ? cause.message : '智能体加载失败'
    } finally { if (current === sequence) loading.value = false }
  }
  async function refreshOne(token: string, id: string) {
    const item = await agentService.get(token, id)
    agents.value = agents.value.map(old => old.id === id ? item : old)
    return item
  }
  async function create(token: string, data: AgentInput) {
    const item = await agentService.create(token, data)
    agents.value.unshift(item)
    return item
  }
  async function update(token: string, id: string, data: Partial<AgentInput> & { enabled?: boolean }) {
    const item = await agentService.update(token, id, data)
    agents.value = agents.value.map(old => old.id === id ? item : old)
    return item
  }
  async function remove(token: string, id: string) {
    await agentService.remove(token, id)
    agents.value = agents.value.filter(item => item.id !== id)
  }
  async function createTask(token: string, id: string, title: string, description = '') {
    await agentService.createTask(token, id, { title, description })
    return refreshOne(token, id)
  }
  async function updateTask(token: string, id: string, taskId: string, status: AgentTaskStatus) {
    await agentService.updateTask(token, id, taskId, { status })
    return refreshOne(token, id)
  }
  async function removeTask(token: string, id: string, taskId: string) {
    await agentService.removeTask(token, id, taskId)
    return refreshOne(token, id)
  }
  function reset() { ++sequence; agents.value = []; loading.value = false; error.value = '' }
  return { agents, loading, error, load, refreshOne, create, update, remove, createTask, updateTask, removeTask, reset }
})
