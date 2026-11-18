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
export type ApprovalDecision = 'allow_once' | 'allow_session' | 'deny'
export type RiskLevel = 'low' | 'medium' | 'high'
export type TokenUsageSource = 'exact' | 'estimated'

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
  /** 可选徽标（如「新」「默认」） */
  badge?: string
  /** 模型默认推荐思考强度 */
  defaultEffort?: string
  /** 提示或不可用说明 */
  note?: string
  /** 当前环境不可用（置灰展示） */
  unavailable?: boolean
}

export interface RunOptions {
  model?: string
  effort?: string
  readOnly?: boolean
  denyRequests?: boolean
  /** 极速模式：自动放行代理工具审批请求，无需人工确认 */
  autoApprove?: boolean
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
}

export interface ToolCallBadge {
  id: string
  name: string
  detail?: string
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
  approvals?: PermissionRequestCard[]
  artifacts?: ArtifactRef[]
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
  models?: FleetModel[]
  nodes?: AgentNode[]
  sessions?: Array<{ sessionId: string; provider: AdapterProvider; title?: string; cwd?: string }>
  messages?: Array<{ role: string; text: string }>
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
