using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Diagnostics;
using BepInEx;
using BepInEx.Logging;

namespace PortableVoice {
    // Both DLLs calculate the same path; only one listener is registered per install mode.
    // A Windows named mutex coordinates append operations with the Python reader.
    internal sealed class SessionReport : ILogListener {
        internal static string ReportPath {
            get {
                using (Process p = Process.GetCurrentProcess()) {
                    return Path.Combine(Directory.GetParent(Paths.BepInExRootPath).FullName,
                        "SMA_VOICE_" + p.StartTime.ToUniversalTime().ToString("yyyyMMdd_HHmmss_fff") + "_" + p.Id + ".log");
                }
            }
        }
        internal static string MutexName(string path) { return @"Local\SMA_VOICE_" + Path.GetFileNameWithoutExtension(path); }
        private readonly string path;
        private readonly Mutex gate;
        private bool disposed;
        internal SessionReport() {
            path = ReportPath;
            using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite)) { }
            gate = new Mutex(false, MutexName(path));
            Append("SESSION", "Inicio da sessao | UTC | Unity " + UnityEngine.Application.unityVersion);
        }
        private void Append(string source, string text) {
            lock (this) {
                if (disposed) return;
                bool acquired = false;
                try {
                    try { acquired = gate.WaitOne(1000); } catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) return;
                    using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                    using (var writer = new StreamWriter(stream, new UTF8Encoding(false))) {
                        writer.WriteLine(DateTime.UtcNow.ToString("o") + " [" + source + "] " + text.Replace("\r", " ").Replace("\n", "\\n"));
                    }
                } catch (Exception) { /* Diagnostics must never break the game or recurse into BepInEx. */ }
                finally { if (acquired) gate.ReleaseMutex(); }
            }
        }
        // BepInEx 6 requires this getter on ILogListener. BepInEx 5 accepts it
        // as an ordinary extra property. Source filtering remains in LogEvent.
        public LogLevel LogLevelFilter { get { return LogLevel.All; } }
        public void LogEvent(object sender, LogEventArgs e) {
            string name = e.Source.SourceName;
            if (name == "SMA Voice Capture" || name == "SMA Voice AutoStart") Append(name + "/" + e.Level, Convert.ToString(e.Data));
        }
        public void Dispose() { lock (this) { if (disposed) return; disposed=true; gate.Dispose(); } }
    }
}
