import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'

export interface PluginConfig {
  serverUrl?: string
  agentTokenEnv?: string
  adapterConfigPath?: string
}

export interface Credential { serverUrl: string; agentToken: string }

const messages: Record<string, string> = {
  unauthorized: 'Agent token is invalid or revoked. Configure a current na_live_ credential.',
  agent_disabled: 'This Agent is disabled. Enable it in Nexa.',
  permission_denied: 'Permission denied. Ask the user to grant the required data scope in Nexa Agent settings.',
  unsupported_action: 'This action is unavailable on this Nexa version.',
  validation_error: 'Invalid parameters. Check the tool schema, category type, amount and date.',
  not_found: 'Entity does not exist in the authorized workspace.',
  conflict: 'The operation could not complete. Retry this logical invocation with the same action identity.',
  idempotency_conflict: 'Action identity was already used for different parameters. Do not retry with changed parameters.',
  local_only: 'Connect this plugin to Nexa Local. Data Actions are unavailable on Core.',
  unavailable: 'Nexa Local is unavailable. A write may have committed; retry this logical invocation with the same identity.',
  configuration_error: 'Configure a trusted Nexa Local URL and a na_live_ credential through the named environment variable or explicit adapter config path.',
}

export class ToolError extends Error {
  constructor(readonly code: string) { super(messages[code] ?? messages.unavailable) }
}

export async function resolveCredential(config: PluginConfig): Promise<Credential> {
  try {
    const shared: Partial<Credential> = config.adapterConfigPath
      ? JSON.parse(await readFile(config.adapterConfigPath, 'utf8')) as Partial<Credential> : {}
    const serverUrl = config.serverUrl ?? shared.serverUrl ?? process.env.NEXA_LOCAL_URL ?? ''
    const agentToken = process.env[config.agentTokenEnv ?? 'NEXA_AGENT_TOKEN'] ?? shared.agentToken ?? ''
    const url = new URL(serverUrl)
    if (url.username || url.password || url.search || url.hash ||
      (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) ||
      !agentToken.startsWith('na_live_')) throw new ToolError('configuration_error')
    return { serverUrl: url.href.replace(/\/$/, ''), agentToken }
  } catch { throw new ToolError('configuration_error') }
}

export type Fetch = typeof fetch

// Tool-call identities survive re-entry after a lost response. The bounded cache
// holds UUIDs/hashes only, never credentials or business payloads.
const identities = new Map<string, string>()
export function invocationId(toolCallId?: string): string {
  if (!toolCallId) return randomUUID()
  const existing = identities.get(toolCallId)
  if (existing) return existing
  const id = randomUUID()
  identities.set(toolCallId, id)
  if (identities.size > 4096) identities.delete(identities.keys().next().value!)
  return id
}

export async function request(credential: Credential, path: string, body: object | undefined,
  fetcher: Fetch = fetch, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const encoded = body === undefined ? undefined : JSON.stringify(body)
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const timeout = AbortSignal.timeout(10_000)
      const response = await fetcher(credential.serverUrl + path, {
        method: encoded === undefined ? 'GET' : 'POST', redirect: 'error',
        headers: { Authorization: `Bearer ${credential.agentToken}`, 'Content-Type': 'application/json' },
        body: encoded, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      })
      if (response.status >= 500 && attempt < 2) continue
      const raw: unknown = await response.json()
      if (!response.ok) {
        const code = typeof raw === 'object' && raw !== null && 'detail' in raw &&
          typeof raw.detail === 'object' && raw.detail !== null && 'code' in raw.detail &&
          typeof raw.detail.code === 'string' ? raw.detail.code : 'unavailable'
        throw new ToolError(Object.hasOwn(messages, code) ? code : 'unavailable')
      }
      if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) throw new ToolError('unavailable')
      return raw as Record<string, unknown>
    } catch (error) {
      if (error instanceof ToolError) throw error
      if (signal?.aborted || attempt === 2) throw new ToolError('unavailable')
    }
  }
  throw new ToolError('unavailable')
}

export async function executeTool(action: string, effect: string, args: Record<string, unknown>,
  config: PluginConfig, toolCallId?: string, fetcher: Fetch = fetch, signal?: AbortSignal) {
  const credential = await resolveCredential(config)
  if (action === 'status') return request(credential, '/api/agent/actions/catalog', undefined, fetcher, signal)
  const body = { action, arguments: args, ...(effect === 'read' ? {} : { actionId: invocationId(toolCallId) }) }
  return request(credential, '/api/agent/actions/execute', body, fetcher, signal)
}
