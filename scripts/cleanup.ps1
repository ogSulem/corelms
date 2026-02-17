Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Remove-IfExists([string]$Path) {
  if (Test-Path -LiteralPath $Path) {
    Write-Host "Removing $Path"
    Remove-Item -LiteralPath $Path -Recurse -Force
  }
}

Write-Host "CoreLMS cleanup starting..."

# Root artifacts
Remove-IfExists ".venv"
Remove-IfExists ".pytest_cache"

# Frontend artifacts
Remove-IfExists "frontend\\node_modules"
Remove-IfExists "frontend\\.next"
Remove-IfExists "frontend\\out"

# Backend artifacts
Get-ChildItem -Path "backend" -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  Remove-IfExists $_.FullName
}
Remove-IfExists "backend\\.pytest_cache"

# Backend virtualenv (if created locally)
Remove-IfExists "backend\\.venv"

Write-Host "Done. To restore frontend deps: cd frontend; yarn install"
Write-Host "To rebuild containers: docker compose up --build"
