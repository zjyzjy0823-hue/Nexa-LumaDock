$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$backend = Join-Path $root 'backend'
$target = Join-Path $root 'src-tauri\binaries\nexa-backend-x86_64-pc-windows-msvc.exe'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw 'Windows x64 is required.' }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Windows x64 is required.' }
python -m pip show pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) { python -m pip install 'pyinstaller>=6,<7' }
Push-Location $backend
try {
    python -m PyInstaller --noconfirm --clean --distpath (Join-Path $backend 'dist') --workpath (Join-Path $backend 'build') 'nexa-backend.spec'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
} finally { Pop-Location }
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
Copy-Item -LiteralPath (Join-Path $backend 'dist\nexa-backend.exe') -Destination $target -Force
Write-Host "Sidecar ready: $target"
