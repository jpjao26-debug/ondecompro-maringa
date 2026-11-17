# OndeCompro em Maringa? - roda a coleta do dia e publica o app (chamado pelo Agendador de Tarefas)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$PSDefaultParameterValues["Out-File:Encoding"] = "utf8"
$pastaLogs = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force $pastaLogs | Out-Null
$log = Join-Path $pastaLogs ("{0:yyyy-MM-dd}.txt" -f (Get-Date))
function RodarPython { if (Get-Command py.exe -ErrorAction SilentlyContinue) { & py.exe -3 @args } else { & python.exe @args } }

"===== Inicio: $(Get-Date -Format 'dd/MM/yyyy HH:mm') =====" | Out-File $log -Append -Encoding utf8

# espera a coleta de Ubatuba terminar (as duas no mesmo PC, uma depois da outra; no maximo 2 horas)
$limite = (Get-Date).AddHours(2)
while ((Get-Date) -lt $limite) {
    $ubatuba = Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe' OR Name='py.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match '\\ondecompro\\rodar\.ps1' }
    if (-not $ubatuba) { break }
    "Esperando a coleta de Ubatuba terminar..." | Out-File $log -Append -Encoding utf8
    Start-Sleep -Seconds 120
}
git pull --rebase --autostash *>> $log
RodarPython -m coletor.rodar *>> $log
if ($LASTEXITCODE -eq 0) {
    RodarPython -m coletor.publicar *>> $log
} else {
    "A coleta falhou - o app continua com os precos anteriores." | Out-File $log -Append -Encoding utf8
}
"===== Fim: $(Get-Date -Format 'dd/MM/yyyy HH:mm') =====" | Out-File $log -Append -Encoding utf8

# apaga logs com mais de 30 dias
Get-ChildItem $pastaLogs -Filter *.txt | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -ErrorAction SilentlyContinue
