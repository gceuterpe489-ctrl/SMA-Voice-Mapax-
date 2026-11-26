@echo off
setlocal DisableDelayedExpansion
title SMA Voice - Windows prerequisites
set "SMA_PREFLIGHT_FILE=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$s=[IO.File]::ReadAllText($env:SMA_PREFLIGHT_FILE); $m='#'+'---SMA_POWERSHELL---'; $i=$s.IndexOf($m,[StringComparison]::Ordinal); if($i -lt 0){exit 1}; & ([ScriptBlock]::Create($s.Substring($i+$m.Length)))"
set "SMA_RC=%ERRORLEVEL%"
echo.
if not "%SMA_RC%"=="0" echo Verificacao interrompida. Confira as mensagens acima.
pause
exit /b %SMA_RC%
#---SMA_POWERSHELL---
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$base = Split-Path -Parent $env:SMA_PREFLIGHT_FILE
$report = Join-Path $base ('SMA_PRE_REQUISITOS_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.txt')
try { [IO.File]::WriteAllText($report, '') } catch { $report = Join-Path $env:TEMP ('SMA_PRE_REQUISITOS_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.txt'); [IO.File]::WriteAllText($report, '') }
function Log([string]$line) { Write-Host $line; Add-Content -LiteralPath $report -Value $line -Encoding UTF8 }
function Check([string]$name, [bool]$ok, [string]$details) {
    $status = if ($ok) { 'OK' } else { 'ATENCAO' }
    Log "[$status] $name : $details"
}
function Find-Python311 {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { try { $p = & $py.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null; if ($LASTEXITCODE -eq 0 -and $p -and (Test-Path -LiteralPath $p -PathType Leaf)) { return [string]$p } } catch {} }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:ProgramFiles\Python311\python.exe")) { if (Test-Path -LiteralPath $p -PathType Leaf) { return $p } }
    return $null
}
function Find-Sdk {
    $paths = @("$env:LOCALAPPDATA\SMA Voice\dotnet\dotnet.exe", "$env:ProgramFiles\dotnet\dotnet.exe")
    $cmd = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if ($cmd) { $paths += $cmd.Source }
    if ($env:ProgramW6432) { $paths += (Join-Path $env:ProgramW6432 'dotnet\dotnet.exe') }
    if ($env:DOTNET_ROOT) { $paths += (Join-Path $env:DOTNET_ROOT 'dotnet.exe') }
    foreach ($p in ($paths | Select-Object -Unique)) { if (Test-Path -LiteralPath $p -PathType Leaf) { try { $v = @(& $p --list-sdks 2>$null); if ($LASTEXITCODE -eq 0 -and ($v -match '^(?:[6-9]|[1-9][0-9]+)\.\d+\.\d+')) { return ($v -join '; ') } } catch {} } }
    return $null
}
function Install-Missing([string]$id, [string]$name, [string]$scope) {
    if (-not $repair) { return }
    if (-not $winget) { Log "[MANUAL] $name : WinGet unavailable."; return }
    if ((Read-Host "Instalar $name pelo WinGet? [s/N]") -notmatch '^[sSyY]$') { Log "[PULADO] $name"; return }
    $argsList = @('install','--id',$id,'--exact','--source','winget')
    if ($scope) { $argsList += @('--scope',$scope) }
    Log "[INSTALACAO] $id"
    try { & $winget.Source @argsList 2>&1 | ForEach-Object { Log ([string]$_) }; $rc = $LASTEXITCODE; Log "[RESULTADO] $id exit=$rc (reinicie se solicitado e execute a verificacao novamente)." } catch { Log "[ERRO] $id : $($_.Exception.Message)" }
}
function Test-Endpoint([string]$name,[string]$url) {
    try { $r = Invoke-WebRequest -UseBasicParsing -Uri $url -Method Head -TimeoutSec 10; Log "[HTTP] $name : $($r.StatusCode)" }
    catch { $resp = $_.Exception.Response; if ($resp) { Log "[HTTP] $name : $([int]$resp.StatusCode) (servidor respondeu; pode bloquear HEAD ou exigir outra rota)" } else { Log "[ATENCAO] $name : $($_.Exception.Message)" } }
}
try {
    Log 'SMA VOICE 1.9.9 - PRE-REQUISITOS WINDOWS / WINDOWS PREREQUISITES'
    Log ('Data / Date: ' + (Get-Date -Format s))
    Write-Host '1) Verificar apenas / Check only'
    Write-Host '2) Verificar e instalar itens ausentes com confirmacao / Check and install missing items'
    $mode = Read-Host 'Opcao / Option [1/2]'
    if ($mode -notin @('1','2')) { throw 'Opcao invalida.' }
    $repair = $mode -eq '2'
    Write-Host '1) SMA - Mono   2) CMA - IL2CPP   3) Ambos / Both'
    $game = Read-Host 'Jogo / Game [1/2/3]'
    if ($game -notin @('1','2','3')) { throw 'Opcao invalida.' }
    Log "Modo=$mode Jogo=$game"
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $x64 = [Environment]::Is64BitOperatingSystem -and ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'AMD64')
    Check 'Windows x64' $x64 "$($os.Caption) build=$($os.BuildNumber)"
    if (-not $x64) { throw 'Este pacote foi preparado para Windows x64.' }
    Log "PowerShell $($PSVersionTable.PSVersion) | LanguageMode=$($ExecutionContext.SessionState.LanguageMode)"
    Log ('Execution policies: ' + ((Get-ExecutionPolicy -List | ForEach-Object { "$($_.Scope)=$($_.ExecutionPolicy)" }) -join '; '))
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    Check 'WinGet' ([bool]$winget) $(if ($winget) { (& $winget.Source --version 2>$null | Out-String).Trim() } else { 'Instale App Installer: https://aka.ms/getwinget' })
    $vc = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
    $vcOk = $null -ne $vc -and $vc.Installed -eq 1
    Check 'Visual C++ v14 x64 runtime' $vcOk $(if ($vcOk) { [string]$vc.Version } else { 'https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist' })
    if (-not $vcOk) { Install-Missing 'Microsoft.VCRedist.2015+.x64' 'Visual C++ x64' '' }
    if ($game -in @('1','3')) {
        $net = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -ErrorAction SilentlyContinue
        $csc = Test-Path -LiteralPath "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
        if (-not $csc) { $csc = Test-Path -LiteralPath "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe" }
        Check '.NET Framework 4.x / csc.exe (SMA)' $csc "Release=$($net.Release); https://dotnet.microsoft.com/download/dotnet-framework"
        if (-not $csc) { Log '[MANUAL] Atualize o Windows / instale .NET Framework 4.8 pelo site oficial. Nao alteramos recursos do Windows.' }
    }
    if ($game -in @('2','3')) {
        $sdk = Find-Sdk
        Check '.NET SDK >=6 (CMA)' ([bool]$sdk) $(if ($sdk) { $sdk } else { 'SDK 8 recomendado; https://dotnet.microsoft.com/download/dotnet/8.0' })
        if (-not $sdk) { Install-Missing 'Microsoft.DotNet.SDK.8' '.NET SDK 8' '' }
    }
    $python = Find-Python311
    Check 'Python 3.11 (novo XTTS)' ([bool]$python) $(if ($python) { 'Encontrado / Found' } else { 'Necessario apenas para ambiente novo; https://www.python.org/downloads/windows/' })
    if (-not $python) { Install-Missing 'Python.Python.3.11' 'Python 3.11' 'user' }
    if ($python) {
        try { $out = @(& $python -c 'import sys,struct,venv,ssl; print(sys.version.split()[0], struct.calcsize("P")*8, ssl.OPENSSL_VERSION)' 2>&1); $rc = $LASTEXITCODE; Check 'Python venv / SSL / x64' ($rc -eq 0 -and (($out -join ' ') -match '\b64\b')) ($out -join ' '); $out = @(& $python -m pip --version 2>&1); Check 'pip' ($LASTEXITCODE -eq 0) ($out -join ' ') } catch { Log "[ATENCAO] Python: $($_.Exception.Message)" }
    }
    $existing = (Read-Host 'Python.exe do XTTS existente (opcional; Enter para pular)').Trim().Trim('"')
    if ($existing) {
        if ([IO.Path]::GetFileName($existing) -ine 'python.exe' -or -not (Test-Path -LiteralPath $existing -PathType Leaf)) { Log '[ATENCAO] Caminho Python XTTS invalido.' }
        else { try { $out = @(& $existing -c 'import torch,numpy,sounddevice; from TTS.api import TTS; print("torch",torch.__version__,"CUDA",torch.cuda.is_available(),"build",torch.version.cuda)' 2>&1); Check 'Imports XTTS' ($LASTEXITCODE -eq 0) ($out -join ' '); $out = @(& $existing -m pip check 2>&1); Check 'XTTS pip check' ($LASTEXITCODE -eq 0) ($out -join ' ') } catch { Log "[ATENCAO] XTTS: $($_.Exception.Message)" } }
    }
    $gpu = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($gpu) { try { $out = @(& $gpu.Source --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1); Check 'NVIDIA driver' ($LASTEXITCODE -eq 0) ($out -join '; ') } catch { Log '[ATENCAO] nvidia-smi falhou.' } }
    else { Log '[INFO] NVIDIA nao localizada pelo nvidia-smi; CPU continua disponivel. Driver: https://www.nvidia.com/Download/index.aspx' }
    Log '[INFO] Novo XTTS usa torch/torchaudio 2.8.0 cu128 ou CPU; CUDA Toolkit separado nao e necessario para as wheels oficiais. Driver compativel necessario para GPU.'
    foreach ($drive in (Get-PSDrive -PSProvider FileSystem | Where-Object { $null -ne $_.Free })) { Log ('[DISCO] {0}: {1:N1} GiB livres' -f $drive.Name, ($drive.Free / 1GB)) }
    try { $sac = (Get-MpComputerStatus -ErrorAction Stop).SmartAppControlState; Log "[INFO] Smart App Control=$sac (nao alterado)" } catch { Log '[INFO] Smart App Control nao consultado.' }
    if ((Read-Host 'Verificar acesso HTTPS aos servidores de download? [S/n]') -notmatch '^[nN]$') {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Test-Endpoint 'GitHub / BepInEx' 'https://github.com/BepInEx/BepInEx/releases'
        Test-Endpoint 'BepInEx builds' 'https://builds.bepinex.dev/projects/bepinex_be'
        Test-Endpoint 'SourceForge / Translator' 'https://downloads.sourceforge.net/'
        Test-Endpoint 'PyPI' 'https://pypi.org/simple/'
        Test-Endpoint 'PyTorch cu128' 'https://download.pytorch.org/whl/cu128/torch/'
        Test-Endpoint 'NuGet' 'https://api.nuget.org/v3/index.json'
        Test-Endpoint 'Ollama' 'https://ollama.com/library/qwen3:4b-instruct'
    }
    try { $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3; Check 'Ollama API local' $true '127.0.0.1:11434'; Check 'Modelo padrao qwen3:4b-instruct' ([bool](@($tags.models | Where-Object { $_.name -eq 'qwen3:4b-instruct' -or $_.model -eq 'qwen3:4b-instruct' }).Count)) 'Outros modelos sao permitidos.' } catch { Log '[INFO] Ollama API offline; use INSTALAR_OLLAMA_E_MODELO.bat se precisar de traducao local.' }
    Log '[FIM] Execute INSTALAR.bat apos corrigir pendencias. Este BAT nao altera o jogo, XTTS existente, drivers ou seguranca do Windows.'
    Log '[INFO] Revise informacoes pessoais nos logs antes de compartilhar.'
    Write-Host "Relatorio: $report"
    exit 0
} catch { Log "[ERRO] $($_.Exception.Message)"; Write-Host "Relatorio: $report"; exit 1 }
