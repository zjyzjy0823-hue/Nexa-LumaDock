export interface WidgetPosition { x: number; y: number }
export interface WidgetSize { width: number; height: number }
export interface WidgetDefinition {
  id: string
  type: string
  title: string
  icon: string
  position: WidgetPosition
  size: WidgetSize
  config: Record<string, unknown>
  datasource: string | null
}
export interface DashboardLayout { widgets: WidgetDefinition[] }
export interface DashboardRecord {
  id: number
  user_id: number
  name: string
  layout_json: DashboardLayout
  created_at: string
  updated_at: string
}
export interface User {
  id: number
  username: string
  avatar: string | null
  created_at: string
}
