using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace CaptchaLocal {
    internal sealed class WorkerSession : IDisposable {
        private readonly object gate = new object();
        private readonly object stateGate = new object();
        private bool busy, disconnected;
        private int epoch;
        private readonly string componentRoot;
        private Process worker;
        private OwnedJob job;
        private DateTime lastUse = DateTime.UtcNow;
        private readonly Timer idleTimer;
        private long sequence;
        internal WorkerSession(string root) {
            componentRoot = root;
            idleTimer = new Timer(ReleaseIdle, null, 15000, 15000);
        }
        internal bool Ready { get { lock (stateGate) { return worker != null && !worker.HasExited; } } }
        internal int Epoch { get { lock (stateGate) { return epoch; } } }
        private void ReleaseIdle(object ignored) {
            lock (stateGate) {
                if (!busy && worker != null && DateTime.UtcNow - lastUse >= TimeSpan.FromSeconds(120)) StopWorker();
            }
        }
        private string ReadLine(Process active, int timeout) {
            Task<string> pending = active.StandardOutput.ReadLineAsync();
            if (!pending.Wait(timeout)) throw new TimeoutException("本地识别耗时过长，请稍后重试。");
            string line = pending.Result;
            if (line == null || line.Length > Component.MaxOutput)
                throw new InvalidDataException("本地识别组件未返回有效结果。");
            return line;
        }
        private Dictionary<string, object> Request(string method, object parameters, int timeout) {
            long id = ++sequence;
            Process active;
            lock (stateGate) { active = worker; }
            if (active == null) throw new InvalidDataException("本地识别已停止。");
            WriteLine(active, new { jsonrpc = "2.0", id = id, method = method, @params = parameters });
            var response = Component.Object(Component.Json().DeserializeObject(ReadLine(active, timeout)));
            object responseId;
            if (!response.TryGetValue("id", out responseId) || Convert.ToInt64(responseId) != id)
                throw new InvalidDataException("本地识别组件回复编号不正确。");
            if (response.ContainsKey("error")) throw new InvalidDataException("本地识别组件暂时无法处理该请求。");
            object result;
            if (!response.TryGetValue("result", out result)) throw new InvalidDataException("本地识别组件回复不完整。");
            return Component.Object(result);
        }
        private static void WriteLine(Process active, object message) {
            byte[] data = new UTF8Encoding(false, true).GetBytes(Component.Json().Serialize(message) + "\n");
            active.StandardInput.BaseStream.Write(data, 0, data.Length);
            active.StandardInput.BaseStream.Flush();
        }
        private void EnsureWorker(int ticket) {
            lock (stateGate) {
            if (disconnected || ticket != epoch) throw new InvalidDataException("本地识别已停止。");
            if (worker != null && !worker.HasExited) return;
            StopWorker();
            string python = Component.ChildPath(componentRoot, "runtime/python.exe");
            string script = Component.ChildPath(componentRoot, "worker/ocr-server.py");
            if (!File.Exists(python) || !File.Exists(script))
                throw new InvalidDataException("本地识别组件文件不完整，请重新安装。");
            var start = new ProcessStartInfo(python, "-I \"" + script + "\"") {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = new UTF8Encoding(false, true),
                StandardErrorEncoding = new UTF8Encoding(false, true),
                WorkingDirectory = componentRoot
            };
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            start.EnvironmentVariables["OMP_NUM_THREADS"] = "2";
            start.EnvironmentVariables["OPENBLAS_NUM_THREADS"] = "2";
            worker = new Process { StartInfo = start, EnableRaisingEvents = true };
            worker.ErrorDataReceived += delegate { };
            if (!worker.Start()) throw new InvalidOperationException("无法启动本地识别组件。");
            job = new OwnedJob(worker);
            worker.BeginErrorReadLine();
            }
            var initialized = Request("initialize", new {
                protocolVersion = Component.Protocol,
                capabilities = new { },
                clientInfo = new { name = "captcha-local-bridge", version = Component.Version }
            }, 15000);
            object negotiated;
            if (!initialized.TryGetValue("protocolVersion", out negotiated) || !Object.Equals(negotiated, Component.Protocol))
                throw new InvalidDataException("本地识别组件版本不兼容，请重新安装。");
            Process active;
            lock (stateGate) { active = worker; }
            if (active == null) throw new InvalidDataException("本地识别已停止。");
            WriteLine(active, new { jsonrpc = "2.0", method = "notifications/initialized" });
        }
        internal object Solve(Dictionary<string, object> arguments, int ticket) {
            lock (gate) {
                lock (stateGate) {
                    if (disconnected || ticket != epoch) throw new InvalidDataException("本地识别已停止。");
                    busy = true; lastUse = DateTime.UtcNow;
                }
                try {
                    EnsureWorker(ticket);
                    var result = Request("tools/call", new { name = "recognize_captcha", arguments = arguments }, 60000);
                    object failed;
                    if (result.TryGetValue("isError", out failed) && Object.Equals(failed, true))
                        throw new InvalidDataException("本地识别失败，请尝试更清晰的图片或在线识别。");
                    object output;
                    if (!result.TryGetValue("structuredContent", out output))
                        throw new InvalidDataException("本地识别组件没有返回识别结果。");
                    var data = Component.Object(output);
                    Component.Text(data, "text", 1024);
                    return data;
                } catch {
                    Stop();
                    throw;
                } finally { lock (stateGate) { busy = false; lastUse = DateTime.UtcNow; } }
            }
        }
        private void StopWorker() {
            Process owned = worker;
            worker = null;
            if (job != null) { job.Dispose(); job = null; }
            if (owned == null) return;
            try { owned.StandardInput.Close(); } catch { }
            try { if (!owned.HasExited && !owned.WaitForExit(1500)) owned.Kill(); } catch { }
            try { owned.Dispose(); } catch { }
        }
        internal void Stop() { lock (stateGate) { epoch++; StopWorker(); } }
        public void Dispose() { idleTimer.Dispose(); lock (stateGate) { disconnected = true; epoch++; StopWorker(); } }
    }

    internal sealed class OwnedJob : IDisposable {
        private IntPtr handle;
        [StructLayout(LayoutKind.Sequential)]
        private struct BasicLimits {
            internal long ProcessTime, JobTime;
            internal uint Flags;
            internal UIntPtr MinimumWorkingSet, MaximumWorkingSet;
            internal uint ActiveProcesses;
            internal UIntPtr Affinity;
            internal uint Priority, Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct Counters {
            internal ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct ExtendedLimits {
            internal BasicLimits Basic;
            internal Counters Io;
            internal UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr job, int info, IntPtr limits, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);
        internal OwnedJob(Process process) {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new InvalidDataException("无法安全管理本地识别进程。");
            var limits = new ExtendedLimits();
            limits.Basic.Flags = 0x2000; // Windows closes only this job's child processes when its final handle closes.
            int size = Marshal.SizeOf(typeof(ExtendedLimits));
            IntPtr pointer = Marshal.AllocHGlobal(size);
            try {
                Marshal.StructureToPtr(limits, pointer, false);
                if (!SetInformationJobObject(handle, 9, pointer, (uint)size) || !AssignProcessToJobObject(handle, process.Handle)) {
                    Dispose();
                    throw new InvalidDataException("无法安全管理本地识别进程。");
                }
            } finally { Marshal.FreeHGlobal(pointer); }
        }
        public void Dispose() {
            if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        }
    }
    internal static class NativeHost {
        private static bool Authorized(string origin, string root) {
            if (String.IsNullOrEmpty(origin)) return false;
            try {
                string manifest = Path.GetFullPath(Path.Combine(root, "..", "captcha.local_ocr.json"));
                var value = Component.Object(Component.Json().DeserializeObject(File.ReadAllText(manifest, Encoding.UTF8)));
                object origins;
                if (!value.TryGetValue("allowed_origins", out origins)) return false;
                foreach (string allowed in Component.Origins(origins))
                    if (String.Equals(allowed, origin, StringComparison.Ordinal)) return true;
            } catch { }
            return false;
        }
        private static Dictionary<string, object> ValidateArguments(object raw) {
            var arguments = Component.Object(raw);
            Component.Text(arguments, "imageBase64", 3400000);
            object expected;
            if (arguments.TryGetValue("expectedLength", out expected)) {
                if (!(expected is int) || (int)expected < 0 || (int)expected > 64)
                    throw new InvalidDataException("识别长度不正确。");
            }
            if (arguments.ContainsKey("hintChars")) Component.Text(arguments, "hintChars", 256);
            if (arguments.ContainsKey("requestId")) Component.Text(arguments, "requestId", 128);
            var clean = new Dictionary<string, object>();
            foreach (string key in new [] { "imageBase64", "expectedLength", "hintChars", "requestId" }) {
                object value;
                if (arguments.TryGetValue(key, out value)) clean[key] = value;
            }
            return clean;
        }
        private static string SafeReason(Exception error) {
            return error is InvalidDataException || error is TimeoutException ? error.Message : "本地识别组件暂时不可用，请重新连接。";
        }
        private static void Reply(Stream output, object reply) {
            lock (output) {
                try { Component.WriteFrame(output, reply); } catch (IOException) { } catch (ObjectDisposedException) { }
            }
        }
        [STAThread]
        private static int Main(string[] args) {
            if (args.Length == 1 && args[0] == "--self-test") return SelfTest();
            string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
            if (args.Length == 0 || !Authorized(args[0], root)) return 2;
            using (var session = new WorkerSession(root))
            using (Stream input = Console.OpenStandardInput())
            using (Stream output = Console.OpenStandardOutput()) {
                Task pending = null;
                try {
                    while (true) {
                        byte[] frame;
                        try { frame = Component.ReadFrame(input); } catch { return 3; }
                        if (frame == null) break;
                        object id = null;
                        try {
                            var message = Component.Object(Component.Json().DeserializeObject(new UTF8Encoding(false, true).GetString(frame)));
                            object rawId;
                            if (message.TryGetValue("id", out rawId) && rawId is string && ((string)rawId).Length <= 128) id = rawId;
                            if (id == null) throw new InvalidDataException("消息编号不正确。");
                            string type = Component.Text(message, "type", 16);
                            object payload;
                            if (type == "PING") {
                                payload = new { installed = true, version = Component.Version, protocolVersion = Component.Protocol, engineLoaded = session.Ready };
                            } else if (type == "STOP") {
                                session.Stop();
                                payload = new { stopped = true };
                            } else if (type == "SOLVE") {
                                if (pending != null && !pending.IsCompleted) throw new InvalidDataException("本地组件正在识别，请稍后重试。");
                                object rawArguments;
                                if (!message.TryGetValue("payload", out rawArguments)) throw new InvalidDataException("识别请求不完整。");
                                var arguments = ValidateArguments(rawArguments);
                                var solveId = id;
                                int ticket = session.Epoch;
                                pending = Task.Run(delegate {
                                    try { Reply(output, new { id = solveId, ok = true, payload = session.Solve(arguments, ticket) }); }
                                    catch (Exception error) { Reply(output, new { id = solveId, ok = false, error = SafeReason(error) }); }
                                });
                                continue;
                            } else throw new InvalidDataException("不支持该操作。");
                            Reply(output, new { id = id, ok = true, payload = payload });
                        } catch (Exception error) {
                            Reply(output, new { id = id, ok = false, error = SafeReason(error) });
                        }
                    }
                } finally {
                    session.Dispose();
                    try { if (pending != null) pending.Wait(5000); } catch { }
                }
            }
            return 0;
        }
        private static int SelfTest() {
            try {
                byte[] utf8 = Encoding.UTF8.GetBytes("{\"id\":\"测试\"}");
                using (var stream = new MemoryStream()) {
                    Component.WriteFrame(stream, new { id = "测试" });
                    stream.Position = 0;
                    byte[] frame = Component.ReadFrame(stream);
                    if (Encoding.UTF8.GetString(frame) != Encoding.UTF8.GetString(utf8)) return 11;
                    if (Component.ReadFrame(stream) != null) return 12;
                }
                using (var oversized = new MemoryStream(new byte[] { 255, 255, 255, 127 })) {
                    try { Component.ReadFrame(oversized); return 13; } catch (InvalidDataException) { }
                }
                try { Component.ChildPath(Path.GetTempPath(), "../escape"); return 14; } catch (InvalidDataException) { }
                try { ValidateArguments(new Dictionary<string, object> { { "imageBase64", "AA==" }, { "expectedLength", true } }); return 15; } catch (InvalidDataException) { }
                using (var session = new WorkerSession(Path.GetTempPath())) {
                    if (session.Ready) return 16;
                    session.Stop();
                    if (session.Ready) return 17;
                }
                return 0;
            } catch { return 10; }
        }
    }
}