// Used by the real PostgreSQL regression: credentials are environment-only;
// structured invocation arrives on stdin, never through command-line arguments.
import { executeTool } from '../dist/client.js'
let input = ''
for await (const chunk of process.stdin) input += chunk
const { serverUrl, action, effect, arguments: args, toolCallId, dropResponseOnce } = JSON.parse(input)
try {
  let lost = false
  const transport = async (...args) => {
    const response = await fetch(...args)
    if (dropResponseOnce && !lost && response.ok) {
      lost = true
      await response.text() // The real API has committed; discard its response.
      throw new Error('simulated response loss')
    }
    return response
  }
  const result = await executeTool(action, effect, args, { serverUrl }, toolCallId, transport)
  process.stdout.write(JSON.stringify(result))
} catch (error) {
  process.stderr.write(error.code ?? 'tool_error')
  process.exitCode = 1
}
