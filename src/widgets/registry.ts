import type { Component } from 'vue'
import QuickAccessWidget from '../components/widgets/QuickAccessWidget.vue'
import ClockWeatherWidget from '../components/widgets/ClockWeatherWidget.vue'
import DevicesWidget from '../components/widgets/DevicesWidget.vue'
import AgentsWidget from '../components/widgets/AgentsWidget.vue'
import LedgerWidget from '../components/widgets/LedgerWidget.vue'
import SystemWidget from '../components/widgets/SystemWidget.vue'
import CollectionsWidget from '../components/widgets/CollectionsWidget.vue'
import AutomationWidget from '../components/widgets/AutomationWidget.vue'
import NotesWidget from '../components/widgets/NotesWidget.vue'

export interface WidgetRegistration {
  component: Component
  minWidth: number
  minHeight: number
}

// Add a component here and a widget entry in dashboard.json; the renderer stays unchanged.
export const widgetRegistry: Record<string, WidgetRegistration> = {
  'quick-access': { component: QuickAccessWidget, minWidth: 300, minHeight: 180 },
  clock: { component: ClockWeatherWidget, minWidth: 190, minHeight: 200 },
  device: { component: DevicesWidget, minWidth: 300, minHeight: 190 },
  agent: { component: AgentsWidget, minWidth: 255, minHeight: 175 },
  ledger: { component: LedgerWidget, minWidth: 275, minHeight: 180 },
  system: { component: SystemWidget, minWidth: 310, minHeight: 180 },
  collections: { component: CollectionsWidget, minWidth: 300, minHeight: 170 },
  automation: { component: AutomationWidget, minWidth: 225, minHeight: 160 },
  notes: { component: NotesWidget, minWidth: 180, minHeight: 160 },
}

export function minimumFor(type: string) {
  return widgetRegistry[type] ?? { minWidth: 180, minHeight: 160 }
}
