import { defineStore } from 'pinia'
import { ref } from 'vue'
import defaultLayout from '../data/dashboard.json'
import { apiRequest } from '../api/client'
import type { DashboardLayout, DashboardRecord, WidgetDefinition } from '../types/widget'

function cloneWidgets(widgets: WidgetDefinition[]): WidgetDefinition[] {
  // Pinia exposes reactive proxies; JSON is the canonical layout wire format.
  return JSON.parse(JSON.stringify(widgets)) as WidgetDefinition[]
}

export const useDashboardStore = defineStore('dashboard', () => {
  const defaults = defaultLayout.widgets as WidgetDefinition[]
  const widgets = ref<WidgetDefinition[]>(cloneWidgets(defaults))
  const dashboard = ref<DashboardRecord | null>(null)
  const saving = ref(false)
  const error = ref('')
  let writeQueue = Promise.resolve()
  let generation = 0
  let pendingWrites = 0

  function reset() {
    generation++
    widgets.value = cloneWidgets(defaults)
    dashboard.value = null
    error.value = ''
  }

  function replace(widgetsFromApi: WidgetDefinition[]) {
    widgets.value = cloneWidgets(widgetsFromApi)
  }

  async function load(token: string) {
    const current = ++generation
    const record = await apiRequest<DashboardRecord>('/api/dashboard', {}, token)
    if (current !== generation) return
    dashboard.value = record
    replace(record.layout_json.widgets)
    error.value = ''
  }

  function save(token: string): Promise<void> {
    const layout: DashboardLayout = { widgets: cloneWidgets(widgets.value) }
    const current = generation
    pendingWrites++
    saving.value = true
    writeQueue = writeQueue.catch(() => undefined).then(async () => {
      try {
        if (current !== generation) return
        const record = await apiRequest<DashboardRecord>('/api/dashboard/layout', {
          method: 'PUT', body: JSON.stringify(layout),
        }, token)
        if (current === generation) {
          dashboard.value = record
          error.value = ''
        }
      } catch (cause) {
        if (current === generation) error.value = cause instanceof Error ? cause.message : '布局保存失败'
        throw cause
      } finally {
        pendingWrites--
        saving.value = pendingWrites > 0
      }
    })
    return writeQueue
  }

  return { widgets, dashboard, saving, error, defaults, reset, replace, load, save }
})
