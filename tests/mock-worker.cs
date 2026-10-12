using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Web.Script.Serialization;

internal static class MockWorker {
    private static int Main() {
        File.WriteAllText("mock-worker-pid.txt", Process.GetCurrentProcess().Id.ToString());
        var json = new JavaScriptSerializer { MaxJsonLength = 4000000 };
        bool initialized = false;
        string line;
        while ((line = Console.ReadLine()) != null) {
            var request = (Dictionary<string, object>)json.DeserializeObject(line);
            string method = (string)request["method"];
            if (method == "notifications/initialized") { initialized = true; continue; }
            object result;
            if (method == "initialize") {
                result = new { protocolVersion = "2025-06-18", capabilities = new { tools = new { } }, serverInfo = new { name = "mock", version = "0.1.2" } };
            } else if (method == "tools/call" && initialized) {
                var parameters = (Dictionary<string, object>)request["params"];
                var arguments = (Dictionary<string, object>)parameters["arguments"];
                if (!Object.Equals(parameters["name"], "recognize_captcha")) return 4;
                object id;
                arguments.TryGetValue("requestId", out id);
                if (Object.Equals(id, "slow")) {
                    File.WriteAllText("mock-solve-started.txt", "started");
                    System.Threading.Thread.Sleep(60000);
                }
                result = new { structuredContent = new { text = "AB12", confidence = 0.95, engine = "rapidocr", requestId = id ?? "" }, content = new object[0] };
            } else return 5;
            Console.WriteLine(json.Serialize(new { jsonrpc = "2.0", id = request["id"], result = result }));
            Console.Out.Flush();
        }
        return 0;
    }
}