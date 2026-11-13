<#
  Inicia o MONETTA neste computador em http://monetta.localhost
  Liga o banco, aplica migrações, compila o app quando preciso e abre o navegador.
  Uso: .\scripts\iniciar.ps1            (ou dois cliques em MONETTA.cmd)
       .\scripts\iniciar.ps1 -Recompilar (força nova compilação do app)
       .\scripts\iniciar.ps1 -Fundo      (sem janela nem navegador; usado ao ligar o Windows)
  No modo -Fundo o andamento vai para logs\monetta.log, as mensagens do servidor (inclusive
  o link de recuperar senha, sem e-mail configurado) para logs\servidor.log, e o servidor
  volta sozinho se cair.
#>
param([switch]$Recompilar, [switch]$Fundo)

# Os comandos externos escrevem avisos no canal de erro; o sucesso é decidido pelo código de saída.
$ErrorActionPreference = 'Continue'
$root     = Split-Path $PSScriptRoot -Parent
$backend  = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python   = Join-Path $backend '.venv\Scripts\python.exe'
$dist     = Join-Path $frontend 'dist\frontend\browser\index.html'
$logs     = Join-Path $root 'logs'
$logFile  = Join-Path $logs 'monetta.log'
$serverLog = Join-Path $logs 'servidor.log'
$pidFile  = Join-Path $logs 'monetta.pid'
$address  = 'http://monetta.localhost'

function Test-Monetta {
  try {
    Invoke-WebRequest 'http://127.0.0.1/api/health' -UseBasicParsing -TimeoutSec 2 | Out-Null
    return $true
  } catch { return $false }
}

function Get-Port80Owner {
  $busy = Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $busy) { return $null }
  $name = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
  if ($name) { return $name } else { return 'outro programa' }
}

# Já está no ar (por exemplo, ligado junto com o Windows): só abre o navegador.
if (Test-Monetta) {
  if (-not $Fundo) {
    Write-Host "MONETTA já está no ar em $address"
    Start-Process $address
  }
  exit 0
}

if ($Fundo) {
  New-Item -ItemType Directory -Force $logs | Out-Null
  # Guarda só o último registro grande: o arquivo não cresce para sempre.
  foreach ($file in $logFile, $serverLog) {
    if ((Test-Path $file) -and (Get-Item $file).Length -gt 5MB) { Move-Item $file "$file.old" -Force }
  }
  Start-Transcript -Path $logFile -Append | Out-Null
  Set-Content -Path $pidFile -Value $PID
}

try {
  Write-Host "$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') MONETTA: ligando o banco..."
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

  $owner = Get-Port80Owner
  if ($owner) { throw "A porta 80 está em uso por $owner. Feche esse programa e tente de novo." }

  $env:PUBLIC_URL = $address
  # O Google não aceita monetta.localhost como retorno; o servidor recebe em localhost e repassa.
  if (-not $env:OAUTH_REDIRECT_BASE) { $env:OAUTH_REDIRECT_BASE = 'http://localhost' }
  $env:HOST = '127.0.0.1'
  $env:PORT = '80'
  $env:PYTHONUNBUFFERED = '1'  # mensagens chegam ao registro na hora

  if (-not $Fundo) {
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
  } else {
    Write-Host "MONETTA no ar em $address (em segundo plano)"
  }

  do {
    Push-Location $backend
    try {
      if ($Fundo) {
        & cmd.exe /c "`"$python`" serve.py >> `"$serverLog`" 2>&1"
      } else {
        # Pelo cmd, as mensagens do servidor chegam como texto comum, sem virar erro do PowerShell.
        & cmd.exe /c "`"$python`" serve.py 2>&1" | Out-Host
      }
    } finally { Pop-Location }
    if (-not $Fundo) { break }
    Write-Host "$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') O servidor parou (código $LASTEXITCODE). Ligando de novo em 10 segundos..."
    Start-Sleep -Seconds 10
    $owner = Get-Port80Owner
    if ($owner) { throw "A porta 80 foi ocupada por $owner; o MONETTA não foi religado." }
  } while ($true)
} catch {
  Write-Host "$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') ERRO: $_"
  if ($Fundo) { exit 1 }
  throw
} finally {
  if ($Fundo) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Stop-Transcript | Out-Null
  }
}
