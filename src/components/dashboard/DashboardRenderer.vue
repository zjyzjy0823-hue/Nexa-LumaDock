<script setup lang="ts">
import { computed } from 'vue'
import ResizableWidget from '../ui/ResizableWidget.vue'
import GlassCard from '../ui/GlassCard.vue'
import { widgetRegistry } from '../../widgets/registry'
import type { WidgetDefinition } from '../../types/widget'

const props = defineProps<{
  widgets: WidgetDefinition[]
  editing: boolean
  activeWidget: string | null
  desktop: boolean
  scale: number
}>()
const emit = defineEmits<{
  moveStart: [id: string, event: PointerEvent]
  resizeStart: [id: string, event: PointerEvent]
  moveKey: [id: string, event: KeyboardEvent]
  resizeKey: [id: string, event: KeyboardEvent]
  reset: [id: string]
  action: [message: string]
}>()

const boardHeight = computed(() => props.desktop
  ? `${Math.max(0, ...props.widgets.map(widget => widget.position.y + widget.size.height)) * props.scale}px`
  : undefined)

function frameStyle(widget: WidgetDefinition) {
  return props.desktop
    ? { left: `${widget.position.x * props.scale}px`, top: `${widget.position.y * props.scale}px` }
    : undefined
}

function actionFor(id: string, event: string, value?: string) {
  if (id === 'quick-access' && event === 'select') emit('action', `${value?.toUpperCase()} 连接功能即将推出。`)
  else emit('action', '快捷方式创建功能即将推出。')
}
</script>

<template>
  <div class="dashboard-grid" :class="{ 'dashboard-grid--editing': editing }" :style="{ height: boardHeight }" aria-label="仪表盘组件">
    <ResizableWidget
      v-for="widget in widgets"
      :id="widget.id"
      :key="widget.id"
      class="widget"
      :class="[`widget--${widget.id}`, { 'widget--active': activeWidget === widget.id }]"
      :style="frameStyle(widget)"
      :editing="editing"
      :display-width="widget.size.width * scale"
      :display-height="widget.size.height * scale"
      :base-width="widget.size.width"
      :base-height="widget.size.height"
      :name="widget.title"
      @move-start="emit('moveStart', widget.id, $event)"
      @resize-start="emit('resizeStart', widget.id, $event)"
      @move-key="emit('moveKey', widget.id, $event)"
      @resize-key="emit('resizeKey', widget.id, $event)"
      @reset="emit('reset', widget.id)"
    >
      <component
        :is="widgetRegistry[widget.type].component"
        v-if="widgetRegistry[widget.type]"
        :config="widget.config"
        :datasource="widget.datasource"
        @add="actionFor(widget.id, 'add')"
        @select="(name: string) => actionFor(widget.id, 'select', name)"
      />
      <GlassCard v-else :title="widget.title"><p>尚未安装 {{ widget.type }} 组件。</p></GlassCard>
    </ResizableWidget>
  </div>
</template>

<style scoped>
.dashboard-grid { position: relative; width: 100%; }
.dashboard-grid > .widget { position: absolute; min-width: 0; scroll-margin-top: 24px; border-radius: var(--radius-card); }
.dashboard-grid > .widget:hover { z-index: 11; }
.dashboard-grid > .widget.widget--active { z-index: 12; }
.widget--focused { outline: 2px solid rgba(211,231,255,.9); outline-offset: 3px; }
@media (max-width: 1279px) {
  .dashboard-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; align-items: stretch; }
  .dashboard-grid > .widget { position: relative; height: 248px; }
  .dashboard-grid > .widget--quick-access, .dashboard-grid > .widget--clock, .dashboard-grid > .widget--devices { height: 299px; }
  .dashboard-grid > .widget--collections { height: 225px; }
  .dashboard-grid > .widget--notes { height: 216px; }
}
@media (max-width: 900px) { .dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) {
  .dashboard-grid { gap: 14px; }
  .dashboard-grid > .widget--collections { height: 345px; }
}
</style>
