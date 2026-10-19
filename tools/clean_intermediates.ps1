param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$cleanupRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$cleanupPrefix = $cleanupRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not (Test-Path -LiteralPath (Join-Path $cleanupRoot 'pyproject.toml')) -or
    -not (Test-Path -LiteralPath (Join-Path $cleanupRoot 'src\camfloat'))) {
    throw 'Run this script from the CamFloat project tools folder.'
}
$cleanupReport = [Collections.Generic.List[string]]::new()
$cleanupSkipped = [Collections.Generic.List[string]]::new()
$cleanupProcesses = @(Get-Process CamFloat -ErrorAction SilentlyContinue)
function Remove-CamFloatIntermediate([string]$relativePath) {
    $cleanupTarget = [IO.Path]::GetFullPath((Join-Path $cleanupRoot $relativePath))
    if (-not $cleanupTarget.StartsWith($cleanupPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target escaped workspace: $cleanupTarget"
    }
    if (Test-Path -LiteralPath $cleanupTarget) {
        $cleanupAncestor = $cleanupTarget
        while ($cleanupAncestor -ne $cleanupRoot) {
            $cleanupAncestorItem = Get-Item -LiteralPath $cleanupAncestor -Force
            if ($cleanupAncestorItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing cleanup through a linked path: $cleanupAncestor"
            }
            $cleanupAncestor = Split-Path -Parent $cleanupAncestor
        }
        $cleanupItem = Get-Item -LiteralPath $cleanupTarget -Force
        foreach ($cleanupProcess in $cleanupProcesses) {
            if ($cleanupProcess.Path -and ($cleanupProcess.Path -eq $cleanupTarget -or
                $cleanupProcess.Path.StartsWith($cleanupTarget + '\', [StringComparison]::OrdinalIgnoreCase))) {
                Write-Output "Skipped running app: $relativePath"
                $cleanupSkipped.Add($relativePath)
                return
            }
        }
        if ($Preview) {
            Write-Output "Would remove: $relativePath"
        } elseif ($cleanupItem.PSIsContainer) {
            Remove-Item -LiteralPath $cleanupTarget -Recurse -Force
        } else {
            Remove-Item -LiteralPath $cleanupTarget -Force
        }
        $cleanupReport.Add($relativePath)
    }
}
# Literal allowlist. Source, Git, development dependencies, settings and final
# current release, research materials and current QA evidence are preserved.
foreach ($cleanupRelative in @('build', 'build_fixed', 'build_release', 'build_v020',
    'dist', 'dist_fixed', 'releases', 'release\CamFloat-Diagnostic',
    '__pycache__', 'tests\__pycache__', 'tools\__pycache__',
    'packaging\__pycache__', 'src\camfloat\__pycache__', '.demo-process-id', '.ui-preview-pid',
    'release\CamFloat-1.1.0-rc.1-win-x64',
    'release\CamFloat-1.1.0-dev.4-win-x64.zip', 'release\CamFloat-1.1.0-dev.4-win-x64.sha256',
    'release\CamFloat-1.1.0-dev.5-win-x64.zip', 'release\CamFloat-1.1.0-dev.5-win-x64.sha256',
    'release\CamFloat-1.1.0-dev.6-win-x64.zip', 'release\CamFloat-1.1.0-dev.6-win-x64.sha256',
    'release\CamFloat-1.1.0-rc.1-win-x64.zip', 'release\CamFloat-1.1.0-rc.1-win-x64.sha256',
    'release\CamFloat-1.1.0-rc.2-win-x64.zip', 'release\CamFloat-1.1.0-rc.2-win-x64.sha256',
    'verification\current\release\portable check', 'verification\current\release\packaged-profile',
    'verification\current\release\superseded-portable', 'verification\current\release\final portable',
    'verification\current\release\final-packaged-profile', 'verification\current\release\final-targeted-profile',
    'verification\current\release\final-network-profile', 'verification\current\release\final-initial-profile',
    'verification\current\release\final-visual-profile', 'verification\current\release\icon-copy-profile')) {
    Remove-CamFloatIntermediate $cleanupRelative
}
foreach ($cleanupOld in @('batch-tests.log', 'preview.png', 'preview-menu.png', 'design-test.mp4')) {
    Remove-CamFloatIntermediate (Join-Path 'verification\current' $cleanupOld)
}
foreach ($cleanupOld in @('preview.png', 'preview-menu.png')) {
    Remove-CamFloatIntermediate (Join-Path 'release\CamFloat' $cleanupOld)
}
if (-not $Preview) {
    @{ removed = @($cleanupReport); skipped = @($cleanupSkipped) } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $cleanupRoot 'verification\current\cleanup.json') -Encoding utf8
    Write-Output "Removed $($cleanupReport.Count) intermediate paths."
}
