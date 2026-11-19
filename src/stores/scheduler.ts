/**
 * 统一定时任务（Cron）Pinia Store：管理 OpenClaw / Hermes 远端原生任务聚合与运行账本。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  jobRefKey,
  schedulerService,
  type OwnerInstance,
  type RemoteCronCreatePayload,
  type RemoteCronRunsResponse,
  type UnifiedJob,
  type UnifiedJobRun,
} from '../services/scheduler'

export const useSchedulerStore = defineStore('scheduler', () => {
  const instances = ref<OwnerInstance[]>([])
  const allJobs = ref<UnifiedJob[]>([])
  const runsByKey = ref<Record<string, RemoteCronRunsResponse>>({})
  const loading = ref(false)
  const error = ref('')

  const remoteJobs = computed(() => allJobs.value.filter(j => j.ref.ownerType !== 'studiolo'))
  const remoteInstances = computed(() => instances.value.filter(i => i.ownerType !== 'studiolo'))
  const onlineRemoteInstances = computed(() =>
    remoteInstances.value.filter(i => i.status === 'online' && i.capabilities.supported),
  )

  function reset() {
    instances.value = []
    allJobs.value = []
    runsByKey.value = {}
    loading.value = false
    error.value = ''
  }

  async function load(token: string) {
    loading.value = true
    error.value = ''
    try {
      const overview = await schedulerService.listJobs(token, 'all')
      instances.value = Array.isArray(overview?.instances) ? overview.instances : []
      allJobs.value = Array.isArray(overview?.jobs) ? overview.jobs : []
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '加载远端定时任务失败'
    } finally {
      loading.value = false
    }
  }

  async function loadRuns(token: string, job: UnifiedJob, limit = 20) {
    const key = jobRefKey(job.ref)
    const res = await schedulerService.listJobRuns(token, job.ref, limit)
    runsByKey.value = { ...runsByKey.value, [key]: res }
    return res
  }

  async function createRemote(token: string, payload: RemoteCronCreatePayload): Promise<UnifiedJob> {
    const created = await schedulerService.createRemoteJob(token, payload)
    await load(token)
    return created
  }

  async function togglePause(token: string, job: UnifiedJob): Promise<UnifiedJob> {
    const updated = await schedulerService.pauseRemoteJob(token, job.ref, job.enabled)
    const key = jobRefKey(updated.ref)
    allJobs.value = allJobs.value.map(item => (jobRefKey(item.ref) === key ? updated : item))
    return updated
  }

  async function runNow(token: string, job: UnifiedJob): Promise<UnifiedJobRun> {
    const reqId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `cron-${Date.now()}`
    const run = await schedulerService.runRemoteJob(token, job.ref, reqId)
    await loadRuns(token, job).catch(() => {})
    return run
  }

  async function removeRemote(token: string, job: UnifiedJob) {
    await schedulerService.deleteRemoteJob(token, job.ref)
    const key = jobRefKey(job.ref)
    allJobs.value = allJobs.value.filter(item => jobRefKey(item.ref) !== key)
  }

  return {
    instances,
    allJobs,
    remoteJobs,
    remoteInstances,
    onlineRemoteInstances,
    runsByKey,
    loading,
    error,
    reset,
    load,
    loadRuns,
    createRemote,
    togglePause,
    runNow,
    removeRemote,
  }
})
