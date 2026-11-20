/**
 * Studiolo v0.7.0 多设备 Agent 协同调度（Fleet）与 E2EE 分块文件总线类型定义。
 */

export type NodePlatform = 'macos' | 'windows' | 'linux' | 'android' | 'ios'

export type AdapterProvider =
  | 'codex'
  | 'opencode'
  | 'hermes'
  | 'antigravity'
  | 'dsh'
  | 'openclaw'
  | 'mock'

export type EndpointKind = 'lan' | 'xtcp' | 'edge_relay' | 'core'
export type ApprovalDecision = 'allow_once' | 'allow_session' | 'allow_trust' | 'deny'
export type RiskLevel = 'low' | 'medium' | 'high'
export type TokenUsageSource = 'exact' | 'estimated'

export interface FleetUsageDay {
  date: string
  requests: number
  tokens: number
  cached: number
  otherInput: number
  output: number
  other: number
}

export type SubscriptionQuotaProvider = 'codex' | 'opencode'

export interface SubscriptionQuotaWindow {
  group: string
  kind: 'primary' | 'secondary' | 'monthly'
  remainingPercent: number
  windowMinutes: number | null
  resetsAt: number | null
}

export interface SubscriptionQuota {
  status: 'ready' | 'no_data' | 'unavailable' | 'offline' | 'unsupported'
  checkedAt: number | null
  windows: SubscriptionQuotaWindow[]
}

export interface SessionTokenUsage {
  totalInputTokens: number
  totalCachedTokens: number
  totalOutputTokens: number
  totalReasoningTokens: number
  totalTokens: number
  lastInputTokens: number
  lastOutputTokens: number
  lastTurnTokens: number
  contextWindow?: number
  turns: number
  model?: string
  source: TokenUsageSource | 'mixed'
  updatedAt: number
}

export interface FleetModel {
  id: string
  label: string
  efforts: string[]
  /** 模型所属 provider（如 opencode / opencode-go），同名模型靠它区分 */
  provider?: string
  /** 可选徽标（如「新」「默认」） */
  badge?: string
  /** 模型默认推荐思考强度 */
  defaultEffort?: string
  /** 提示或不可用说明 */
  note?: string
  /** 当前环境不可用（置灰展示） */
  unavailable?: boolean
}

export type ComposerMode = 'build' | 'plan'

export interface RunOptions {
  model?: string
  effort?: string
  agent?: string
  readOnly?: boolean
  denyRequests?: boolean
  /** 极速模式：自动放行代理工具审批请求，无需人工确认 */
  autoApprove?: boolean
  /** Plan 模式：要求代理先输出结构化方案并在执行前确认 */
  planMode?: boolean
}

export interface WorkspaceSkill {
  id: string
  trigger: string
  title: string
  description: string
  source: string
  template: string
}

export interface FileBlameLine {
  line: number
  sha: string
  author: string
  time: number
}

export interface DiffAnnotation {
  id: string
  filePath: string
  lineNo: number
  codeSnippet: string
  comment: string
  resolved: boolean
  createdAt: number
}

export interface PastedTextBlock {
  id: string
  title: string
  content: string
  lineCount: number
  charCount: number
}

export interface AgentModeOption {
  id: string
  name: string
  description?: string
  mode?: string
}

export interface McpServerInfo {
  name: string
  status?: string
  tools?: string[]
  error?: string
}

export interface WorkspaceRule {
  id: string
  title: string
  source: string
  content: string
}

export interface WorkspaceTreeEntry {
  path: string
  name: string
  isDir: boolean
  sizeBytes: number
}

export interface TerminalSessionState {
  terminalId: string
  sessionId: string
  cwd: string
  output: string
  pty?: boolean
  closed?: boolean
  exitCode?: number
}

export interface FilePreviewState {
  path: string
  language: string
  content: string
  lineCount: number
  truncated: boolean
  sizeBytes: number
  isBinary: boolean
  mime?: string
  base64Data?: string
  loading?: boolean
  saving?: boolean
  error?: string
  highlightLine?: number
  blame?: FileBlameLine[]
  blameLoading?: boolean
  updatedAt: number
}

export interface TransferEndpoint {
  kind: EndpointKind
  url: string
  priority: number
  label: string
}

export interface ResolvedEndpoint extends TransferEndpoint {
  ticket?: string | null
}

export interface AdapterInfo {
  provider: AdapterProvider
  version: string
  status: 'ready' | 'unavailable' | 'error'
  capabilities: string[]
}

export interface AgentNode {
  id: string
  workspaceId: string
  name: string
  platform: NodePlatform
  hostname: string | null
  status: 'online' | 'offline' | 'revoked' | 'waiting_approval' | string
  tokenLast4: string | null
  tokenCreatedAt: string | null
  revokedAt: string | null
  allowedRoots: string[]
  adapters: AdapterInfo[]
  transferEndpoints: TransferEndpoint[]
  lastSeenAt: string | null
  createdAt: string
  updatedAt: string
}

export interface NodeTokenOut {
  node: AgentNode
  nodeToken: string
}

export interface BlobOut {
  id: string
  workspaceId: string
  uploaderKind: string
  uploaderId: string
  purpose: 'fleet_artifact' | 'shared_space'
  digest: string
  ciphertextSize: number
  chunkSize: number
  chunkCount: number
  storageRole: string
  storageLocation: string
  manifest: Record<string, unknown> | null
  committedAt: string | null
  expiresAt: string | null
  createdAt: string
}

export interface BlobEndpointsOut {
  blob: BlobOut
  endpoints: ResolvedEndpoint[]
}

export interface ArtifactRef {
  artifactId: string
  aadContext: string
  fileName: string
  mime: string
  plaintextSize: number
  ciphertextSize: number
  chunkCount: number
  digest: string
  /** Base64URL 编码的 32 字节 AES-256-GCM 密钥，仅在内存与点对点帧中流传，Core/Relay 不持久化 */
  keyB64: string
  directToken?: string | null
  storageRole?: string
  downloadedTransport?: EndpointKind
}

export interface ChatSession {
  sessionId: string
  nodeId: string
  provider: AdapterProvider
  title: string
  cwd: string
  worktreePath?: string | null
  hasDiff?: boolean
  todoCount?: number
}

export type ToolCallStatus = 'running' | 'completed' | 'error'

export interface MessageMediaItem {
  id: string
  url: string
  fileName: string
  mime: string
  filePath?: string
  sizeBytes?: number
}

export interface ToolCallBadge {
  id: string
  callId?: string
  name: string
  title?: string
  detail?: string
  status?: ToolCallStatus
  input?: unknown
  output?: string
  error?: string
  durationMs?: number
  startedAt?: number
  subagentSessionId?: string
  media?: MessageMediaItem[]
}

export interface FormFieldOption {
  value: string
  label: string
  description?: string
}

export interface FormFieldWhen {
  key: string
  op: 'eq' | 'neq'
  value: unknown
}

export interface FormFieldSchema {
  key: string
  type: 'string' | 'number' | 'integer' | 'boolean' | 'multiselect' | 'external'
  title?: string
  description?: string
  required?: boolean
  hidden?: boolean
  default?: unknown
  placeholder?: string
  format?: string
  custom?: boolean
  minimum?: number
  maximum?: number
  minItems?: number
  maxItems?: number
  options?: FormFieldOption[]
  url?: string
  when?: FormFieldWhen
}

export interface MessageFormRequest {
  formId: string
  nodeId: string
  sessionId: string
  provider: AdapterProvider
  title: string
  fields: FormFieldSchema[]
  status: 'pending' | 'submitted' | 'cancelled'
  answer?: Record<string, unknown>
  createdAt: number
}

export type MessagePart =
  | { type: 'thought'; text: string }
  | { type: 'text'; text: string }
  | { type: 'tool'; callId: string }

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled'

export interface TodoItem {
  id: string
  content: string
  status: TodoStatus
  priority?: string
}

export interface DiffFileEntry {
  path: string
  status: string
  additions: number
  deletions: number
  patch: string
}

export interface DiffSummary {
  filesChanged: number
  additions: number
  deletions: number
}

export interface SessionDiffState {
  files: DiffFileEntry[]
  summary: DiffSummary
  isGitRepo?: boolean
  branch?: string
  cwd?: string
  perTurn?: boolean
  updatedAt: number
}

export interface CheckpointInfo {
  checkpointId: string
  sessionId: string
  runId?: string
  requestId?: string
  summary: DiffSummary
  reverted?: boolean
  createdAt: number
}

export interface QueuedPromptItem {
  id: string
  text: string
  files?: File[]
  options?: RunOptions
  createdAt: number
}

export interface MessageBranch {
  userText: string
  tailMessages: ChatMessage[]
  createdAt: number
}

export interface PermissionRequestCard {
  callId: string
  nodeId: string
  sessionId: string
  provider: AdapterProvider
  title: string
  command: string
  risk: RiskLevel
  decision: 'pending' | ApprovalDecision
  createdAt: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  runId?: string
  requestId?: string
  nodeId: string
  provider: AdapterProvider
  text: string
  thought?: string
  streaming?: boolean
  error?: string
  toolCalls?: ToolCallBadge[]
  parts?: MessagePart[]
  forms?: MessageFormRequest[]
  approvals?: PermissionRequestCard[]
  artifacts?: ArtifactRef[]
  media?: MessageMediaItem[]
  checkpointId?: string
  diffSummary?: DiffSummary
  branches?: MessageBranch[]
  activeBranchIndex?: number
  durationMs?: number
  turnTokens?: number
  modelLabel?: string
  createdAt: number
}

export type FleetConnectionState = 'disconnected' | 'connecting' | 'reconnecting' | 'online'

export interface FleetWsEvent {
  type: string
  nodeId?: string
  provider?: AdapterProvider
  sessionId?: string
  runId?: string
  requestId?: string
  text?: string
  name?: string
  detail?: string
  callId?: string
  title?: string
  command?: string
  risk?: RiskLevel
  decision?: ApprovalDecision
  artifact?: ArtifactRef
  code?: string
  message?: string
  status?: ToolCallStatus | string
  input?: unknown
  output?: string
  deltaOutput?: string
  error?: string
  durationMs?: number
  subagentSessionId?: string
  media?: MessageMediaItem[]
  items?: TodoItem[]
  files?: string[] | DiffFileEntry[]
  summary?: DiffSummary
  isGitRepo?: boolean
  branch?: string
  perTurn?: boolean
  checkpointId?: string
  restoredFiles?: string[]
  supported?: boolean
  models?: FleetModel[]
  agents?: AgentModeOption[]
  servers?: McpServerInfo[]
  rules?: WorkspaceRule[]
  skills?: WorkspaceSkill[]
  lines?: FileBlameLine[]
  seq?: number
  lastSeq?: number
  incremental?: boolean
  pty?: boolean
  formId?: string
  fields?: FormFieldSchema[]
  cancelled?: boolean
  path?: string
  language?: string
  content?: string
  lineCount?: number
  truncated?: boolean
  sizeBytes?: number
  isBinary?: boolean
  mime?: string
  base64Data?: string
  mergedFiles?: string[]
  active?: boolean
  events?: FleetWsEvent[]
  relDir?: string
  entries?: WorkspaceTreeEntry[]
  patterns?: string[]
  commitHash?: string
  filesCommitted?: string[]
  terminalId?: string
  data?: string
  exitCode?: number
  nodes?: AgentNode[]
  sessions?: Array<{ sessionId: string; provider: AdapterProvider; title?: string; cwd?: string }>
  messages?: Array<{
    role: string
    text: string
    thought?: string
    toolCalls?: ToolCallBadge[]
    media?: MessageMediaItem[]
    parts?: Array<{ type: string; text?: string; callId?: string; id?: string }>
  }>
  cwd?: string
  worktreePath?: string | null
  messageId?: string
  scope?: 'turn' | 'cumulative'
  inputTokens?: number
  cachedInputTokens?: number
  outputTokens?: number
  reasoningTokens?: number
  totalTokens?: number
  lastInputTokens?: number
  lastCachedInputTokens?: number
  lastOutputTokens?: number
  lastReasoningTokens?: number
  lastTotalTokens?: number
  contextWindow?: number
  model?: string
  source?: TokenUsageSource
  usage?: Record<string, unknown>
}
