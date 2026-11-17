import { Type } from 'typebox'
import { defineToolPlugin } from 'openclaw/plugin-sdk/tool-plugin'
import catalog from './catalog.json' with { type: 'json' }
import { executeTool } from './client.js'

export default defineToolPlugin({
  id: 'studiolo-tools',
  name: 'Studiolo Local Tools',
  description: 'Access authorized Ledger, Websites and Data through Studiolo Local. Never bypass permission errors. Writes remain local until manual sync.',
  configSchema: Type.Object({
    serverUrl: Type.Optional(Type.String({ description: 'Trusted Studiolo Local URL; HTTPS for remote hosts.' })),
    agentTokenEnv: Type.Optional(Type.String({ description: 'Environment variable holding the Agent token; default STUDIOLO_AGENT_TOKEN.' })),
    adapterConfigPath: Type.Optional(Type.String({ description: 'Explicit shared runtime adapter config.json path. Never discover credential files automatically.' })),
  }, { additionalProperties: false }),
  tools: tool => [
    tool({ name: 'studiolo_status', description: 'Check Studiolo Local connectivity, Agent identity, current scopes and Studiolo version. Never returns credentials.',
      parameters: Type.Object({}, { additionalProperties: false }),
      execute: (_args, config, context) => executeTool('status', 'read', {}, config, context.toolCallId, fetch, context.signal) }),
    ...catalog.map(entry => tool({
      name: entry.toolName, description: entry.description,
      parameters: Type.Unsafe<Record<string, unknown>>(entry.parameters),
      execute: (args, config, context) => executeTool(entry.action, entry.effect, args, config, context.toolCallId, fetch, context.signal),
    })),
  ],
})
