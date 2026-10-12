using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace CaptchaLocal {
    internal sealed class SetupWindow : Form {
        private readonly Label status;
        private readonly ProgressBar progress;
        private readonly Button close;
        private bool finished;
        internal SetupWindow() {
            Text = "安装本地识别组件";
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new System.Drawing.Size(520, 235);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            Font = new System.Drawing.Font("Microsoft YaHei UI", 10);
            status = new Label { AutoSize = false, Left = 24, Top = 24, Width = 472, Height = 100, Text = "正在准备本地识别组件…\r\n首次识别才会加载模型，闲置后自动释放。" };
            progress = new ProgressBar { Left = 24, Top = 135, Width = 472, Height = 18, Style = ProgressBarStyle.Marquee };
            close = new Button { Left = 376, Top = 177, Width = 120, Height = 34, Text = "完成", Enabled = false };
            close.Click += delegate { Close(); };
            Controls.AddRange(new Control[] { status, progress, close });
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (!finished) e.Cancel = true; };
            Shown += async delegate {
                try {
                    var pairing = Setup.FindPairing();
                    if (pairing.Count == 0) {
                        status.Text = "请选择插件下载的配对文件（名称以 captcha-local-setup- 开头）。";
                        using (var dialog = new OpenFileDialog { Title = "选择插件的配对文件", Filter = "插件配对文件|captcha-local-setup-*.json", Multiselect = false, CheckFileExists = true }) {
                            if (dialog.ShowDialog(this) != DialogResult.OK) throw new InvalidDataException("尚未安装。请先在插件里点击安装，再打开安装包。");
                            pairing.Add(Setup.ReadPairing(dialog.FileName));
                        }
                    }
                    status.Text = "正在安装，完成后返回插件点击“连接本地组件”。\r\n无需安装 Python、填写服务器地址或 API Key。";
                    await Task.Run(delegate { Setup.Install(pairing); });
                    status.Text = "安装完成。返回插件，点击“连接本地组件”即可使用。\r\n组件只在识别时加载模型，不会开机启动。";
                    progress.Style = ProgressBarStyle.Continuous;
                    progress.Value = 100;
                } catch (Exception error) {
                    status.Text = error is InvalidDataException ? error.Message : "安装未完成。请关闭本地识别后重试，或从公开仓库重新下载安装包。";
                    progress.Style = ProgressBarStyle.Continuous;
                    progress.Value = 0;
                } finally { finished = true; close.Enabled = true; close.Focus(); }
            };
        }
    }

    internal static class Setup {
        private static readonly Regex PairingName = new Regex("^captcha-local-setup-([a-p]{32})(?: \\(\\d+\\))?\\.json$", RegexOptions.CultureInvariant);
        private static readonly Guid DownloadsId = new Guid("374DE290-123F-4565-9164-39C4925E467B");
        [DllImport("shell32.dll")]
        private static extern int SHGetKnownFolderPath([MarshalAs(UnmanagedType.LPStruct)] Guid folder, uint flags, IntPtr token, out IntPtr path);
        internal static string Downloads() {
            IntPtr pointer;
            int result = SHGetKnownFolderPath(DownloadsId, 0, IntPtr.Zero, out pointer);
            if (result != 0) throw new InvalidDataException("无法定位下载文件夹，请手动选择插件配对文件。");
            try { return Marshal.PtrToStringUni(pointer); } finally { Marshal.FreeCoTaskMem(pointer); }
        }
        internal static string ExpectedPairingId(string filename) {
            var match = Regex.Match(Path.GetFileName(filename), "^captcha-local-setup-0\\.1\\.0-([a-p]{32})(?: \\(\\d+\\))?\\.exe$", RegexOptions.CultureInvariant);
            return match.Success ? match.Groups[1].Value : null;
        }
        internal static List<string> FindPairing() {
            var result = new List<string>();
            string expected = ExpectedPairingId(Process.GetCurrentProcess().MainModule.FileName);
            if (expected == null) return result;
            string downloads;
            try { downloads = Downloads(); } catch { return result; }
            if (!Directory.Exists(downloads)) return result;
            foreach (string file in Directory.EnumerateFiles(downloads, "captcha-local-setup-" + expected + "*.json").Take(100)) {
                var name = PairingName.Match(Path.GetFileName(file));
                if (!name.Success || name.Groups[1].Value != expected) continue;
                try {
                    string id = ReadPairing(file);
                    if (id == expected) { result.Add(id); break; }
                } catch { }
            }
            return result;
        }
        internal static string ReadPairing(string path) {
            var name = PairingName.Match(Path.GetFileName(path));
            if (!name.Success || new FileInfo(path).Length > 4096)
                throw new InvalidDataException("这不是插件生成的有效配对文件。请在插件里重新下载。");
            var value = Component.Object(Component.Json().DeserializeObject(File.ReadAllText(path, Encoding.UTF8)));
            string id = Component.Text(value, "extensionId", 32);
            if (!Component.ExtensionId.IsMatch(id) || id != name.Groups[1].Value ||
                Component.Text(value, "hostName", 64) != Component.HostName ||
                Component.Text(value, "componentVersion", 32) != Component.Version)
                throw new InvalidDataException("配对文件与安装包不匹配。请在插件里重新下载安装。");
            return id;
        }
        private static Stream Resource(string name) {
            Stream result = Assembly.GetExecutingAssembly().GetManifestResourceStream(name);
            if (result == null) throw new InvalidDataException("安装包文件不完整，请重新下载。");
            return result;
        }
        private static string Digest(Stream input) {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
        }
        private static string ResourceText(string name) {
            using (Stream input = Resource(name))
            using (var reader = new StreamReader(input, Encoding.UTF8)) return reader.ReadToEnd().Trim();
        }
        private static void NoReparse(string directory) {
            if (Directory.Exists(directory) && (File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("组件目录不是普通文件夹，无法安全安装。");
        }
        private static void VerifyFiles(string directory, Dictionary<string, object> hashes) {
            foreach (var item in hashes) {
                string file = Component.ChildPath(directory, item.Key);
                if (!File.Exists(file) || (File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("组件文件不完整，请关闭本地识别后重新安装。");
                using (Stream input = File.OpenRead(file))
                    if (!String.Equals(Digest(input), item.Value as string, StringComparison.Ordinal))
                        throw new InvalidDataException("组件文件校验未通过，请重新下载并安装。");
            }
        }
        internal static void Install(IList<string> ids) {
            if (!Environment.Is64BitOperatingSystem) throw new InvalidDataException("此版本需要 64 位 Windows。");
            if (ids.Count == 0 || ids.Any(id => !Component.ExtensionId.IsMatch(id)))
                throw new InvalidDataException("插件配对信息无效。");
            string app = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CaptchaLocalCompanion");
            NoReparse(app);
            Directory.CreateDirectory(app);
            string version = Component.ChildPath(app, Component.Version);
            NoReparse(version);
            var hashes = Component.Object(Component.Json().DeserializeObject(ResourceText("payload-files.json")));
            string stage = Component.ChildPath(app, ".staging-" + Guid.NewGuid().ToString("N"));
            try {
                if (!Directory.Exists(version)) {
                    Directory.CreateDirectory(stage);
                    using (Stream archive = Resource("payload.zip")) {
                        if (Digest(archive) != ResourceText("payload-sha256.txt"))
                            throw new InvalidDataException("安装包校验未通过，请重新下载。");
                        archive.Position = 0;
                        using (var zip = new ZipArchive(archive, ZipArchiveMode.Read)) {
                            long total = 0;
                            foreach (var entry in zip.Entries) {
                                string destination = Component.ChildPath(stage, entry.FullName);
                                total += entry.Length;
                                if (total > 1200000000 || entry.Length > 300000000)
                                    throw new InvalidDataException("安装包超过大小限制。");
                                if (entry.FullName.EndsWith("/", StringComparison.Ordinal)) { Directory.CreateDirectory(destination); continue; }
                                if (!hashes.ContainsKey(entry.FullName)) throw new InvalidDataException("安装包包含未登记的文件。");
                                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                                using (var source = entry.Open())
                                using (var target = new FileStream(destination, FileMode.CreateNew, FileAccess.Write)) source.CopyTo(target);
                            }
                        }
                    }
                    VerifyFiles(stage, hashes);
                    Directory.Move(stage, version);
                } else VerifyFiles(version, hashes);
                foreach (string required in new [] { "native/captcha-local-host.exe", "runtime/python.exe", "worker/ocr-server.py", "uninstall.ps1" })
                    if (!File.Exists(Component.ChildPath(version, required))) throw new InvalidDataException("安装包缺少必需文件。");
                string manifest = Component.ChildPath(app, Component.HostName + ".json");
                var origins = new HashSet<string>(ids.Select(id => "chrome-extension://" + id + "/"), StringComparer.Ordinal);
                if (File.Exists(manifest)) {
                    try {
                        var current = Component.Object(Component.Json().DeserializeObject(File.ReadAllText(manifest, Encoding.UTF8)));
                        object allowed;
                        if (current.TryGetValue("allowed_origins", out allowed))
                            foreach (string origin in Component.Origins(allowed)) origins.Add(origin);
                    } catch { }
                }
                File.WriteAllText(manifest, Component.Json().Serialize(new {
                    name = Component.HostName,
                    description = "Optional local OCR companion",
                    path = Component.ChildPath(version, "native/captcha-local-host.exe"),
                    type = "stdio",
                    allowed_origins = origins.OrderBy(item => item).ToArray()
                }), new UTF8Encoding(false));
                File.WriteAllText(Component.ChildPath(app, ".component-owner"), "captcha-local-companion\n", new UTF8Encoding(false));
                foreach (string browser in new [] { "Software\\Google\\Chrome\\NativeMessagingHosts\\", "Software\\Microsoft\\Edge\\NativeMessagingHosts\\" }) {
                    using (RegistryKey key = Registry.CurrentUser.CreateSubKey(browser + Component.HostName)) key.SetValue("", manifest, RegistryValueKind.String);
                }
            } finally {
                if (Directory.Exists(stage)) {
                    NoReparse(stage);
                    Directory.Delete(stage, true);
                }
            }
        }
        private static int CheckPackage() {
            try {
                var hashes = Component.Object(Component.Json().DeserializeObject(ResourceText("payload-files.json")));
                using (Stream archive = Resource("payload.zip")) {
                    if (Digest(archive) != ResourceText("payload-sha256.txt")) return 31;
                    archive.Position = 0;
                    using (var zip = new ZipArchive(archive, ZipArchiveMode.Read)) {
                        int seen = 0;
                        foreach (var entry in zip.Entries) {
                            Component.ChildPath(Path.GetTempPath(), entry.FullName);
                            if (entry.FullName.EndsWith("/", StringComparison.Ordinal)) continue;
                            object expected;
                            if (!hashes.TryGetValue(entry.FullName, out expected)) return 32;
                            using (Stream file = entry.Open()) if (Digest(file) != expected as string) return 33;
                            seen++;
                        }
                        if (seen != hashes.Count) return 34;
                    }
                }
                return 0;
            } catch { return 30; }
        }
        private static int SelfTest() {
            string directory = Path.Combine(Path.GetTempPath(), "captcha-pairing-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try {
                string id = new string('a', 32);
                if (ExpectedPairingId("captcha-local-setup-0.1.0-" + id + ".exe") != id) return 21;
                if (ExpectedPairingId("captcha-local-setup-0.1.0-" + id + " (1).exe") != id) return 22;
                if (ExpectedPairingId("captcha-local-setup-0.1.0.exe") != null) return 23;
                if (ExpectedPairingId("captcha-local-setup-0.1.0-" + new string('x', 32) + ".exe") != null) return 24;
                string file = Component.ChildPath(directory, "captcha-local-setup-" + id + ".json");
                File.WriteAllText(file, Component.Json().Serialize(new { extensionId = id, hostName = Component.HostName, componentVersion = Component.Version }));
                if (ReadPairing(file) != id) return 25;
                File.WriteAllText(file, Component.Json().Serialize(new { extensionId = new string('b', 32), hostName = Component.HostName, componentVersion = Component.Version }));
                try { ReadPairing(file); return 26; } catch (InvalidDataException) { }
                File.Delete(file);
                return 0;
            } catch { return 20; }
            finally {
                foreach (string file in Directory.GetFiles(directory)) File.Delete(file);
                Directory.Delete(directory);
            }
        }
        [STAThread]
        private static int Main(string[] args) {
            if (args.Length == 1 && args[0] == "--self-test") return SelfTest();
            if (args.Length == 1 && args[0] == "--check-package") return CheckPackage();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupWindow());
            return 0;
        }
    }
}