using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;
using UnityEngine.SceneManagement;
#if SMA_IL2CPP
using BepInEx.Unity.IL2CPP;
#endif

// Portable replacement for recovered AutoStart 1.2.0. Uses the same plugin ID.
[BepInPlugin("local.sma.voiceautostart", "SMA Voice AutoStart", "1.4.1")]
#if !SMA_GENERIC
[BepInDependency("local.sma.voicecapture")]
#endif
#if SMA_IL2CPP
public sealed class SMAVoiceAutoStart : BasePlugin {
    private static SMAVoiceAutoStart owner;
    private string sceneSignature;
    private BepInEx.Logging.ManualLogSource Logger { get { return Log; } }
    public override void Load() { Awake(); }
    public override bool Unload() { Shutdown(); return true; }
    internal static void DriverTick() { if (owner != null) { owner.CheckScenes(); owner.CheckReader(); } }
    internal static void DriverQuit() { if (owner != null) owner.Shutdown(); }
    private static string SceneSignature() {
        StringBuilder b = new StringBuilder();
        b.Append(SceneManager.GetActiveScene().handle);
        for (int i = 0; i < SceneManager.sceneCount; i++) b.Append('|').Append(SceneManager.GetSceneAt(i).handle);
        return b.ToString();
    }
    private void CheckScenes() {
        if (stopping) return;
        try {
            string current = SceneSignature();
            if (current != sceneSignature) { sceneSignature = current; ResetScene(); }
        } catch (Exception e) { Logger.LogWarning("SMA IL2CPP scene check: " + e.Message); }
    }
#else
public sealed class SMAVoiceAutoStart : BaseUnityPlugin {
#endif
    private static bool attempted;
    private Process reader;
    private string statusPath, lastStatus;
    private float nextStatus;
    private PortableVoice.SessionReport sessionReport;
    private void CheckReader() {
        if (stopping || Time.realtimeSinceStartup < nextStatus) return;
        nextStatus = Time.realtimeSinceStartup + 1f;
        try {
            if (statusPath == null || !File.Exists(statusPath)) return;
            string current = File.ReadAllText(statusPath, Encoding.UTF8).Trim();
            if (current != lastStatus) { lastStatus = current; Logger.LogInfo("SMA READER_STATUS | " + current); }
        } catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
#if !SMA_IL2CPP
    private void Update() { CheckReader(); }
#endif
    private string session, marker;
    private long generation;
    private int lastFrame = -1;
    private bool subscribed, stopping;
    private readonly UTF8Encoding utf8 = new UTF8Encoding(false);

    private void Awake() {
        ConfigEntry<bool> enabled = Config.Bind("Startup", "Enabled", true, "Start the local voice reader when the game starts.");
        ConfigEntry<bool> announce = Config.Bind("Audio", "Announce", true, "Speak a startup confirmation once the XTTS reader is ready.");
        if (!enabled.Value) { Logger.LogInfo("SMA AutoStart disabled in config."); return; }
        if (attempted) return;
        attempted = true;
        try {
            string pointer = Path.Combine(Paths.ConfigPath, "sma-voice-portable.paths");
            string[] paths = File.ReadAllLines(pointer, Encoding.UTF8);
            if (paths.Length != 2 || !Path.IsPathRooted(paths[0]) || !Path.IsPathRooted(paths[1]))
                throw new InvalidDataException("Invalid portable runtime pointer. Run INSTALAR.bat again.");
            string python = paths[0], runtime = paths[1];
            string launcher = Path.Combine(runtime, "iniciar.py");
            if (!File.Exists(python) || !File.Exists(launcher) || !File.Exists(Path.Combine(runtime, "instalacao.json")))
                throw new FileNotFoundException("Portable Python/runtime missing. Run INSTALAR.bat again.");
            string root = Directory.GetParent(Paths.BepInExRootPath).FullName;
            string queue = Path.Combine(Paths.BepInExRootPath, "SMA-Voice-Queue");
            Directory.CreateDirectory(queue);
            session = Guid.NewGuid().ToString("N");
            marker = Path.Combine(queue, "session-" + session + ".state");
            WriteMarker();
            statusPath = marker + ".status";
            string central = Path.Combine(Path.Combine(Paths.PluginPath,
#if SMA_GENERIC
                "SMA Voice"
#else
                "SMAVoiceCapture"
#endif
                ), "CONFIGURACOES.txt");
            bool enableLog = File.Exists(central) && new PortableVoice.VoiceSettings(central).Bool("ENABLE_LOG", true);
#if SMA_GENERIC
            if (enableLog) { sessionReport = new PortableVoice.SessionReport(); BepInEx.Logging.Logger.Listeners.Add(sessionReport); }
#endif
#if SMA_IL2CPP
            sceneSignature = SceneSignature();
            owner = this;
            AddComponent<SMAVoiceAutoStartDriver>();
#else
            SceneManager.activeSceneChanged += ActiveChanged;
            SceneManager.sceneLoaded += SceneLoaded;
            SceneManager.sceneUnloaded += SceneUnloaded;
            Application.quitting += Shutdown;
            subscribed = true;
#endif
            int pid;
            using (Process game = Process.GetCurrentProcess()) { pid = game.Id; }
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = python;
            info.WorkingDirectory = runtime;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.Arguments = "-u " + Quote(launcher) + " --autostart-root " + Quote(root)
                + " --game-pid " + pid.ToString(CultureInfo.InvariantCulture)
                + " --session-file " + Quote(marker) + " --status-file " + Quote(statusPath)
                + (enableLog ? " --session-report " + Quote(PortableVoice.SessionReport.ReportPath) : " --session-report-off")
                + (announce.Value ? " --startup-announce" : "");
            reader = Process.Start(info);
            if (reader == null) throw new InvalidOperationException("Process.Start returned null");
            reader.Exited += ReaderExited;
            reader.EnableRaisingEvents = true;
            Logger.LogInfo("SMA AutoStart 1.4.1: reader launched, session=" + session + "; wait for READER_STATUS READY");
        } catch (Exception e) {
            Logger.LogError("SMA AutoStart failed: " + e);
            Shutdown();
        }
    }

    // Windows command-line quoting; supports spaces, Unicode and trailing backslashes.
    private static string Quote(string value) {
        StringBuilder b = new StringBuilder("\""); int slash = 0;
        foreach (char c in value) {
            if (c == '\\') { slash++; continue; }
            if (c == '"') { b.Append('\\', slash * 2 + 1); b.Append(c); }
            else { b.Append('\\', slash); b.Append(c); }
            slash = 0;
        }
        b.Append('\\', slash * 2); b.Append('"'); return b.ToString();
    }
    private void WriteMarker() {
        string tmp = marker + ".tmp";
        try {
            File.WriteAllText(tmp, session + "\n" + generation.ToString(CultureInfo.InvariantCulture) + "\n" + DateTime.UtcNow.Ticks.ToString(CultureInfo.InvariantCulture) + "\n", utf8);
            for (int attempt = 0; ; attempt++) {
                try { if (File.Exists(marker)) File.Replace(tmp, marker, null); else File.Move(tmp, marker); break; }
                catch (IOException) { if (attempt >= 2) throw; System.Threading.Thread.Sleep(5); }
            }
        } finally { if (File.Exists(tmp)) File.Delete(tmp); }
    }
    private void ActiveChanged(Scene previous, Scene current) { ResetScene(); }
    private void SceneLoaded(Scene scene, LoadSceneMode mode) { ResetScene(); }
#if !SMA_IL2CPP
    private void SceneUnloaded(Scene scene) { ResetScene(); }
#endif
    private void ResetScene() {
        if (stopping || Time.frameCount == lastFrame) return;
        lastFrame = Time.frameCount;
        generation++;
        try { WriteMarker(); }
        catch (Exception e) { Logger.LogWarning("SMA scene marker failed: " + e.Message); }
    }
    private void ReaderExited(object sender, EventArgs args) {
        if (stopping) return;
        try { Logger.LogWarning("SMA reader exited: " + ((Process)sender).ExitCode + "; see session report if enabled. No automatic crash loop."); }
        catch (Exception) { }
    }
    private void CheckFinalReaderStatus() {
        try { if (statusPath != null && File.Exists(statusPath)) Logger.LogInfo("SMA READER_FINAL_STATUS | " + File.ReadAllText(statusPath, Encoding.UTF8).Trim()); } catch (Exception) { }
    }
    // Event subscription stays alive even if Unity destroys the original plugin owner.
    private void Shutdown() {
        if (stopping) return;
        stopping = true;
#if SMA_IL2CPP
        owner = null;
#else
        if (subscribed) {
            SceneManager.activeSceneChanged -= ActiveChanged;
            SceneManager.sceneLoaded -= SceneLoaded;
            SceneManager.sceneUnloaded -= SceneUnloaded;
            Application.quitting -= Shutdown;
        }
#endif
        if (reader != null) {
            try {
                reader.Exited -= ReaderExited;
                if (!reader.HasExited) {
                    File.WriteAllText(marker + ".stop", "stop", utf8);
                    if (!reader.WaitForExit(1500)) { Logger.LogWarning("SMA reader shutdown timeout; forcing exit"); reader.Kill(); reader.WaitForExit(500); }
                }
                CheckFinalReaderStatus();
                Logger.LogInfo("SMA SESSION_READER_END | exit=" + (reader.HasExited ? reader.ExitCode.ToString() : "unknown"));
            }
            catch (Exception e) { Logger.LogWarning("SMA reader shutdown: " + e.Message); }
            finally { reader.Dispose(); }
        }
        if (marker != null) {
            foreach (string path in new string[] { marker, marker+".status", marker+".stop" }) {
                try { File.Delete(path); } catch (Exception) { }
            }
        }
        Logger.LogInfo("SMA SESSION_END | game closing");
    }
}

#if SMA_IL2CPP
public sealed class SMAVoiceAutoStartDriver : MonoBehaviour {
    public SMAVoiceAutoStartDriver(IntPtr ptr) : base(ptr) { }
    private void Update() { SMAVoiceAutoStart.DriverTick(); }
    private void OnApplicationQuit() { SMAVoiceAutoStart.DriverQuit(); }
}
#endif
