export type AgentStatus = 'running' | 'idle' | 'offline'
export type AgentTaskStatus = 'running' | 'completed' | 'queued'
export type AgentCapabilityIcon = 'search' | 'file' | 'globe' | 'database' | 'code' | 'calendar'

export interface AgentTask {
  id: string
  title: string
  description: string
  time: string
  status: AgentTaskStatus
}

export interface AgentCapability {
  title: string
  description: string
  icon: AgentCapabilityIcon
  tone: 'blue' | 'violet' | 'mint' | 'amber'
}

export interface AgentLog {
  time: string
  level: 'success' | 'info' | 'warning'
  message: string
}

export interface AgentApiCall {
  method: string
  endpoint: string
  time: string
  duration: string
  status: number
}

export interface Agent {
  id: string
  name: string
  role: string
  description: string
  status: AgentStatus
  avatar: 'spark' | 'orbit' | 'wave' | 'chart' | 'sun'
  model: string
  workspace: string
  successRate: string
  callsToday: number
  tasksToday: number
  uptime: string
  lastActive: string
  capabilities: AgentCapability[]
  tasks: AgentTask[]
  logs: AgentLog[]
  apiCalls: AgentApiCall[]
}

export const agents: Agent[] = [
  {
    id: 'nora', name: 'Nora', role: '研究助理', avatar: 'spark', status: 'running',
    description: '从可信来源整理信息，把复杂问题转化为清晰、可执行的洞察。',
    model: 'GPT-4o', workspace: '个人工作区', successRate: '99.2%', callsToday: 128, tasksToday: 12,
    uptime: '14 天 8 小时', lastActive: '正在工作',
    capabilities: [
      { title: '深度搜索', description: '跨来源检索与可信度筛选', icon: 'search', tone: 'blue' },
      { title: '网页摘要', description: '提取重点并生成结构化摘要', icon: 'globe', tone: 'violet' },
      { title: '文档分析', description: '阅读资料、对比和归纳', icon: 'file', tone: 'mint' },
      { title: '知识整理', description: '沉淀研究结果与引用', icon: 'database', tone: 'amber' },
    ],
    tasks: [
      { id: 'NR-2048', title: '整理本周 AI 行业动态', description: '正在分析 18 个信息来源', time: '进行 12 分钟', status: 'running' },
      { id: 'NR-2047', title: '竞品功能对比报告', description: '已生成 6 页研究摘要', time: '今天 10:42', status: 'completed' },
      { id: 'NR-2046', title: '收集产品设计参考', description: '归档 24 条高相关结果', time: '今天 09:18', status: 'completed' },
      { id: 'NR-2045', title: '分析用户访谈记录', description: '等待可用执行时段', time: '今天 08:35', status: 'queued' },
    ],
    logs: [
      { time: '11:26:08', level: 'info', message: '开始分析新的搜索结果（18 个来源）' },
      { time: '11:24:41', level: 'success', message: '网页内容提取完成，已去除重复信息' },
      { time: '11:22:13', level: 'info', message: '任务 NR-2048 已进入执行队列' },
      { time: '10:42:57', level: 'success', message: '竞品功能对比报告已完成并保存' },
    ],
    apiCalls: [
      { method: 'POST', endpoint: '/v1/agents/nora/runs', time: '11:26:08', duration: '428 ms', status: 200 },
      { method: 'GET', endpoint: '/v1/search/sources', time: '11:24:41', duration: '183 ms', status: 200 },
      { method: 'POST', endpoint: '/v1/documents/analyze', time: '10:42:57', duration: '1.2 s', status: 200 },
    ],
  },
  {
    id: 'atlas', name: 'Atlas', role: '自动化专家', avatar: 'orbit', status: 'running',
    description: '连接常用工具，自动执行重复工作并持续跟踪重要流程。',
    model: 'GPT-4o', workspace: '个人工作区', successRate: '98.8%', callsToday: 84, tasksToday: 8,
    uptime: '9 天 3 小时', lastActive: '正在工作',
    capabilities: [
      { title: '工作流编排', description: '连接任务、条件与外部服务', icon: 'code', tone: 'violet' },
      { title: '日程同步', description: '自动协调日程与提醒', icon: 'calendar', tone: 'blue' },
      { title: '数据连接', description: '读取和更新工作区数据', icon: 'database', tone: 'mint' },
      { title: '网页操作', description: '完成标准化网页流程', icon: 'globe', tone: 'amber' },
    ],
    tasks: [
      { id: 'AT-1186', title: '同步项目里程碑', description: '正在更新 4 个工作空间', time: '进行 4 分钟', status: 'running' },
      { id: 'AT-1185', title: '整理今日待办事项', description: '已创建 9 条待办', time: '今天 09:02', status: 'completed' },
      { id: 'AT-1184', title: '归档昨日完成任务', description: '已归档 17 项', time: '今天 08:10', status: 'completed' },
    ],
    logs: [
      { time: '11:18:35', level: 'info', message: '开始同步项目里程碑' },
      { time: '11:18:02', level: 'success', message: '成功连接所有工作空间' },
      { time: '09:02:14', level: 'success', message: '今日待办事项已整理完成' },
    ],
    apiCalls: [
      { method: 'POST', endpoint: '/v1/agents/atlas/runs', time: '11:18:35', duration: '312 ms', status: 200 },
      { method: 'PATCH', endpoint: '/v1/workspaces/milestones', time: '11:18:02', duration: '224 ms', status: 200 },
    ],
  },
  {
    id: 'echo', name: 'Echo', role: '内容创作', avatar: 'wave', status: 'idle',
    description: '把零散想法转化为有条理、有语气的文案和内容草稿。',
    model: 'Claude 3.5', workspace: '创作工作区', successRate: '97.6%', callsToday: 42, tasksToday: 5,
    uptime: '待命中', lastActive: '18 分钟前',
    capabilities: [
      { title: '内容撰写', description: '多种语气与格式的内容草稿', icon: 'file', tone: 'violet' },
      { title: '网页摘要', description: '快速理解参考内容', icon: 'globe', tone: 'blue' },
      { title: '资料搜索', description: '定位素材与事实依据', icon: 'search', tone: 'mint' },
    ],
    tasks: [
      { id: 'EC-0896', title: '撰写产品更新说明', description: '第一版草稿已保存', time: '今天 10:21', status: 'completed' },
      { id: 'EC-0895', title: '准备社交媒体文案', description: '已生成 3 个版本', time: '今天 09:46', status: 'completed' },
      { id: 'EC-0894', title: '整理品牌语气指南', description: '等待可用执行时段', time: '昨天 17:35', status: 'queued' },
    ],
    logs: [
      { time: '10:21:05', level: 'success', message: '产品更新说明草稿已保存' },
      { time: '09:46:17', level: 'success', message: '社交媒体文案已生成' },
      { time: '09:40:02', level: 'info', message: '已加载品牌语气指南' },
    ],
    apiCalls: [
      { method: 'POST', endpoint: '/v1/agents/echo/runs', time: '10:21:05', duration: '806 ms', status: 200 },
      { method: 'GET', endpoint: '/v1/brand/voice', time: '09:40:02', duration: '129 ms', status: 200 },
    ],
  },
  {
    id: 'delta', name: 'Delta', role: '数据分析师', avatar: 'chart', status: 'running',
    description: '探索数据趋势，用直观图表和结论支持更快的决策。',
    model: 'GPT-4o', workspace: '数据工作区', successRate: '99.1%', callsToday: 96, tasksToday: 7,
    uptime: '5 天 17 小时', lastActive: '正在工作',
    capabilities: [
      { title: '数据分析', description: '清洗、聚合与解释数据', icon: 'database', tone: 'blue' },
      { title: '报告生成', description: '生成可分享的分析报告', icon: 'file', tone: 'violet' },
      { title: '脚本执行', description: '运行受控分析脚本', icon: 'code', tone: 'mint' },
    ],
    tasks: [
      { id: 'DT-0738', title: '生成月度增长报告', description: '正在处理 12 张数据表', time: '进行 8 分钟', status: 'running' },
      { id: 'DT-0737', title: '检查异常转化指标', description: '已标记 2 处异常波动', time: '今天 09:32', status: 'completed' },
      { id: 'DT-0736', title: '更新仪表盘数据', description: '同步已完成', time: '今天 08:12', status: 'completed' },
    ],
    logs: [
      { time: '11:14:21', level: 'info', message: '正在处理月度增长报告数据' },
      { time: '09:32:08', level: 'warning', message: '转化指标发现 2 处异常波动' },
      { time: '08:12:44', level: 'success', message: '仪表盘数据同步完成' },
    ],
    apiCalls: [
      { method: 'POST', endpoint: '/v1/agents/delta/runs', time: '11:14:21', duration: '509 ms', status: 200 },
      { method: 'GET', endpoint: '/v1/datasets/growth', time: '11:13:02', duration: '192 ms', status: 200 },
    ],
  },
  {
    id: 'mira', name: 'Mira', role: '日程协调', avatar: 'sun', status: 'offline',
    description: '让日程、会议准备和重要提醒井然有序。',
    model: 'GPT-4o mini', workspace: '个人工作区', successRate: '98.4%', callsToday: 0, tasksToday: 0,
    uptime: '已暂停', lastActive: '昨天 18:24',
    capabilities: [
      { title: '日程管理', description: '整理和协调会议安排', icon: 'calendar', tone: 'amber' },
      { title: '文档摘要', description: '提炼会前参考资料', icon: 'file', tone: 'blue' },
      { title: '资料搜索', description: '快速查找会议背景', icon: 'search', tone: 'violet' },
    ],
    tasks: [
      { id: 'MI-0312', title: '准备明日会议简报', description: '等待智能体恢复运行', time: '昨天 18:24', status: 'queued' },
      { id: 'MI-0311', title: '整理本周会议纪要', description: '已保存至工作区', time: '昨天 16:08', status: 'completed' },
    ],
    logs: [
      { time: '18:24:03', level: 'warning', message: '智能体已暂停' },
      { time: '16:08:42', level: 'success', message: '本周会议纪要已整理完成' },
    ],
    apiCalls: [
      { method: 'POST', endpoint: '/v1/agents/mira/pause', time: '18:24:03', duration: '105 ms', status: 200 },
    ],
  },
]
