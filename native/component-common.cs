using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace CaptchaLocal {
    internal static class Component {
        internal const string Version = "0.1.0";
        internal const string HostName = "captcha.local_ocr";
        internal const string Protocol = "2025-06-18";
        internal const int MaxInput = 4000000;
        internal const int MaxOutput = 1000000;
        internal static readonly Regex ExtensionId = new Regex("^[a-p]{32}$", RegexOptions.CultureInvariant);
        internal static JavaScriptSerializer Json() {
            return new JavaScriptSerializer { MaxJsonLength = MaxInput, RecursionLimit = 32 };
        }
        internal static Dictionary<string, object> Object(object value) {
            var result = value as Dictionary<string, object>;
            if (result == null) throw new InvalidDataException("消息格式不正确。");
            return result;
        }
        internal static string Text(Dictionary<string, object> value, string key, int limit) {
            object raw;
            if (!value.TryGetValue(key, out raw) || !(raw is string) || ((string)raw).Length > limit)
                throw new InvalidDataException("缺少或无效的 " + key + "。");
            return (string)raw;
        }
        internal static string ChildPath(string root, string relative) {
            if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.IndexOf(':') >= 0)
                throw new InvalidDataException("安装包路径不正确。");
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string result = Path.GetFullPath(Path.Combine(prefix, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!result.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("安装包包含目录之外的路径。");
            return result;
        }
        internal static IEnumerable<string> Origins(object raw) {
            var items = raw as IEnumerable;
            if (items == null || raw is string) yield break;
            foreach (var item in items) {
                var text = item as string;
                if (text == null || !text.StartsWith("chrome-extension://", StringComparison.Ordinal)) continue;
                string id = text.Substring("chrome-extension://".Length).TrimEnd('/');
                if (ExtensionId.IsMatch(id)) yield return "chrome-extension://" + id + "/";
            }
        }
        internal static byte[] ReadFrame(Stream input) {
            byte[] header = new byte[4];
            int count = input.Read(header, 0, header.Length);
            if (count == 0) return null;
            while (count < 4) {
                int next = input.Read(header, count, 4 - count);
                if (next == 0) throw new EndOfStreamException("消息长度不完整。");
                count += next;
            }
            uint length = (uint)(header[0] | header[1] << 8 | header[2] << 16 | header[3] << 24);
            if (length == 0 || length > MaxInput) throw new InvalidDataException("消息超过大小限制。");
            byte[] data = new byte[(int)length];
            count = 0;
            while (count < data.Length) {
                int next = input.Read(data, count, data.Length - count);
                if (next == 0) throw new EndOfStreamException("消息内容不完整。");
                count += next;
            }
            return data;
        }
        internal static void WriteFrame(Stream output, object value) {
            byte[] data = new UTF8Encoding(false, true).GetBytes(Json().Serialize(value));
            if (data.Length > MaxOutput) throw new InvalidDataException("回复超过大小限制。");
            int length = data.Length;
            byte[] header = { (byte)length, (byte)(length >> 8), (byte)(length >> 16), (byte)(length >> 24) };
            output.Write(header, 0, header.Length);
            output.Write(data, 0, data.Length);
            output.Flush();
        }
    }
}