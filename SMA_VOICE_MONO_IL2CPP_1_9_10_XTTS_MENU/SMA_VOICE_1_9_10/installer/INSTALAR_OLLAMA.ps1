$ErrorActionPreference='Stop'
$Model='qwen3:4b-instruct'
function Find-Ollama {
    $cmd=Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe")) {
        if (Test-Path -LiteralPath $p -PathType Leaf) { return $p }
    }
    return $null
}
function Get-LocalModels {
    try { return (Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3) } catch { return $null }
}
try {
    Write-Host "SMA Voice - Ollama + $Model (local translation / traducao local)"
    $ollama=Find-Ollama
    if (-not $ollama) {
        $winget=Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'WinGet not available. Install Ollama from https://ollama.com/download/windows and run this BAT again.' }
        & $winget.Source install --id Ollama.Ollama --exact --source winget
        if ($LASTEXITCODE -ne 0) { throw 'Ollama installation failed. See CMD above; official installer: https://ollama.com/download/windows' }
        $env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')+';'+$env:Path
        $ollama=Find-Ollama
        if (-not $ollama) { throw 'Ollama installed but not found. Reopen this BAT.' }
    } else { Write-Host 'Ollama already installed / Ollama existente preservado.' }
    $env:OLLAMA_HOST='127.0.0.1:11434'
    $tags=Get-LocalModels
    if ($null -eq $tags) {
        Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Minimized
        for ($i=0; $i -lt 40; $i++) { Start-Sleep -Seconds 1; $tags=Get-LocalModels; if ($null -ne $tags) { break } }
    }
    if ($null -eq $tags) { throw 'Ollama local API unavailable on 127.0.0.1:11434. Open Ollama and retry.' }
    if (@($tags.models | Where-Object { $_.name -eq $Model -or $_.model -eq $Model }).Count -eq 0) {
        Write-Host 'Downloading model (~2.5 GB) / Baixando modelo...'
        & $ollama pull $Model
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed / Falha no download do modelo.' }
    } else { Write-Host 'Default model already present / Modelo existente preservado.' }
    $tags=Get-LocalModels
    if ($null -eq $tags -or @($tags.models | Where-Object { $_.name -eq $Model -or $_.model -eq $Model }).Count -eq 0) { throw 'Model not found in local API after installation.' }
    & $ollama list
    if ($LASTEXITCODE -ne 0) { throw 'ollama list failed.' }
    Write-Host 'READY: http://127.0.0.1:11434' -ForegroundColor Green
    Write-Host "Configure UnityGameTranslator local LLM and MODELO_OLLAMA=$Model (or auto). Other models are not removed or changed."
    exit 0
} catch { Write-Host "ERROR: $_" -ForegroundColor Red; exit 1 }
