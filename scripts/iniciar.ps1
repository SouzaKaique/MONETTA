<#
  Inicia o MONETTA neste computador em http://monetta.localhost
  Liga o banco, aplica migrações, compila o app quando preciso e abre o navegador.
  Uso: .\scripts\iniciar.ps1            (ou dois cliques em MONETTA.cmd)
       .\scripts\iniciar.ps1 -Recompilar (força nova compilação do app)
#>
param([switch]$Recompilar)

# Os comandos externos escrevem avisos no canal de erro; o sucesso é decidido pelo código de saída.
$ErrorActionPreference = 'Continue'
$root     = Split-Path $PSScriptRoot -Parent
$backend  = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python   = Join-Path $backend '.venv\Scripts\python.exe'
$dist     = Join-Path $frontend 'dist\frontend\browser\index.html'
$address  = 'http://monetta.localhost'

Write-Host 'MONETTA: ligando o banco...'
& (Join-Path $PSScriptRoot 'db.ps1') start | Out-Null
if (-not $?) { throw 'Falha ao ligar o banco. Veja .pgdata\server.log' }

Write-Host 'MONETTA: conferindo o banco...'
Push-Location $backend
try { & $python -m flask --app wsgi.py db upgrade 2>&1 | Out-Null } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar o banco.' }

# Compila quando ainda não existe ou quando o código mudou depois da última compilação.
$source = Get-ChildItem (Join-Path $frontend 'src') -Recurse -File |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
$stale = -not (Test-Path $dist) -or $source.LastWriteTime -gt (Get-Item $dist).LastWriteTime
if ($Recompilar -or $stale) {
  Write-Host 'MONETTA: compilando o app (leva cerca de 1 minuto)...'
  Push-Location $frontend
  try { npx ng build 2>&1 | Out-Null } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o app.' }
}

$busy = Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
  $name = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
  if (-not $name) { $name = 'outro programa' }
  throw "A porta 80 está em uso por $name. Se o MONETTA já estiver aberto, use a janela dele: $address"
}

$env:PUBLIC_URL = $address
# O Google não aceita monetta.localhost como retorno; o servidor recebe em localhost e repassa.
if (-not $env:OAUTH_REDIRECT_BASE) { $env:OAUTH_REDIRECT_BASE = 'http://localhost' }
$env:HOST = '127.0.0.1'
$env:PORT = '80'

Start-Job -ScriptBlock {
  param($url)
  foreach ($i in 1..30) {
    try { Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
    catch { Start-Sleep -Seconds 1 }
  }
  Start-Process $url
} -ArgumentList $address | Out-Null

Write-Host ''
Write-Host "MONETTA no ar em $address"
Write-Host 'Deixe esta janela aberta enquanto usa. Para encerrar, feche a janela.'
Push-Location $backend
try { & $python serve.py } finally { Pop-Location }
