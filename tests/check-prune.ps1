$ErrorActionPreference = 'Stop'
$TaskSourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TaskTemporary = Join-Path ([IO.Path]::GetTempPath()) ('captcha-prune-test-' + [Guid]::NewGuid().ToString('N'))
$TaskStage = Join-Path $TaskTemporary 'payload'
$TaskSite = Join-Path $TaskStage 'runtime\Lib\site-packages'
$TaskOutside = Join-Path $TaskTemporary 'outside'
$TaskLink = Join-Path $TaskSite 'dangerous\tests'
function Write-Fixture([string]$Relative, [string]$Content) {
    $TaskFile = Join-Path $TaskSite $Relative
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($TaskFile)) | Out-Null
    [IO.File]::WriteAllText($TaskFile, $Content)
}
function Require([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
try {
    [IO.Directory]::CreateDirectory($TaskSite) | Out-Null
    [IO.Directory]::CreateDirectory($TaskOutside) | Out-Null
    [IO.File]::WriteAllText((Join-Path $TaskStage '.build-owner'), 'captcha-local-companion-build')
    Write-Fixture 'numpy\tests\fixture.txt' ('test' * 200)
    Write-Fixture 'numpy\__pycache__\cache.pyc' 'cache'
    Write-Fixture 'numpy\core.py' 'real source module'
    Write-Fixture 'numpy-2.2.6.dist-info\LICENSE.txt' 'original license'
    Write-Fixture 'numpy-2.2.6.dist-info\tests\NOTICE.txt' 'protected metadata notice'
    Write-Fixture 'retained\tests\LICENSE.txt' 'protected test notice'
    Write-Fixture 'cv2\data\haarcascade_eye.xml' 'unused face classifier'
    Write-Fixture 'cv2\data\__init__.py' 'data module'
    Write-Fixture 'cv2\opencv_videoio_ffmpeg4110_64.dll' 'optional video plugin'
    Write-Fixture 'cv2\cv2.pyd' 'required image processing module'
    Write-Fixture 'rapidocr_onnxruntime\models\recognition.onnx' 'required OCR model'
    $TaskReport = & (Join-Path $TaskSourceRoot 'scripts\prune-package.ps1') -StageDirectory $TaskStage
    Require (-not (Test-Path -LiteralPath (Join-Path $TaskSite 'numpy\tests'))) 'Test fixtures were retained unexpectedly.'
    Require (-not (Test-Path -LiteralPath (Join-Path $TaskSite 'numpy\__pycache__'))) 'Cache files were retained unexpectedly.'
    Require (-not (Test-Path -LiteralPath (Join-Path $TaskSite 'cv2\data\haarcascade_eye.xml'))) 'Unused Haar data was retained unexpectedly.'
    Require (-not (Test-Path -LiteralPath (Join-Path $TaskSite 'cv2\opencv_videoio_ffmpeg4110_64.dll'))) 'Video plugin was retained unexpectedly.'
    foreach ($TaskRequired in @('numpy\core.py','numpy-2.2.6.dist-info\LICENSE.txt','numpy-2.2.6.dist-info\tests\NOTICE.txt','retained\tests\LICENSE.txt','cv2\data\__init__.py','cv2\cv2.pyd','rapidocr_onnxruntime\models\recognition.onnx')) {
        Require (Test-Path -LiteralPath (Join-Path $TaskSite $TaskRequired)) ('Required file removed: ' + $TaskRequired)
    }
    Require ($TaskReport.RemovedBytes -gt 0) 'No reduction was reported.'
    $TaskSecond = & (Join-Path $TaskSourceRoot 'scripts\prune-package.ps1') -StageDirectory $TaskStage
    Require ($TaskSecond.RemovedBytes -eq 0) 'Pruning was not repeatable.'
    [IO.File]::WriteAllText((Join-Path $TaskOutside 'keep.txt'), 'outside fixture')
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($TaskLink)) | Out-Null
    New-Item -ItemType Junction -Path $TaskLink -Target $TaskOutside | Out-Null
    $TaskRejected = $false
    try { & (Join-Path $TaskSourceRoot 'scripts\prune-package.ps1') -StageDirectory $TaskStage | Out-Null } catch { $TaskRejected = $true }
    Require $TaskRejected 'A junction was accepted as a deletion target.'
    Require (Test-Path -LiteralPath (Join-Path $TaskOutside 'keep.txt')) 'A file outside the package was removed.'
    Remove-Item -LiteralPath $TaskLink -Force
    Remove-Item -LiteralPath (Join-Path $TaskStage '.build-owner') -Force
    $TaskRejected = $false
    try { & (Join-Path $TaskSourceRoot 'scripts\prune-package.ps1') -StageDirectory $TaskStage | Out-Null } catch { $TaskRejected = $true }
    Require $TaskRejected 'An unowned directory was accepted.'
    Write-Host 'Package pruning passed: tests/cache/video data removed; source/models/notices preserved; junction and unowned-root checks rejected.'
} finally {
    if (Test-Path -LiteralPath $TaskLink) { Remove-Item -LiteralPath $TaskLink -Force }
    $TaskResolved = [IO.Path]::GetFullPath($TaskTemporary)
    $TaskPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($TaskResolved.StartsWith($TaskPrefix, [StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($TaskResolved).StartsWith('captcha-prune-test-')) {
        Remove-Item -LiteralPath $TaskResolved -Recurse -Force
    }
}