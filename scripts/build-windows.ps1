param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\dist'),
    [string]$PythonCommand = 'python',
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$TaskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TaskOut = [IO.Path]::GetFullPath($OutputDirectory)
$TaskStage = Join-Path $TaskOut 'payload'
$TaskCsc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$TaskVersion = '0.1.0'
$TaskPythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
$TaskPythonSha = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
if (-not (Test-Path -LiteralPath $TaskCsc)) { throw '需要 Windows 自带的 .NET Framework 4.x 编译器。' }
if (Test-Path -LiteralPath $TaskStage) { throw '构建输出已存在，请使用一个新的输出目录，避免覆盖旧构建。' }
[IO.Directory]::CreateDirectory($TaskStage) | Out-Null
$TaskRuntime = Join-Path $TaskStage 'runtime'
$TaskNative = Join-Path $TaskStage 'native'
$TaskWorker = Join-Path $TaskStage 'worker'
[IO.Directory]::CreateDirectory($TaskRuntime) | Out-Null
[IO.Directory]::CreateDirectory($TaskNative) | Out-Null
[IO.Directory]::CreateDirectory($TaskWorker) | Out-Null
& $TaskCsc '/nologo' '/target:winexe' '/platform:x64' '/optimize+' '/r:System.Web.Extensions.dll' ('/out:' + (Join-Path $TaskNative 'captcha-local-host.exe')) (Join-Path $TaskRoot 'native\component-common.cs') (Join-Path $TaskRoot 'native\native-host.cs')
if ($LASTEXITCODE -ne 0) { throw '本机连接程序编译失败。' }
& (Join-Path $TaskNative 'captcha-local-host.exe') '--self-test'
if ($LASTEXITCODE -ne 0) { throw '本机连接程序自检失败。' }
Copy-Item -LiteralPath (Join-Path $TaskRoot 'worker\ocr-server.py') -Destination (Join-Path $TaskWorker 'ocr-server.py')
Copy-Item -LiteralPath (Join-Path $TaskRoot 'scripts\uninstall.ps1') -Destination (Join-Path $TaskStage 'uninstall.ps1')
foreach ($TaskNotice in @('LICENSE', 'THIRD-PARTY-NOTICES.md', 'requirements.txt')) {
    Copy-Item -LiteralPath (Join-Path $TaskRoot $TaskNotice) -Destination (Join-Path $TaskStage $TaskNotice)
}
if (-not $SkipDependencies) {
    $TaskPythonZip = Join-Path $TaskOut 'python-embed.zip'
    Invoke-WebRequest -Uri $TaskPythonUrl -OutFile $TaskPythonZip
    if ((Get-FileHash -LiteralPath $TaskPythonZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $TaskPythonSha) { throw 'Python 官方包校验失败。' }
    Expand-Archive -LiteralPath $TaskPythonZip -DestinationPath $TaskRuntime
    $TaskSitePackages = Join-Path $TaskRuntime 'Lib\site-packages'
    [IO.Directory]::CreateDirectory($TaskSitePackages) | Out-Null
    & $PythonCommand '-m' 'pip' 'install' '--disable-pip-version-check' '--only-binary=:all:' '--no-compile' '--target' $TaskSitePackages '-r' (Join-Path $TaskRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '识别依赖下载失败。' }
    [IO.File]::WriteAllText((Join-Path $TaskRuntime 'python312._pth'), "python312.zip`n.`nLib/site-packages`nimport site`n", [Text.UTF8Encoding]::new($false))
    # Ship Microsoft's app-local CRT from the licensed Visual Studio build runner.
    $TaskVsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $TaskVsWhere)) { throw '构建机需要 Visual Studio 的可再分发运行库。' }
    $TaskVsPath = & $TaskVsWhere '-latest' '-products' '*' '-property' 'installationPath'
    $TaskCrt = Get-Item -Path (Join-Path $TaskVsPath 'VC\Redist\MSVC\*\x64\Microsoft.VC143.CRT') | Where-Object { $_.PSIsContainer } | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $TaskCrt) { throw '未找到 Visual C++ x64 可再分发运行库，拒绝生成不完整安装包。' }
    Get-ChildItem -LiteralPath $TaskCrt.FullName -Filter '*.dll' | Copy-Item -Destination $TaskRuntime
    $TaskPythonExe = Join-Path $TaskRuntime 'python.exe'
    & $TaskPythonExe '-I' (Join-Path $TaskRoot 'tests\check-bundle.py') $TaskStage
    if ($LASTEXITCODE -ne 0) { throw '安装包内的运行环境检查失败。' }
}
$TaskHashes = [ordered]@{}
$TaskFiles = Get-ChildItem -LiteralPath $TaskStage -File -Recurse | Sort-Object FullName
foreach ($TaskFile in $TaskFiles) {
    $TaskRelative = $TaskFile.FullName.Substring($TaskStage.Length + 1).Replace('\','/')
    $TaskHashes[$TaskRelative] = (Get-FileHash -LiteralPath $TaskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$TaskFilesManifest = Join-Path $TaskOut 'payload-files.json'
[IO.File]::WriteAllText($TaskFilesManifest, ($TaskHashes | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
Add-Type -AssemblyName System.IO.Compression.FileSystem
$TaskPayloadZip = Join-Path $TaskOut 'payload.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($TaskStage, $TaskPayloadZip, [IO.Compression.CompressionLevel]::Optimal, $false)
$TaskPayloadSha = Join-Path $TaskOut 'payload-sha256.txt'
[IO.File]::WriteAllText($TaskPayloadSha, (Get-FileHash -LiteralPath $TaskPayloadZip -Algorithm SHA256).Hash.ToLowerInvariant(), [Text.UTF8Encoding]::new($false))
$TaskSetup = Join-Path $TaskOut ('captcha-local-setup-' + $TaskVersion + '.exe')
& $TaskCsc '/nologo' '/target:winexe' '/platform:x64' '/optimize+' '/r:System.Web.Extensions.dll' '/r:System.Windows.Forms.dll' '/r:System.Drawing.dll' '/r:System.IO.Compression.dll' ('/resource:' + $TaskPayloadZip + ',payload.zip') ('/resource:' + $TaskFilesManifest + ',payload-files.json') ('/resource:' + $TaskPayloadSha + ',payload-sha256.txt') ('/out:' + $TaskSetup) (Join-Path $TaskRoot 'native\component-common.cs') (Join-Path $TaskRoot 'native\install-setup.cs')
if ($LASTEXITCODE -ne 0) { throw '独立安装器编译失败。' }
& $TaskSetup '--check-package'
if ($LASTEXITCODE -ne 0) { throw '安装器资源校验失败。' }
$TaskSetupHash = (Get-FileHash -LiteralPath $TaskSetup -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($TaskSetup + '.sha256'), ($TaskSetupHash + '  ' + [IO.Path]::GetFileName($TaskSetup) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Host ('已生成独立安装包：' + $TaskSetup)
if ($SkipDependencies) { Write-Warning '本次仅检查打包链路，不是可发布安装包。' }