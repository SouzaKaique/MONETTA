<#
  Banco PostgreSQL privado do MONETTA (porta 5433), separado do servico do Windows.
  Uso: .\scripts\db.ps1 init | start | stop | status
  "init" gera a senha, cria o cluster em .pgdata e grava DATABASE_URL e SECRET_KEY em .env.
#>
param([Parameter(Mandatory)][ValidateSet('init','start','stop','status')][string]$Action)

$ErrorActionPreference = 'Stop'
$root   = Split-Path $PSScriptRoot -Parent
$data   = Join-Path $root '.pgdata'
$log    = Join-Path $data 'server.log'
$envf   = Join-Path $root '.env'
$bin    = 'C:\Program Files\PostgreSQL\17\bin'
$port   = 5433

# pg_ctl deixa o servidor herdar o stdout: nunca usar pipe aqui, senao o script fica preso.
function Start-Db {
  $a = @('-D', "`"$data`"", '-o', "`"-p $port -h 127.0.0.1`"", '-l', "`"$log`"", 'start')
  Start-Process -FilePath "$bin\pg_ctl.exe" -ArgumentList $a -WindowStyle Hidden
  foreach ($i in 1..30) {
    & "$bin\pg_isready.exe" -q -h 127.0.0.1 -p $port
    if ($LASTEXITCODE -eq 0) { return }
    Start-Sleep -Seconds 1
  }
  throw 'PostgreSQL nao respondeu em 30s; veja .pgdata\server.log'
}

function New-Secret([int]$bytes) {
  $b = New-Object byte[] $bytes
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  -join ($b | ForEach-Object { $_.ToString('x2') })
}

switch ($Action) {
  'init' {
    if (Test-Path (Join-Path $data 'PG_VERSION')) { Write-Output 'Cluster ja existe.'; return }
    $pw = New-Secret 24
    $pwfile = [IO.Path]::GetTempFileName()
    # initdb le a senha de um arquivo: ela nao aparece na linha de comando nem no historico.
    [IO.File]::WriteAllText($pwfile, $pw)
    try {
      & "$bin\initdb.exe" -D $data -U monetta --pwfile=$pwfile -A scram-sha-256 -E UTF8 --locale=C | Out-Null
    } finally { Remove-Item $pwfile -Force }
    Start-Db
    $env:PGPASSWORD = $pw
    & "$bin\createdb.exe" -h 127.0.0.1 -p $port -U monetta monetta
    & "$bin\createdb.exe" -h 127.0.0.1 -p $port -U monetta monetta_test
    $url = "postgresql+psycopg://monetta:$pw@127.0.0.1:$port/monetta"
    $lines = @(
      "DATABASE_URL=$url",
      "TEST_DATABASE_URL=$($url -replace '/monetta$','/monetta_test')",
      "SECRET_KEY=$(New-Secret 32)",
      "APP_TIMEZONE=America/Sao_Paulo",
      "PUBLIC_URL=http://localhost:4200",
      "",
      "# Login social: deixe vazio para esconder o botao correspondente.",
      "GOOGLE_CLIENT_ID=",
      "GOOGLE_CLIENT_SECRET=",
      "APPLE_CLIENT_ID=",
      "APPLE_TEAM_ID=",
      "APPLE_KEY_ID=",
      "APPLE_PRIVATE_KEY_PATH="
    )
    [IO.File]::WriteAllLines($envf, $lines)
    Write-Output 'Cluster criado e .env gravado.'
  }
  'start'  { Start-Db; Write-Output 'Banco no ar na porta 5433.' }
  'stop'   { & "$bin\pg_ctl.exe" -D $data -m fast -w stop }
  'status' { & "$bin\pg_ctl.exe" -D $data status }
}
