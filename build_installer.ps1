$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed." }

& $root\build_windows_exe.ps1
if ($LASTEXITCODE -ne 0) { throw "app build failed." }

& $python generate_bundle_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed." }

Remove-Item -Recurse -Force "$root\build\installer", "$root\dist\TeleManager-Setup.exe" -ErrorAction SilentlyContinue

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "TeleManager-Setup" `
    --icon "$root\build\branding\TeleManager.ico" `
    --add-binary "$root\dist\TeleManager.exe;payload" `
    --add-data "$root\assets;assets" `
    installer.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installer build failed." }

Write-Host "Installer build complete: $root\dist\TeleManager-Setup.exe"
