# Hosting GRATIS, sin tarjeta: Render o Koyeb (cuenta Google).
# Este script intenta Koyeb. Si no hay login, te dice el siguiente paso.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) { throw "Falta .env" }

$koyeb = Get-Command koyeb -ErrorAction SilentlyContinue
if (-not $koyeb) {
  Write-Host "Instalando Koyeb CLI (gratis)..."
  $bin = Join-Path $env:USERPROFILE ".koyeb"
  New-Item -ItemType Directory -Force -Path $bin | Out-Null
  $url = "https://github.com/koyeb/koyeb-cli/releases/latest/download/koyeb-cli_windows_amd64.zip"
  $zip = Join-Path $env:TEMP "koyeb-cli.zip"
  Invoke-WebRequest -Uri $url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $bin -Force
  $env:Path = "$bin;" + $env:Path
}

Write-Host "Si pide login, pega el token de: https://app.koyeb.com/account/api"
koyeb auth whoami
if ($LASTEXITCODE -ne 0) {
  throw "Haz login en Koyeb (gratis, sin tarjeta) y vuelve a lanzar deploy.ps1"
}

# Construye lista de env desde .env
$envArgs = @()
Get-Content .env | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
  $k, $v = $line.Split("=", 2)
  if ($k -and $v) { $envArgs += @("--env", "$k=$v") }
}
$envArgs += @("--env", "PYTHONUNBUFFERED=1")
$envArgs += @("--env", "PORT=8080")

Write-Host "Desplegando servicio gratuito biwenger-bot..."
koyeb apps get biwenger-bot
if ($LASTEXITCODE -ne 0) {
  koyeb apps create biwenger-bot
}

# Deploy desde el directorio local (Docker remoto).
koyeb services create biwenger-bot/bot `
  --type web `
  --docker python:3.12-slim `
  --regions fra `
  --ports 8080:http `
  --routes /:8080 `
  @envArgs

Write-Host "Cuando Koyeb te de la URL, pon PUBLIC_URL=https://ESA-URL en el panel (opcional)."
Write-Host "Listo: puedes apagar el PC. El bot vive en el plan gratis de Koyeb."
