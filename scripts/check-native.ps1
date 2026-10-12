param([string]$PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
$TaskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TaskTestRoot = Join-Path ([IO.Path]::GetTempPath()) ('captcha-native-test-' + [Guid]::NewGuid().ToString('N'))
$TaskVersion = Join-Path $TaskTestRoot '0.1.0'
$TaskNative = Join-Path $TaskVersion 'native'
$TaskRuntime = Join-Path $TaskVersion 'runtime'
$TaskWorker = Join-Path $TaskVersion 'worker'
$TaskCsc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
foreach ($TaskDirectory in @($TaskNative, $TaskRuntime, $TaskWorker)) { [IO.Directory]::CreateDirectory($TaskDirectory) | Out-Null }
try {
    & $TaskCsc '/nologo' '/target:exe' '/platform:x64' '/r:System.Web.Extensions.dll' ('/out:' + (Join-Path $TaskNative 'captcha-local-host.exe')) (Join-Path $TaskRoot 'native\component-common.cs') (Join-Path $TaskRoot 'native\native-host.cs')
    if ($LASTEXITCODE -ne 0) { throw '本机连接程序编译失败。' }
    & (Join-Path $TaskNative 'captcha-local-host.exe') '--self-test'
    if ($LASTEXITCODE -ne 0) { throw '本机连接程序自检失败。' }
    & $TaskCsc '/nologo' '/target:exe' '/platform:x64' '/r:System.Web.Extensions.dll' ('/out:' + (Join-Path $TaskRuntime 'python.exe')) (Join-Path $TaskRoot 'tests\mock-worker.cs')
    if ($LASTEXITCODE -ne 0) { throw '模拟识别程序编译失败。' }
    [IO.File]::WriteAllText((Join-Path $TaskWorker 'ocr-server.py'), '# Mock marker; no Python or OCR engine is launched.')
    $TaskManifest = @{ allowed_origins = @('chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/') } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $TaskTestRoot 'captcha.local_ocr.json'), $TaskManifest)
    & $TaskCsc '/nologo' '/target:exe' '/platform:x64' '/r:System.Web.Extensions.dll' '/r:System.Windows.Forms.dll' '/r:System.Drawing.dll' '/r:System.IO.Compression.dll' ('/out:' + (Join-Path $TaskTestRoot 'setup-check.exe')) (Join-Path $TaskRoot 'native\component-common.cs') (Join-Path $TaskRoot 'native\install-setup.cs')
    if ($LASTEXITCODE -ne 0) { throw '安装器编译失败。' }
    & (Join-Path $TaskTestRoot 'setup-check.exe') '--self-test'
    if ($LASTEXITCODE -ne 0) { throw '安装配对信息校验失败。' }
    & $PythonCommand (Join-Path $TaskRoot 'tests\check-native.py') $TaskTestRoot
    if ($LASTEXITCODE -ne 0) { throw '本机消息协议检查失败。' }
} finally {
    $TaskResolved = [IO.Path]::GetFullPath($TaskTestRoot)
    $TaskTempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($TaskResolved.StartsWith($TaskTempPrefix, [StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($TaskResolved).StartsWith('captcha-native-test-')) {
        Remove-Item -LiteralPath $TaskResolved -Recurse -Force
    }
}