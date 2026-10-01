/** Host-native desktop entry point, without Bash or PowerShell dependencies. */
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('../', import.meta.url))
const [action, ...args] = process.argv.slice(2)
if (!['prepare', 'dev', 'build'].includes(action) ||
    (args.length && (args.length !== 2 || args[0] !== '--target'))) {
  throw new Error('Usage: node scripts/desktop.mjs prepare|dev|build [--target triple]')
}
function run(command, arguments_) {
  const result = spawnSync(command, arguments_, { cwd: root, stdio: 'inherit' })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
const rust = spawnSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' })
const target = args[1] || process.env.TAURI_ENV_TARGET_TRIPLE || rust.stdout?.trim()
if (!target) throw new Error('Install Rust stable or specify --target')
const venv = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.NEXA_PYTHON || (existsSync(venv) ? venv : process.platform === 'win32' ? 'python' : 'python3')
run(python, ['scripts/build-backend-sidecar.py', '--target', target])
if (action !== 'prepare') {
  run(process.execPath, ['node_modules/@tauri-apps/cli/tauri.js', action, '--target', target])
}
