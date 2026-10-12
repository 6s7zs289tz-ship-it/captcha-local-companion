param([Parameter(Mandatory = $true)][string]$StageDirectory)
$ErrorActionPreference = 'Stop'
$TaskStageRoot = [IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
$TaskSiteRoot = [IO.Path]::GetFullPath((Join-Path $TaskStageRoot 'runtime\Lib\site-packages')).TrimEnd('\')
$TaskMarker = Join-Path $TaskStageRoot '.build-owner'
if (-not (Test-Path -LiteralPath $TaskMarker) -or [IO.File]::ReadAllText($TaskMarker).Trim() -ne 'captcha-local-companion-build') {
    throw '没有本构建的目录标记，拒绝清理。'
}
function Assert-OwnedPackagePath([string]$Candidate, [switch]$Children) {
    $TaskResolved = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    if (-not $TaskResolved.StartsWith($TaskSiteRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not $TaskResolved.StartsWith($TaskStageRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw '清理目标不在本构建的依赖目录内。'
    }
    $TaskAncestor = $TaskResolved
    while ($true) {
        if (Test-Path -LiteralPath $TaskAncestor) {
            if ((Get-Item -LiteralPath $TaskAncestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw '依赖目录包含链接，拒绝清理。'
            }
        }
        if ($TaskAncestor -eq $TaskStageRoot) { break }
        $TaskAncestor = [IO.Path]::GetDirectoryName($TaskAncestor)
        if (-not $TaskAncestor) { throw '无法确认清理目录归属。' }
    }
    if ($Children -and (Get-ChildItem -LiteralPath $TaskResolved -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) {
        throw '清理目标包含链接，拒绝清理。'
    }
}
function Remove-OwnedPackageItem([string]$Candidate) {
    if (-not (Test-Path -LiteralPath $Candidate)) { return }
    $TaskItem = Get-Item -LiteralPath $Candidate -Force
    Assert-OwnedPackagePath $TaskItem.FullName -Children:$TaskItem.PSIsContainer
    if ($TaskItem.PSIsContainer) { Remove-Item -LiteralPath $TaskItem.FullName -Recurse -Force }
    else { Remove-Item -LiteralPath $TaskItem.FullName -Force }
}
if (-not (Test-Path -LiteralPath $TaskSiteRoot)) { throw '没有可清理的构建依赖。' }
# Check the owned root before enumeration; every deletion repeats the path and link checks.
Assert-OwnedPackagePath (Join-Path $TaskSiteRoot '.guard')
$TaskBefore = [long](Get-ChildItem -LiteralPath $TaskSiteRoot -File -Recurse -Force | Measure-Object Length -Sum).Sum
$TaskRemoved = 0
$TaskDirectories = Get-ChildItem -LiteralPath $TaskSiteRoot -Directory -Recurse -Force |
    Where-Object { $_.Name -in @('tests', '__pycache__') -and $_.FullName -notmatch '\.dist-info(?:\\|$)' } |
    Sort-Object { $_.FullName.Length } -Descending
foreach ($TaskDirectory in $TaskDirectories) {
    if (-not (Test-Path -LiteralPath $TaskDirectory.FullName)) { continue }
    Assert-OwnedPackagePath $TaskDirectory.FullName -Children
    # Retain a whole test directory if it contains an original license or notice.
    if (Get-ChildItem -LiteralPath $TaskDirectory.FullName -File -Recurse -Force |
        Where-Object { $_.Name -match '^(?:LICEN[CS]E|COPYING|NOTICE)(?:[.-]|$)' }) { continue }
    Remove-OwnedPackageItem $TaskDirectory.FullName
    $TaskRemoved++
}
$TaskCvData = Join-Path $TaskSiteRoot 'cv2\data'
if (Test-Path -LiteralPath $TaskCvData) {
    foreach ($TaskFile in Get-ChildItem -LiteralPath $TaskCvData -File -Filter 'haarcascade*.xml') {
        Remove-OwnedPackageItem $TaskFile.FullName
        $TaskRemoved++
    }
}
# OpenCV's optional FFmpeg plugin is used by video I/O, not PNG/JPEG OCR.
# Upstream explicitly permits excluding this DLL from image-only distributions.
$TaskCvRoot = Join-Path $TaskSiteRoot 'cv2'
if (Test-Path -LiteralPath $TaskCvRoot) {
    foreach ($TaskFile in Get-ChildItem -LiteralPath $TaskCvRoot -File |
        Where-Object { $_.Name -match '^opencv_videoio_ffmpeg[0-9]+_64\.dll$' }) {
        Remove-OwnedPackageItem $TaskFile.FullName
        $TaskRemoved++
    }
}
$TaskAfter = [long](Get-ChildItem -LiteralPath $TaskSiteRoot -File -Recurse -Force | Measure-Object Length -Sum).Sum
[pscustomobject]@{BeforeBytes=$TaskBefore;AfterBytes=$TaskAfter;RemovedBytes=($TaskBefore-$TaskAfter);RemovedItems=$TaskRemoved}