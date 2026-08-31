$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed." }

Remove-Item -Recurse -Force "$root\build", "$root\dist" -ErrorAction SilentlyContinue

& $python generate_bundle_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed." }

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "TeleManager" `
    --icon "$root\build\branding\TeleManager.ico" `
    --add-data "$root\assets;assets" `
    --hidden-import "keyring.backends.Windows" `
    telegram_manager_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller app build failed." }

Write-Host "Build complete: $root\dist\TeleManager.exe"
