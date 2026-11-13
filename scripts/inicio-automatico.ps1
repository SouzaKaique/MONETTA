<#
  Liga o MONETTA sozinho, em segundo plano, sempre que você entrar no Windows.
  Uso: .\scripts\inicio-automatico.ps1           (ativa e já liga agora)
       .\scripts\inicio-automatico.ps1 -Remover  (desativa; não desliga o que está no ar)
  Cria um atalho na pasta Inicializar do seu usuário: não precisa de administrador e
  aparece em Gerenciador de Tarefas > Aplicativos de inicialização.
#>
param([switch]$Remover)

$ErrorActionPreference = 'Stop'
$root    = Split-Path $PSScriptRoot -Parent
$iniciar = Join-Path $PSScriptRoot 'iniciar.ps1'
$atalho  = Join-Path ([Environment]::GetFolderPath('Startup')) 'MONETTA.lnk'
$shell   = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$argumentos = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$iniciar`" -Fundo"

if ($Remover) {
  Remove-Item $atalho -ErrorAction SilentlyContinue
  Write-Output 'O MONETTA não vai mais ligar junto com o Windows.'
  Write-Output 'Para desligar agora: .\scripts\parar.ps1'
  return
}

$link = (New-Object -ComObject WScript.Shell).CreateShortcut($atalho)
$link.TargetPath = $shell
$link.Arguments = $argumentos
$link.WorkingDirectory = $root
$link.WindowStyle = 7  # minimizado: no máximo um piscar rápido ao entrar no Windows
$link.Description = 'Liga o MONETTA em segundo plano'
$link.Save()
Write-Output "Pronto: o MONETTA vai ligar sozinho ao entrar no Windows."

Start-Process -FilePath $shell -ArgumentList $argumentos -WindowStyle Hidden
Write-Output 'Ligando agora em segundo plano. Em até 1 minuto abra http://monetta.localhost'
