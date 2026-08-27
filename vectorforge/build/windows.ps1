$ErrorActionPreference = "Stop"

$ForgeRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ForgeRoot

python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller --noconfirm --clean VectorForge.spec

Write-Host "Windows build written to $ForgeRoot/dist/VectorForge.exe"
