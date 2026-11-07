<#
  Backup completo do banco em backups\ (pasta fora do git). Guarda os 14 mais recentes.
  Uso: .\scripts\backup.ps1
  Para agendar, crie uma tarefa no Agendador de Tarefas do Windows chamando este script.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$bin  = 'C:\Program Files\PostgreSQL\17\bin'
$dir  = Join-Path $root 'backups'
$keep = 14

$line = Get-Content (Join-Path $root '.env') | Where-Object { $_ -like 'DATABASE_URL=*' }
if ($line -notmatch '://([^:]+):([^@]+)@([^:/]+):(\d+)/(\w+)') { throw 'DATABASE_URL invalida no .env' }
$user, $pass, $hostName, $port, $name = $Matches[1..5]

New-Item -ItemType Directory -Force $dir | Out-Null
$file = Join-Path $dir ("monetta-{0}.dump" -f (Get-Date -Format 'yyyy-MM-dd-HHmm'))
$env:PGPASSWORD = $pass
& "$bin\pg_dump.exe" -h $hostName -p $port -U $user -F c -f $file $name
if ($LASTEXITCODE -ne 0) { throw 'pg_dump falhou' }

Get-ChildItem $dir -Filter 'monetta-*.dump' | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip $keep | Remove-Item -Force -Confirm:$false
Write-Output "Backup salvo em $file"
