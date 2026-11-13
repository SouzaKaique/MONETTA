<#
  Desliga o MONETTA que está em segundo plano: servidor e banco.
  Uso: .\scripts\parar.ps1
  Ele volta a ligar na próxima vez que você entrar no Windows (se o início automático estiver ativo).
#>
$root    = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $root 'logs\monetta.pid'

# Primeiro o processo que vigia o servidor; senão ele religaria o que for fechado.
if (Test-Path $pidFile) {
  $id = (Get-Content $pidFile -Raw).Trim()
  if ($id) { & taskkill.exe /PID $id /T /F 2>&1 | Out-Null }
  Remove-Item $pidFile -ErrorAction SilentlyContinue
}

$listen = Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listen) {
  $process = Get-Process -Id $listen.OwningProcess -ErrorAction SilentlyContinue
  if ($process -and $process.ProcessName -like 'python*') {
    & taskkill.exe /PID $listen.OwningProcess /T /F 2>&1 | Out-Null
  }
}

& (Join-Path $PSScriptRoot 'db.ps1') stop 2>&1 | Out-Null
Write-Output 'MONETTA desligado.'
