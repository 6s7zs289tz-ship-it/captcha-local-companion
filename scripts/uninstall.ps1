param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
$TaskAppRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CaptchaLocalCompanion'))
$TaskManifest = Join-Path $TaskAppRoot 'captcha.local_ocr.json'
$TaskOwner = Join-Path $TaskAppRoot '.component-owner'
if (-not (Test-Path -LiteralPath $TaskOwner) -or ([IO.File]::ReadAllText($TaskOwner).Trim() -ne 'captcha-local-companion')) {
    throw '未找到本组件的安装记录，未删除任何文件。'
}
if ((Get-Item -LiteralPath $TaskAppRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw '组件目录不是普通文件夹，无法安全卸载。'
}
$TaskBrowsers = @('HKCU:\Software\Google\Chrome\NativeMessagingHosts\captcha.local_ocr', 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\captcha.local_ocr')
foreach ($TaskKey in $TaskBrowsers) {
    if (Test-Path -LiteralPath $TaskKey) {
        $TaskRegistered = (Get-Item -LiteralPath $TaskKey).GetValue('')
        if ($TaskRegistered -eq $TaskManifest) { Remove-Item -LiteralPath $TaskKey }
    }
}
# Close local recognition in the browser first. Do not find or kill unrelated Python processes.
$TaskAllFiles = Get-ChildItem -LiteralPath $TaskAppRoot -Recurse -Force
if ($TaskAllFiles | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
    throw '组件目录包含链接，已撤销浏览器登记；请手动检查组件文件夹。'
}
try {
    Remove-Item -LiteralPath $TaskAppRoot -Recurse -Force
    if (-not $Quiet) { Write-Host '本地识别组件已卸载。' }
} catch {
    throw '浏览器登记已撤销。请在插件中关闭本地识别，关闭浏览器，再重新运行卸载脚本。'
}