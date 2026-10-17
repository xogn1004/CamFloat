$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$diagnosticStage = Join-Path $env:LOCALAPPDATA 'CamFloatBuild\diagnostic'
$diagnosticDestination = Join-Path $PSScriptRoot 'release\CamFloat-Diagnostic'
New-Item -ItemType Directory -Path $diagnosticStage -Force | Out-Null
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $diagnosticStage 'dist') --workpath (Join-Path $diagnosticStage 'work') `
    CamFloat.spec *> (Join-Path $diagnosticStage 'build.log')
if ($LASTEXITCODE -ne 0) { throw 'Diagnostic build failed. See the staging build.log.' }
robocopy (Join-Path $diagnosticStage 'dist\CamFloat') $diagnosticDestination /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw 'Diagnostic publish failed.' }
foreach ($diagnosticName in @('CamFloat-CPU.exe', 'CamFloat-Clock.exe')) {
    Copy-Item -LiteralPath (Join-Path $diagnosticDestination 'CamFloat.exe') `
        -Destination (Join-Path $diagnosticDestination $diagnosticName) -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'DIAGNOSTIC_BUILD.md') `
    -Destination (Join-Path $diagnosticDestination 'README.md') -Force
Write-Output "Built diagnostic players: $diagnosticDestination"
