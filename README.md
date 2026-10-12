# Optional local OCR companion

这是验证码识别插件的独立本地组件，面向 **64 位 Windows 10/11**。插件默认使用在线识别；只有用户主动选择本地识别并同意安装后，才下载本组件。Python、识别引擎和模型不会放进浏览器插件。

## 普通用户安装

1. 在插件设置中开启本地识别，阅读识别效果和资源占用提示，选择安装。
2. 保留插件下载的小型配对文件，打开独立安装包一次。
3. 安装完成后返回插件，设置页自动连接后点击“保存设置”。若未自动连接，可点击“安装后重新连接”。

不需要了解 MCP，也不需要安装 Python、填写服务器地址或 API Key。组件装在当前用户的 `%LOCALAPPDATA%\\CaptchaLocalCompanion`，不会创建开机启动项或系统服务。Windows 对未签名安装器可能显示未知发布者提示，请先核对发布页面的文件校验值。

本地引擎使用通用文字识别模型，复杂验证码的识别效果可能明显低于在线服务。组件需要额外磁盘空间；模型首次识别时才加载，约两分钟不使用、关闭本地识别或断开浏览器连接后释放模型进程。实际资源占用随图片和电脑而异。

## 安全边界

- 通过浏览器原生连接与本机组件通信，不监听 HTTP 端口。
- 安装器只读取与本次安装包名称中的插件 ID 相同的 `captcha-local-setup-<插件ID>.json` 配对文件；未找到时让用户选择同类文件。
- 只在当前用户的 Chrome/Edge 登记经过校验的插件 ID，不开放通配来源。
- 模型文件和依赖随独立安装包提供，识别时不下载模型或向外发送图片。
- 只结束本组件自己创建的识别进程；不会扫描端口或结束其他 Python 服务。
- 不读取浏览器凭据、个人运行设置或开发助手配置。

## 卸载

先关闭插件的本地识别，再运行安装目录内的 `0.1.2\\uninstall.ps1`。脚本只撤销指向本组件的浏览器登记、删除本组件自己的安装文件；遇到占用文件或目录链接会停止并说明原因。

## 构建与检查

构建需要 Windows、Python 3.12 x64，以及 Visual Studio 提供的可再分发运行库。公开仓库的自动发布流程会在 Windows 构建机完成这些步骤，普通用户不需要安装构建工具。

```powershell
python tests/test-ocr-server.py
./scripts/check-native.ps1
./scripts/build-windows.ps1
```

脚本下载 Python 官方嵌入式包并核对固定 SHA-256，预装固定版本的 OCR 依赖，保留授权文件，清理第三方测试、缓存、人脸分类数据和视频专用插件，验证图片处理与完整识别，再打包到独立安装器。只清理当前构建目录，保留 OCR 模型、核心运行库和正常源文件。每个内部文件也记录 SHA-256，安装时校验。构建不会登记浏览器宿主或安装组件。发布检查会在构建机使用包内模型，离线识别自行生成的测试图片。

浏览器宿主名为 `captcha.local_ocr`。宿主用浏览器的长度前缀 JSON 消息处理 `PING`、`SOLVE`、`STOP`，内部调用标准 MCP `2025-06-18` 的 `recognize_captcha` 工具。工具约定见 [worker 源码](worker/ocr-server.py)。

Python 3.12.10 是官方提供 Windows 3.12 二进制包的最后维护版本；后续 3.12 安全发行仅提供源码。维护者应持续评估升级 Python 及识别依赖，并随新组件版本发布，而不是让用户现场安装开发环境。

## 授权与来源

本仓库自己的代码使用 MIT 许可。第三方软件保留各自许可，详见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 及安装包中的授权文件。

参考：[Microsoft Edge 原生消息](https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/native-messaging)、[Python 嵌入式发行版](https://docs.python.org/3.12/using/windows.html#the-embeddable-package)、[Microsoft 运行库本地部署](https://learn.microsoft.com/en-us/cpp/windows/choosing-a-deployment-method)。