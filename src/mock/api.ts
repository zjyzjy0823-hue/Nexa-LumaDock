import type { ApiKey, ApiKeyExpiration, ApiRequest, ApiScope, ApiStat, ApiUsagePoint, Webhook } from '../types/api'

export const apiScopes: ApiScope[] = ['Devices', 'Agents', 'Data', 'Ledger', 'Automation', 'Read']
export const apiExpirations: { value: ApiKeyExpiration; label: string }[] = [
  { value: '30 days', label: '30 天' },
  { value: '90 days', label: '90 天' },
  { value: '1 year', label: '1 年' },
  { value: 'Never', label: '永不过期' },
]

export const apiStats: ApiStat[] = [
  { id: 'requests', label: '今日请求', value: '1,248', trend: '较昨日 +12.8%', tone: 'blue', sparkline: [22, 30, 25, 41, 37, 47, 42, 60, 53, 70] },
  { id: 'keys', label: '活跃密钥', value: '4', trend: '全部正常运行', tone: 'mint', sparkline: [38, 39, 39, 42, 42, 42, 43, 43, 43, 43] },
  { id: 'webhooks', label: 'Webhook', value: '6', trend: '已配置端点', tone: 'violet', sparkline: [23, 23, 32, 30, 40, 38, 44, 46, 46, 52] },
  { id: 'errors', label: '错误率', value: '0.3%', trend: '较昨日 −0.1%', tone: 'amber', sparkline: [62, 55, 64, 49, 45, 51, 40, 38, 34, 30] },
]

export const initialApiKeys: ApiKey[] = [
  { id: 'key-agent', name: 'Nexa Agent Key', status: 'active', maskedKey: 'sk_live_••••••••93kd', secret: 'sk_live_nexa_agent_demo_93kd', scopes: ['Devices', 'Agents', 'Data'], lastUsed: '2 分钟前', expiration: 'Never' },
  { id: 'key-mobile', name: 'Mobile App Key', status: 'active', maskedKey: 'sk_live_••••••••a7m2', secret: 'sk_live_mobile_app_demo_a7m2', scopes: ['Devices', 'Read'], lastUsed: '18 分钟前', expiration: '1 year' },
  { id: 'key-webhook', name: 'Webhook Key', status: 'active', maskedKey: 'sk_live_••••••••f4q8', secret: 'sk_live_webhook_demo_f4q8', scopes: ['Automation', 'Data'], lastUsed: '1 小时前', expiration: '90 days' },
  { id: 'key-development', name: 'Development Key', status: 'active', maskedKey: 'sk_test_••••••••dev6', secret: 'sk_test_development_demo_dev6', scopes: ['Ledger', 'Automation', 'Read'], lastUsed: '昨天 18:42', expiration: '30 days' },
]

export const recentApiRequests: ApiRequest[] = [
  { id: 'req-1', method: 'GET', path: '/api/v1/devices', status: 200, durationMs: 32, time: '10:42:08' },
  { id: 'req-2', method: 'POST', path: '/api/v1/agents/task', status: 201, durationMs: 84, time: '10:40:26' },
  { id: 'req-3', method: 'GET', path: '/api/v1/data/projects', status: 200, durationMs: 18, time: '10:38:12' },
  { id: 'req-4', method: 'POST', path: '/api/v1/ledger/records', status: 401, durationMs: 12, time: '10:31:44' },
  { id: 'req-5', method: 'GET', path: '/api/v1/automation/run', status: 200, durationMs: 46, time: '10:28:03' },
  { id: 'req-6', method: 'POST', path: '/api/v1/webhook/test', status: 500, durationMs: 120, time: '10:16:38' },
]

export const initialWebhooks: Webhook[] = [
  { id: 'hook-agent', name: 'Agent Task Completed', method: 'POST', url: 'https://example.com/webhook/agent', enabled: true },
  { id: 'hook-device', name: 'Device Offline', method: 'POST', url: 'https://example.com/webhook/device', enabled: true },
]

export const apiUsage: ApiUsagePoint[] = [
  { day: '周日', requests: 820, errors: 6 },
  { day: '周一', requests: 960, errors: 5 },
  { day: '周二', requests: 890, errors: 7 },
  { day: '周三', requests: 1130, errors: 4 },
  { day: '周四', requests: 1030, errors: 5 },
  { day: '周五', requests: 1370, errors: 3 },
  { day: '周六', requests: 1248, errors: 4 },
]
