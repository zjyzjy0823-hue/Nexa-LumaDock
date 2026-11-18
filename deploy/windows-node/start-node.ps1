param(
  [string]$ConfigPath = "$env:USERPROFILE\.studiolo-node\config.json",
  [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ConfigPath)) {
  Write-Error "找不到节点配置文件: $ConfigPath 。请先从 agent-node/config.example.json 复制配置。"
}

if (-not $env:STUDIOLO_NODE_TOKEN) {
  Write-Host "提示：请确认 $ConfigPath 中已填入 nodeToken，或通过 `$env:STUDIOLO_NODE_TOKEN 注入 sn_live_ 凭证。" -ForegroundColor Yellow
}

$RepoNodeDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "agent-node"
Set-Location $RepoNodeDir
& $PythonExe -m agent_node --config $ConfigPath
