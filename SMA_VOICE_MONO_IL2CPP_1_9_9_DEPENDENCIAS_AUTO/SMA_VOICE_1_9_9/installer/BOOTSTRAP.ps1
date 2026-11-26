$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Find-ExistingPython {
    while ($true) {
        $folder = (Read-Host 'XTTS folder or python.exe / Pasta XTTS ou python.exe').Trim().Trim('"')
        if (-not $folder) { throw 'Pasta obrigatoria.' }
        if (Test-Path -LiteralPath $folder -PathType Leaf) { $candidates = @($folder) }
        elseif (Test-Path -LiteralPath $folder -PathType Container) {
            $candidates = @('Scripts\python.exe','venv\Scripts\python.exe','.venv\Scripts\python.exe','env\Scripts\python.exe','xtts_env\Scripts\python.exe','python.exe','python_embeded\python.exe','python_embedded\python.exe','installer_files\env\python.exe') | ForEach-Object { Join-Path $folder $_ }
            $candidates += @(Get-ChildItem -LiteralPath $folder -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'Scripts\python.exe' })
        } else { Write-Host 'Pasta inexistente.'; continue }
        foreach ($candidate in ($candidates | Select-Object -Unique)) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                try {
                    & $candidate -c 'import sys; assert sys.version_info >= (3,9); import torch,numpy,sounddevice; from TTS.api import TTS' 2>$null | Out-Null
                    if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
                } catch { continue }
            }
        }
        Write-Host 'Nenhum Python XTTS funcional encontrado. Informe a pasta do venv/conda ou o python.exe diretamente. Uma pasta contendo apenas model.pth nao e um ambiente Python.'
        if ((Read-Host 'Tentar outra pasta? [S/n]') -eq 'n') { throw 'Selecao cancelada.' }
    }
}
function Find-Python311 {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $result = & $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $result -and (Test-Path -LiteralPath $result)) { return $result }
        } catch { }
    }
    $candidates = @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:ProgramFiles\Python311\python.exe")
    foreach($candidate in $candidates) { if(Test-Path -LiteralPath $candidate) { return $candidate } }
    return $null
}
try {
    Write-Host 'SMA VOICE 1.9.9 - Installation / Instalacao'
    Write-Host '1) SMA - Some Modeling Agency (Mono)'
    Write-Host '2) CMA - Corrupted Modeling Agency (IL2CPP)'
    $gameOption=Read-Host 'Game / Jogo [1/2]'
    if ($gameOption -eq '1') { $game='SMA' }
    elseif ($gameOption -eq '2') { $game='CMA' }
    else { throw 'Opcao invalida / Invalid game selection.' }
    $gamePath=(Read-Host 'Game folder or executable / Pasta do jogo ou executavel').Trim().Trim('"')
    if (-not $gamePath -or -not (Test-Path -LiteralPath $gamePath)) { throw 'Game path not found / Pasta inexistente.' }
    $gamePath=(Resolve-Path -LiteralPath $gamePath).Path
    $gameRoot=$gamePath
    if (Test-Path -LiteralPath $gamePath -PathType Leaf) { $gameRoot=Split-Path -Parent $gamePath }
    $paths=Join-Path $gameRoot 'BepInEx\config\sma-voice-portable.paths'
    $python=$null
    if (Test-Path -LiteralPath $paths -PathType Leaf) {
        $old=@(Get-Content -LiteralPath $paths -Encoding UTF8)
        if ($old.Count -ge 1 -and [IO.Path]::IsPathRooted($old[0]) -and [IO.Path]::GetFileName($old[0]) -ieq 'python.exe' -and (Test-Path -LiteralPath $old[0] -PathType Leaf)) {
            try {
                & $old[0] -c 'import sys; assert sys.version_info >= (3,9); import torch,numpy,sounddevice; from TTS.api import TTS' 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $python=$old[0]; $kind='existing'; Write-Host 'Existing XTTS reused / XTTS existente reutilizado.' }
            } catch { }
        }
    }
    if (-not $python) {
    Write-Host 'XTTS setup / Ambiente de voz' 
    Write-Host '1 - Existing XTTS / Ja tenho XTTS instalado'
    Write-Host '2 - New XTTS environment / Instalar XTTS'
    $mode=Read-Host 'Option / Opcao'
    if ($mode -eq '1') { $python=Find-ExistingPython; $kind='existing' }
    elseif ($mode -eq '2') {
        $kind='auto'; $python=Find-Python311
        if (-not $python) {
            $winget=Get-Command winget.exe -ErrorAction SilentlyContinue
            if (-not $winget) { throw 'WinGet indisponivel. Instale Python 3.11 x64 de python.org (inclua py launcher) e execute novamente.' }
            Write-Host 'Instalando Python 3.11 via WinGet. Confirme as solicitacoes do Windows se aparecerem.'
            & $winget.Source install --id Python.Python.3.11 --exact --scope user
            if ($LASTEXITCODE -ne 0) { throw 'Instalacao do Python falhou.' }
            $python=Find-Python311
            if (-not $python) { throw 'Python instalado, mas nao localizado nesta sessao. Feche e execute INSTALAR.bat novamente.' }
        }
    } else { throw 'Opcao invalida.' }
    }
    Write-Host "Python selecionado: $python"
    & $python "$PSScriptRoot\instalar_portatil.py" --xtts $kind --game $game --game-root $gamePath
    exit $LASTEXITCODE
} catch { Write-Host "ERRO: $_" -ForegroundColor Red; exit 1 }
