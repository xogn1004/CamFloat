$ErrorActionPreference = 'Stop'
$cleanupRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$cleanupPrefix = $cleanupRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$cleanupReport = [Collections.Generic.List[string]]::new()
function Remove-CamFloatIntermediate([string]$relativePath) {
    $cleanupTarget = [IO.Path]::GetFullPath((Join-Path $cleanupRoot $relativePath))
    if (-not $cleanupTarget.StartsWith($cleanupPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target escaped workspace: $cleanupTarget"
    }
    if (Test-Path -LiteralPath $cleanupTarget) {
        $cleanupItem = Get-Item -LiteralPath $cleanupTarget -Force
        if ($cleanupItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing recursive cleanup of a linked path: $cleanupTarget"
        }
        Remove-Item -LiteralPath $cleanupTarget -Recurse -Force
        $cleanupReport.Add($relativePath)
    }
}
# Literal allowlist. Source, Git, development dependencies, settings and final
# release/verification evidence are deliberately outside these targets.
foreach ($cleanupRelative in @('build', 'build_fixed', 'build_release', 'build_v020',
    'dist', 'dist_fixed', 'releases', 'release\CamFloat-Diagnostic',
    '__pycache__', 'tests\__pycache__', '.demo-process-id', '.ui-preview-pid')) {
    Remove-CamFloatIntermediate $cleanupRelative
}
foreach ($cleanupOld in Get-ChildItem -LiteralPath (Join-Path $cleanupRoot 'verification') -Force) {
    if ($cleanupOld.Name -notin @('current', 'rtsp-keyframes-test.mp4')) {
        Remove-CamFloatIntermediate (Join-Path 'verification' $cleanupOld.Name)
    }
}
foreach ($cleanupOld in @('batch-tests.log', 'preview.png', 'preview-menu.png', 'design-test.mp4')) {
    Remove-CamFloatIntermediate (Join-Path 'verification\current' $cleanupOld)
}
foreach ($cleanupOld in @('preview.png', 'preview-menu.png')) {
    Remove-CamFloatIntermediate (Join-Path 'release\CamFloat' $cleanupOld)
}
$cleanupReport | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $cleanupRoot 'verification\current\cleanup.json') -Encoding utf8
Write-Output "Removed $($cleanupReport.Count) intermediate paths."
