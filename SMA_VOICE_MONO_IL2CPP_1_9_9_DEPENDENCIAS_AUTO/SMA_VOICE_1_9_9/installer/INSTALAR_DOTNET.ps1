$ErrorActionPreference = 'Stop'
try {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA indisponivel.' }
    $target = Join-Path $env:LOCALAPPDATA 'SMA Voice\dotnet'
    $exe = Join-Path $target 'dotnet.exe'
    function Test-Sdk([string]$Path) {
        if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
        try {
            $versions = & $Path --list-sdks 2>$null
            return ($LASTEXITCODE -eq 0 -and [bool]($versions -match '^(?:[6-9]|[1-9][0-9]+)\.\d+\.\d+'))
        } catch { return $false }
    }
    $candidates = @($exe)
    $command = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    foreach ($folder in @($env:ProgramW6432, $env:ProgramFiles, $env:DOTNET_ROOT)) {
        if ($folder) {
            $candidates += (Join-Path $folder 'dotnet\dotnet.exe')
            $candidates += (Join-Path $folder 'dotnet.exe')
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Sdk $candidate) { Write-Host "SDK .NET ja disponivel: $candidate"; exit 0 }
    }
    Write-Host 'Baixando SDK .NET 8 (compilador C#) do site oficial da Microsoft. Requer internet.'
    Write-Host "Instalacao local: $target (sem alterar PATH global ou XTTS)."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $tempDir = Join-Path ([IO.Path]::GetTempPath()) ('sma-dotnet-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempDir | Out-Null
    try {
        $script = Join-Path $tempDir 'dotnet-install.ps1'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://dot.net/v1/dotnet-install.ps1' -OutFile $script
        $hostExe = Join-Path $PSHOME 'powershell.exe'
        & $hostExe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $script -Channel 8.0 -InstallDir $target -NoPath
        if ($LASTEXITCODE -ne 0) { throw "Instalador oficial retornou $LASTEXITCODE." }
        if (-not (Test-Sdk $exe)) { throw 'SDK instalado, mas dotnet --list-sdks nao retornou uma versao compativel.' }
        Write-Host "SDK .NET disponivel: $exe" -ForegroundColor Green
    } finally { Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    exit 0
} catch {
    Write-Host "ERRO instalando SDK .NET: $_" -ForegroundColor Red
    Write-Host 'Verifique a internet ou instale o SDK manualmente em https://dotnet.microsoft.com/download/dotnet/8.0'
    exit 1
}
