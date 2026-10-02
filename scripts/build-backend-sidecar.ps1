# Compatibility entry point for existing Windows build instructions.
param([string]$Target = 'x86_64-pc-windows-msvc')
$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'build-backend-sidecar.py') --target $Target
if ($LASTEXITCODE -ne 0) { throw 'Backend sidecar build failed.' }
