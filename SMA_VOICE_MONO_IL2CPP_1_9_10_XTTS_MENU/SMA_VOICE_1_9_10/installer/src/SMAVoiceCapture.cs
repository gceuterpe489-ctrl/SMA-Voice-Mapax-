using System;
using System.IO;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;
#if SMA_IL2CPP
using BepInEx.Unity.IL2CPP;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
#endif

[BepInPlugin("local.sma.voicecapture", "SMA Voice Capture", "0.10.13")]
#if SMA_IL2CPP
public sealed class SMAVoiceCapture : BasePlugin
#else
public sealed class SMAVoiceCapture : BaseUnityPlugin
#endif
{
    private const string GameAssembly = "Assembly-D_C_Dependientes_ReSc.DialogueSys";
    private static SMAVoiceCapture instance;
    private Harmony harmony;
    private SMAVoiceTickDriver driver;
    private bool quitting;
    private PortableVoice.SessionReport sessionReport;
    private bool inspectorEnabled = true;
    private float nextInspector;
    private int lastTickFrame = -1;
    private float nextHeartbeat;
    private int translatorCallbackCount, textCallbackCount, subtitleCallbackCount;
    private string tickRoute = "not-started";
    private ConfigEntry<string> allowedPaths, allowedNames, source, allowedIds;
    private ConfigEntry<string> uiPaths;
    private ConfigEntry<bool> uiFallback, pollEnabled;
    private ConfigEntry<bool> nativeBox, nativeUnknownNpc;
    // Native dialogue is independent of the visual text/portrait lifecycle.
    private sealed class BoxLine {
        public string Actor, Name, Alias, Original, Spoken, Origin, Raw;
        public bool Ready, Sent, Failed, TranslationPublished;
        public string EventPath;
        public IntPtr ToolkitPointer;
        public float Created, LastSeen, SentAt;
    }
    private readonly List<BoxLine> boxLines = new List<BoxLine>();
    private readonly HashSet<MethodBase> hookedSubtitleMethods = new HashSet<MethodBase>();
    private int boxScene = Int32.MinValue;
    private int nativeAccepted, nativeSent, boxUiSent, barkSent, barkBlocked;
#if SMA_IL2CPP
    private bool enableCmaBark = true;
    private bool enableCmaFixedBox = true;
    private Type fixedDocumentType, fixedVisualType, fixedTextType;
    private Component fixedDocument;
    private float nextFixedScan, fixedChanged, nextFixedError;
    private string fixedKey = "", fixedLastSource = "", fixedLastSpoken = "", fixedLastActor = "";
    private bool fixedReported;
    private BoxLine fixedPending;
    private string fixedDiagnostic = "";
    private int fixedObserved, fixedSent;
    private readonly Dictionary<IntPtr, TranslationNotice> fixedNotices = new Dictionary<IntPtr, TranslationNotice>();
#else
    private bool enableMonoBarkRecovery = true;
    private int controllerHooks;
#endif
    private bool BarkRecoveryEnabled() {
#if SMA_IL2CPP
        return enableCmaBark;
#else
        // Do not broaden an existing Mono filter when the native controller is available.
        return enableMonoBarkRecovery && (pollFemaleBark.Value || controllerHooks == 0);
#endif
    }
    private int barkObserved, barkEvidenceUsed;
    private readonly Dictionary<int, BarkWrite> barkWrites = new Dictionary<int, BarkWrite>();
    private readonly Dictionary<int, BarkWrite> boxWrites = new Dictionary<int, BarkWrite>();
    private sealed class BarkWrite { public string Text; public DateTime Changed; }
    // Setters can fire repeatedly for the same text. Only a real change renews evidence.
    private void RememberBarkWrite(Component c, string value) { RememberWrite(barkWrites, c, value); }
    private void RememberBoxWrite(Component c, string value) { RememberWrite(boxWrites, c, value); }
    private void RememberWrite(Dictionary<int, BarkWrite> writes, Component c, string value) {
        int id = c.GetInstanceID(); string text = CleanPoll(value);
        lock (writes) {
            BarkWrite prev;
            if (writes.TryGetValue(id, out prev) && prev.Text == text) return;
            if (writes.Count >= 256 && !writes.ContainsKey(id)) writes.Clear();
            writes[id] = new BarkWrite { Text = text, Changed = DateTime.UtcNow };
        }
    }
    private bool FreshBarkEvidence(Component c, string current, out string route) { return FreshTextEvidence(barkWrites, c, current, out route); }
    private bool FreshBoxEvidence(Component c, string current, out string route) { return FreshTextEvidence(boxWrites, c, current, out route); }
    private bool FreshTextEvidence(Dictionary<int, BarkWrite> writes, Component c, string current, out string route) {
        route = "none";
        if (String.IsNullOrWhiteSpace(current) || !c.gameObject.activeInHierarchy) return false;
        Behaviour behaviour = c as Behaviour;
        if (behaviour != null && !behaviour.isActiveAndEnabled) return false;
        DateTime now = DateTime.UtcNow;
        BarkWrite write;
        lock (writes) {
            if (writes.TryGetValue(c.GetInstanceID(), out write) && write.Text == current &&
                (now - write.Changed).TotalSeconds <= 4) { route = "setter"; return true; }
        }
        TranslationNotice notice;
        if (translatorLatest.TryGetValue(c.GetInstanceID(), out notice) && SameComponent(notice.Component, c) &&
            (now - notice.Changed).TotalSeconds <= 4 &&
            (current == CleanPoll(notice.Original) || current == CleanPoll(notice.Translation))) {
            route = "translator"; return true;
        }
        return false;
    }
    private float nextNativeHookRetry;
    private int nativeHookRetries;
    private readonly HashSet<string> boxDiscoveryPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    private ConfigEntry<string> pollNames;
    private ConfigEntry<bool> pollFemaleBark, pollSecondaryBark;
    private ConfigEntry<bool> translatorEnabled;
    private ConfigEntry<float> translatorWait, subtitleReadyWait, subtitleFallbackWait;
    private Type translatorScanner, translatorCore;
    private MethodInfo getOriginal, getTranslation;
    private bool translatorInstalled;
    private float nextTranslatorTry;
    private readonly object translatorLock = new object();
    private readonly List<TranslationNotice> translatorNotices = new List<TranslationNotice>();
    private readonly Dictionary<int, TranslationNotice> translatorLatest = new Dictionary<int, TranslationNotice>();
    private class TranslationNotice { public object Component; public string Original, Translation; public DateTime Received, Changed; }

    // Only actual game GUIDs are persisted by the reader. A prefab path is not an ID.
    private Type characterType;
    private readonly Dictionary<int, CharacterVoiceIdentity> femaleRoots = new Dictionary<int, CharacterVoiceIdentity>();
    private class CharacterVoiceIdentity { public string Id, Name, FullName, Alias; }
    private readonly Dictionary<int, string> liveAliases = new Dictionary<int, string>();
    private readonly Dictionary<int, string> liveAliasNames = new Dictionary<int, string>();
    private string RuntimeAlias(Component c, string name) {
        int id = c.GetInstanceID(); string token, old;
        if (!liveAliases.TryGetValue(id, out token) || (liveAliasNames.TryGetValue(id, out old) && old.Length > 0 && name.Length > 0 && !old.Equals(name, StringComparison.OrdinalIgnoreCase))) { token = "live:" + Guid.NewGuid().ToString("N"); liveAliases[id] = token; }
        if (name.Length > 0 || !liveAliasNames.ContainsKey(id)) liveAliasNames[id] = name;
        return token;
    }
    private string lastIdentityReport = "";
    private readonly HashSet<string> registryNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    private DateTime registryStamp = DateTime.MinValue;
    private void RefreshRegistryNames()
    {
        string file = Path.Combine(spool, "subtitle-model-names.txt");
        try {
            if (!File.Exists(file)) { registryNames.Clear(); registryStamp = DateTime.MinValue; return; }
            DateTime stamp = File.GetLastWriteTimeUtc(file);
            if (stamp == registryStamp) return;
            string[] lines = File.ReadAllLines(file, Encoding.UTF8);
            registryNames.Clear();
            foreach (string line in lines) if (!PlaceholderName(line)) registryNames.Add(NormalizeName(line));
            registryStamp = stamp;
            Logger.LogInfo("SMA subtitle registry: " + registryNames.Count + " model names loaded");
        } catch (IOException) { /* writer may be replacing file; retry next scan */ }
        catch (Exception e) { Logger.LogWarning("SMA subtitle registry error: " + e.Message); }
    }
    private readonly List<Component> pollTargets = new List<Component>();
    private readonly object boxTargetLock = new object();
    private readonly List<Component> boxTargetNotices = new List<Component>();
    private readonly Dictionary<int, PollState> pollStates = new Dictionary<int, PollState>();
    private Type[] pollTypes;
    private float nextScan, nextPoll, nextReport, nextError;
    private class PollState { public string Key = ""; public float Changed; public bool Reported; public string LastDiagnostic = ""; public string LastBarkProbe = ""; public BoxLine Native; }
    private const string SubtitleTail = "/NPC Subtitle Panel/Panel Subtitle/NPC Subtitle Line";
    private const string NameTail = "/NPC Subtitle Panel/Panel Name/NPC Portrait Name";
    private const string BarkTail = "/Bark/PanelDeBark/PopUp";
    private readonly Dictionary<string, DateTime> recent = new Dictionary<string, DateTime>();
    private string spool;
    private float floatingReady = 0.35f, pollSeconds = 0.15f;
    private int captureDedupMs = 1500;
    private float normalReady, normalFallback, floatingFallback;
#if SMA_IL2CPP
    private BepInEx.Logging.ManualLogSource Logger { get { return Log; } }
    public override void Load() { Awake(); }
    public override bool Unload() { Shutdown(); return true; }
    internal static void DriverTick() { if (instance != null) instance.Tick("il2cpp-driver"); }
    internal static void DriverQuit() { if (instance != null) instance.Shutdown(); }
#endif
    private void Awake()
    {
        instance = this;
        allowedPaths = Config.Bind("BarkFilter", "AllowedControllerPaths", "", "Exact object paths separated by |. Empty means no controller audio.");
        allowedNames = Config.Bind("BarkFilter", "AllowedSpeakerNames", "", "Exact displayed speaker names separated by |. Empty means no UI audio.");
        source = Config.Bind("BarkFilter", "CaptureSource", "Diagnostic", "Diagnostic, Controller, UI, Subtitle, TextUI, TextPoll, Translator, or Hybrid. Diagnostic never exports text.");
        allowedIds = Config.Bind("Filter", "AllowedActorIds", "", "Exact actor IDs separated by comma. Only non-player NPCs on this list can be voiced via Subtitle.");
        uiPaths = Config.Bind("TextFallback", "AllowedTextPaths", "", "Exact dedicated character subtitle object paths separated by |. Never use shared player/menu paths.");
        nativeBox = Config.Bind("NormalBox", "NativeCapture", true, "Capture native non-player NPC dialogue; UI polling is a fallback.");
        nativeUnknownNpc = Config.Bind("NormalBox", "AllowConfirmedNpcWithoutModel", true, "Accept native NPCs with an explicit non-player flag even if their model is not registered yet. Disable to restrict to verified models/allowed IDs.");
        uiFallback = Config.Bind("TextFallback", "EnableTextFallback", false, "Optional text setter hooks for an inspector-verified dedicated subtitle object. Restart after changing.");
        pollEnabled = Config.Bind("TextPoll", "Enabled", true, "Read visible subtitle components independently of text setters.");
        pollNames = Config.Bind("TextPoll", "AllowedSpeakerNames", "Wanjiru Camara", "Verified female speaker names separated by |.");
        pollFemaleBark = Config.Bind("TextPoll", "AllowFemaleBark", false, "Enable only after verifying female avatar popup visibility in diagnostics.");
        pollSecondaryBark = Config.Bind("TextPoll", "AllowSecondaryBark", false, "Optional secondary popup (.Sec); disabled by default to avoid reading auxiliary text.");
        translatorEnabled = Config.Bind("Translator", "Enabled", true, "Optional read-only integration with UnityGameTranslator 0.16.1.");
        // The legacy AssumePortugueseTarget setting is no longer used: readiness is language-neutral.
        translatorWait = Config.Bind("Translator", "FallbackWaitSeconds", 1.5f, "Wait before sending untranslated bark text to the existing Ollama fallback.");
        subtitleReadyWait = Config.Bind("Translator", "SubtitleReadyWaitSeconds", 0.15f, "Normal NPC subtitle stabilization after translation; does not affect floating barks.");
        subtitleFallbackWait = Config.Bind("Translator", "SubtitleFallbackWaitSeconds", 0.50f, "Normal NPC subtitle wait before Ollama fallback; does not affect floating barks.");
        normalReady = subtitleReadyWait.Value; normalFallback = subtitleFallbackWait.Value; floatingFallback = translatorWait.Value;
        string central = Path.Combine(Path.Combine(Paths.PluginPath, "SMAVoiceCapture"), "CONFIGURACOES.txt");
        if (File.Exists(central)) {
            try {
                var settings = new PortableVoice.VoiceSettings(central);
                inspectorEnabled = settings.Bool("ENABLE_INSPECTOR", true);
#if SMA_IL2CPP
                enableCmaBark = settings.Bool("ENABLE_CMA_BARK", true);
                enableCmaFixedBox = settings.Bool("ENABLE_CMA_FIXED_BOX", true);
#else
                enableMonoBarkRecovery = settings.Bool("ENABLE_MONO_BARK_RECOVERY", true);
#endif
                if (settings.Bool("ENABLE_LOG", true)) {
                    try { sessionReport = new PortableVoice.SessionReport(); BepInEx.Logging.Logger.Listeners.Add(sessionReport); }
                    catch (Exception e) { Logger.LogWarning("SMA session report unavailable: " + e.Message); }
                }
                float nr = settings.Int("DELAY_CAIXA_NORMAL_MS",150,0,5000)/1000f;
                float nf = settings.Int("FALLBACK_CAIXA_NORMAL_MS",500,0,10000)/1000f;
                float fr = settings.Int("DELAY_BALAO_FLUTUANTE_MS",350,0,5000)/1000f;
                float ff = settings.Int("FALLBACK_BALAO_FLUTUANTE_MS",1500,0,10000)/1000f;
                float ps = settings.Int("INTERVALO_CAPTURA_MS",150,50,1000)/1000f;
                int dd = settings.Int("DEDUP_CAPTURA_MS",1500,0,10000);
                normalReady=nr; normalFallback=nf; floatingReady=fr; floatingFallback=ff; pollSeconds=ps; captureDedupMs=dd;
                Logger.LogInfo("SMA central settings loaded: " + central);
            } catch (Exception e) { Logger.LogError("SMA invalid central settings; using original cfg: " + e.Message); }
        }
        spool = Path.Combine(Paths.BepInExRootPath, "SMA-Voice-Queue");
        Directory.CreateDirectory(spool);
        // Old source snapshots must not authorize speakers in a new game session.
        try { File.Delete(Path.Combine(spool, "subtitle-model-names.txt")); }
        catch (Exception e) { Logger.LogWarning("SMA subtitle registry reset: " + e.Message); }
        try { File.WriteAllLines(Path.Combine(spool, "identity-sources.txt"), new string[] { Application.persistentDataPath, Path.GetDirectoryName(Application.dataPath) }, new UTF8Encoding(false)); Logger.LogInfo("SMA identity sources: " + Application.persistentDataPath); } catch (Exception e) { Logger.LogWarning("SMA identity sources unavailable: " + e.Message); }
        harmony = new Harmony("local.sma.voicecapture");
        int n = 0;
        int controllerInstalled = Install("Assets._ReusableScripts.CuchiCuchi.Dependentes.Controllers.Discursos.ControlladorDeBarkDePersonalidad", "Bark", 7, "AfterController");
        n += controllerInstalled;
#if !SMA_IL2CPP
        controllerHooks = controllerInstalled;
#endif
        n += Install("Assets._ReusableScripts.CuchiCuchi.Dependentes.DialogueSystem.UnityUIBarkUITValle", "Bark", 2, "AfterUI");
        n += TryHook("Assembly-D_C_Dependientes_ReSc.DialogueSys", "Assets._ReusableScripts.CuchiCuchi.Dependentes.DialogueSystem.DialogueSystemCurrentLine", "OnConversationLine", 1);
        n += TryHook("DialogSys", "PixelCrushers.DialogueSystem.DialogueSystemEvents", "OnConversationLine", 1);
        n += TryHook("DialogSys", "PixelCrushers.DialogueSystem.UnityUIDialogueUI", "ShowSubtitle", 1);
        n += TryHook("DialogSys", "PixelCrushers.DialogueSystem.UnityUISubtitleControls", "ShowSubtitle", 1);
        n += TryHook("DialogueSystem", "PixelCrushers.DialogueSystem.AbstractDialogueUI", "ShowSubtitle", 1);
        n += TryHook("DialogueSystem", "PixelCrushers.DialogueSystem.ConversationView", "NotifyParticipantsOnConversationLine", 1);
        n += TryHook("DialogueSystem", "PixelCrushers.DialogueSystem.ConversationView", "StartSubtitle", 3);
        n += InstallBoxAlternatives();
        if (uiFallback.Value || nativeBox.Value || BarkRecoveryEnabled()) {
            n += TryTextHook("Unity.TextMeshPro", "TMPro.TMP_Text");
            n += TryTextHook("UnityEngine.UI", "UnityEngine.UI.Text");
        }
        Logger.LogInfo("SMA voice hook summary: " + n + " installed; source=" + source.Value + "; TextFallback=" + uiFallback.Value + "; nativeBox=" + nativeBox.Value);
        if (source.Value.Equals("Diagnostic", StringComparison.OrdinalIgnoreCase)) Logger.LogInfo("SMA diagnostic mode: no text exported.");
        pollTypes = new Type[] { FindGameType("TMPro.TMP_Text", "Unity.TextMeshPro"), FindGameType("UnityEngine.UI.Text", "UnityEngine.UI") };
        TryTranslatorHooks();
        #if SMA_IL2CPP
        Logger.LogInfo("SMA CMA bark policy: enabled=" + enableCmaBark + "; verified avatar identity required; primary popup only unless secondary explicitly enabled");
#else
        Logger.LogInfo("SMA Mono bark policy: recovery=" + BarkRecoveryEnabled() + "; native controller hooks=" + controllerHooks + "; existing visible filter=" + pollFemaleBark.Value);
#endif
        Logger.LogInfo("SMA CAPTURE_CONFIG | box_ready_ms=" + (int)(normalReady*1000) + " | box_fallback_ms=" + (int)(normalFallback*1000) + " | bark_ready_ms=" + (int)(floatingReady*1000) + " | bark_fallback_ms=" + (int)(floatingFallback*1000) + " | poll_ms=" + (int)(pollSeconds*1000));
        Logger.LogInfo("SMA poll enabled=" + pollEnabled.Value + "; types=" + (pollTypes[0] != null) + "/" + (pollTypes[1] != null));
        Logger.LogInfo("SMA queue path: " + spool);
#if SMA_IL2CPP
        // BepInEx registers the injected component and attaches it to its persistent manager.
        driver = AddComponent<SMAVoiceTickDriver>();
        Logger.LogInfo("SMA IL2CPP persistent driver registered");
#else
        try {
            GameObject host = new GameObject("SMA Voice Persistent Driver");
            UnityEngine.Object.DontDestroyOnLoad(host);
            host.hideFlags = HideFlags.HideAndDontSave;
            driver = host.AddComponent<SMAVoiceTickDriver>();
            driver.Owner = this;
            host.SetActive(true);
            Logger.LogInfo("SMA driver created: " + host.activeInHierarchy + " enabled=" + driver.enabled);
        } catch (Exception e) { Logger.LogWarning("SMA driver create error: " + e); }
        Application.onBeforeRender += BeforeRenderTick;
        Application.quitting += Shutdown;
        Logger.LogInfo("SMA driver render fallback registered");
#endif
    }
    private void TryTranslatorHooks()
    {
        if (!translatorEnabled.Value || translatorInstalled) return;
        translatorScanner = FindGameType("UnityGameTranslator.Core.TranslatorScanner", "UnityGameTranslator");
        translatorCore = FindGameType("UnityGameTranslator.Core.TranslatorCore", "UnityGameTranslator");
        if (translatorScanner == null) return;
        translatorInstalled = true;
        const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
        getOriginal = translatorScanner.GetMethod("GetOriginalText", flags, null, new Type[] { typeof(object) }, null);
        if (translatorCore != null) getTranslation = translatorCore.GetMethod("GetTranslationValue", flags, null, new Type[] { typeof(string) }, null);
        int count = 0;
        foreach (MethodInfo m in translatorScanner.GetMethods(flags)) {
            ParameterInfo[] a = m.GetParameters();
            string callback = null;
            if ((m.Name == "ApplyTranslationToComponents" || m.Name == "OnTranslationComplete") && a.Length == 3 && a[0].ParameterType == typeof(string) && a[1].ParameterType == typeof(string) && typeof(System.Collections.IEnumerable).IsAssignableFrom(a[2].ParameterType)) callback = "AfterTranslationBatch";
            if (m.Name == "RegisterRenderWatch" && a.Length == 3 && a[0].ParameterType == typeof(object) && a[1].ParameterType == typeof(string) && a[2].ParameterType == typeof(string)) callback = "AfterRenderWatch";
            if (callback == null) continue;
            try {
                harmony.Patch(m, postfix: new HarmonyMethod(typeof(SMAVoiceCapture).GetMethod(callback, BindingFlags.Public | BindingFlags.Static)));
                count++; Logger.LogInfo("SMA translator hook installed: " + m.Name);
            } catch (Exception e) { Logger.LogWarning("SMA translator hook failed: " + m.Name + " | " + e.Message); }
        }
        Logger.LogInfo("SMA translator bridge: hooks=" + count + " originalLookup=" + (getOriginal != null) + " cacheLookup=" + (getTranslation != null));
    }
    public static void AfterTranslationBatch(string __0, string __1, object __2)
    {
        if (object.ReferenceEquals(instance, null) || __2 == null) return;
        try {
            System.Collections.IEnumerable items = __2 as System.Collections.IEnumerable;
            if (items == null) return;
            foreach (object item in items) instance.EnqueueTranslation(item, __0, __1);
        } catch (Exception) { /* callbacks never interfere with translator */ }
    }
    public static void AfterRenderWatch(object __0, string __1, string __2)
    {
        if (!object.ReferenceEquals(instance, null)) instance.EnqueueTranslation(__0, __1, __2);
    }
    private void EnqueueTranslation(object component, string original, string translation)
    {
        System.Threading.Interlocked.Increment(ref translatorCallbackCount);
        if (component == null || String.IsNullOrWhiteSpace(translation)) return;
        lock (translatorLock) {
            if (translatorNotices.Count >= 4096) translatorNotices.RemoveRange(0, 2048);
            translatorNotices.Add(new TranslationNotice { Component = component, Original = original, Translation = translation, Received = DateTime.UtcNow, Changed = DateTime.UtcNow });
        }
    }
    private void AddPollTarget(Component c) {
        if (c == null) return;
        int id = c.GetInstanceID();
        foreach (Component existing in pollTargets)
            if (existing != null && existing.GetInstanceID() == id) return;
        pollTargets.Add(c);
    }
    private void DrainTranslatorNotices()
    {
        TranslationNotice[] batch;
        lock (translatorLock) { batch = translatorNotices.ToArray(); translatorNotices.Clear(); }
        foreach (TranslationNotice item in batch) {
            Component c = AsComponent(item.Component);
            if (c == null) {
#if SMA_IL2CPP
                RememberFixedNotice(item);
#endif
                continue;
            }
            string path = ObjectPath(c);
            if (!IsSubtitle(path) && !IsSpeakerName(path) && !FemaleBarkPath(path)) continue;
            int id = c.GetInstanceID();
            TranslationNotice prev;
            if (!translatorLatest.TryGetValue(id, out prev) || prev.Original != item.Original || prev.Translation != item.Translation) {
                translatorLatest[id] = item;
                Logger.LogInfo("SMA translator candidate: path=" + path + " length=" + item.Translation.Length);
            }
            else { prev.Received = item.Received; }
            if (IsSubtitle(path)) {
                // A translation notification is authoritative for this exact source,
                // even if the portrait or typewriter is still showing a previous line.
                string original=CleanPoll(item.Original), translated=CleanPoll(item.Translation);
                foreach (BoxLine line in boxLines) {
                    if (line.Failed || line.Ready || (line.Sent && String.IsNullOrEmpty(line.EventPath))) continue;
                    if (SameBoxText(original,line.Original) && translated.Length > 0 && !SameBoxText(original,translated)) {
                        line.Spoken=translated; line.Ready=true;
                    }
                }
            }
            AddPollTarget(c);
        }
        if (translatorLatest.Count > 256) {
            List<int> dead = new List<int>();
            foreach (KeyValuePair<int, TranslationNotice> kv in translatorLatest) if ((AsComponent(kv.Value.Component)) == null) dead.Add(kv.Key);
            foreach (int id in dead) translatorLatest.Remove(id);
            if (translatorLatest.Count > 1024) translatorLatest.Clear();
        }
    }
    private bool TranslatorText(Component c, string visible, out string original)
    {
        original = "";
        if (!translatorEnabled.Value) return false;
        TranslationNotice item;
        if (translatorLatest.TryGetValue(c.GetInstanceID(), out item) && SameComponent(item.Component, c)) {
            string before = CleanPoll(item.Original), after = CleanPoll(item.Translation);
            if (visible == before || visible == after) {
                original = before;
                if (visible == after && before != after && before.Length > 0) return true;
            }
        }
        try {
            if (getOriginal != null) {
                string raw = Convert.ToString(getOriginal.Invoke(null, new object[] { c }));
                string before = CleanPoll(raw);
                if (before.Length > 0 && (original.Length == 0 || visible == before)) original = before;
                if (getTranslation != null && before.Length > 0 && before != visible) {
                    string translated = CleanPoll(Convert.ToString(getTranslation.Invoke(null, new object[] { raw })));
                    if (translated.Length > 0 && translated == visible) return true;
                }
            }
        } catch (Exception) { /* optional readback; regular polling remains available */ }
        return false;
    }
    // Only the normal NPC subtitle may reuse a translation before it is rendered.
    // Require the current visible source to match the exact original, not a stale component entry.
    private bool TrySubtitleTranslation(Component c, string visible, out string translated)
    {
        translated = "";
        if (!translatorEnabled.Value || String.IsNullOrWhiteSpace(visible)) return false;
        TranslationNotice item;
        if (translatorLatest.TryGetValue(c.GetInstanceID(), out item) && SameComponent(item.Component, c)
            && CleanPoll(item.Original) == visible) {
            string candidate = CleanPoll(item.Translation);
            if (candidate.Length > 0 && candidate != visible) { translated = candidate; return true; }
        }
        try {
            // The original returned for a component can belong to its previous line. Never
            // use it unless it matches the complete text currently shown in this subtitle.
            if (getTranslation != null && getOriginal != null) {
                string raw = Convert.ToString(getOriginal.Invoke(null, new object[] { c }));
                if (CleanPoll(raw) == visible) {
                    string candidate = CleanPoll(Convert.ToString(getTranslation.Invoke(null, new object[] { raw })));
                    if (candidate.Length > 0 && candidate != visible) { translated = candidate; return true; }
                }
            }
        } catch (Exception) { /* original polling / fallback remains available */ }
        return false;
    }
    private static bool Ends(string path, string suffix) { return path.EndsWith(suffix, StringComparison.OrdinalIgnoreCase); }
    private static bool HasSegment(string path, string segment)
    {
        foreach (string part in path.Split('/')) {
            string candidate = part.Trim();
            if (candidate.EndsWith("(Clone)", StringComparison.OrdinalIgnoreCase)) candidate = candidate.Substring(0, candidate.Length - 7).Trim();
            if (candidate.Equals(segment, StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }
    private static bool IsNpcPanel(string segment) {
        string name = segment.Trim();
        if (name.EndsWith("(Clone)", StringComparison.OrdinalIgnoreCase)) name = name.Substring(0, name.Length-7).Trim();
        return System.Text.RegularExpressions.Regex.IsMatch(name, @"^NPC Subtitle Panel(?:\s+(?:\d+|\(\d+\)))?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    }
    private static bool HasNpcPanel(string path) {
        foreach (string part in path.Split('/')) if (IsNpcPanel(part)) return true;
        return false;
    }
    private static bool IsSubtitle(string path) {
        return HasNpcPanel(path) && (HasSegment(path, "NPC Subtitle Line") || HasSegment(path, "Subtitle Text") || HasSegment(path, "Subtitle Line") || HasSegment(path, "Dialogue Text"));
    }
    private static bool IsSpeakerName(string path) {
        return HasNpcPanel(path) && (HasSegment(path, "NPC Portrait Name") || HasSegment(path, "Portrait Name") || HasSegment(path, "Speaker Name") || HasSegment(path, "NPC Name"));
    }
    private static string PanelKey(Component component)
    {
        for (Transform t = component.transform; t != null; t = t.parent)
            if (IsNpcPanel(t.name)) return t.GetInstanceID().ToString();
        return component.GetInstanceID().ToString();
    }
    private bool FemaleBarkPath(string path)
    {
        if (!Ends(path, BarkTail) && !(pollSecondaryBark.Value && Ends(path, BarkTail + ".Sec"))) return false;
        foreach (string part in path.Split('/')) if (part.StartsWith("Female Avatar Root", StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }
    private static Transform FemaleRoot(Component target)
    {
        if (target == null) return null;
        for (Transform t = target.transform; t != null; t = t.parent)
            if (t.name.StartsWith("Female Avatar Root", StringComparison.OrdinalIgnoreCase)) return t;
        return null;
    }
    private static string ReadString(object obj, string property)
    {
        try { return Convert.ToString(Read(obj, property)) ?? ""; } catch (Exception) { return ""; }
    }
    private CharacterVoiceIdentity ReadIdentity(Component character)
    {
        if (character == null) return null;
        Guid id;
        if (!Guid.TryParse(ReadString(character, "ID_UnicoString"), out id) && !Guid.TryParse(ReadString(character, "ID_Unico"), out id)) id = Guid.Empty;
        if (id == new Guid("00000001-0000-0000-0000-000000000000")) return null;
        string name = ReadString(character, "nombre"), full = ReadString(character, "nombreCompleto");
        string alias = RuntimeAlias(character, String.IsNullOrWhiteSpace(full) ? name : full);
        return new CharacterVoiceIdentity { Id = id == Guid.Empty ? alias : id.ToString("D"), Name = name, FullName = full, Alias = alias };
    }
    private CharacterVoiceIdentity UniqueIdentity(IEnumerable<Component> components)
    {
        CharacterVoiceIdentity found = null;
        foreach (Component component in components) {
            CharacterVoiceIdentity identity = ReadIdentity(component);
            if (identity == null) continue;
            if (found != null && found.Id != identity.Id) return null;
            if (found == null) found = identity;
        }
        return found;
    }
    private CharacterVoiceIdentity ResolveFemaleRoot(Transform root)
    {
        if (root == null || characterType == null) return null;
        // Prefer the exact female avatar subtree. If the Character controller sits on a parent,
        // accept only a controller directly attached to the nearest ancestor (not a sibling).
        Component[] local = CharacterComponents(root, characterType, true);
        if (local.Length > 0) return UniqueIdentity(local);
        int depth = 0;
        for (Transform t = root.parent; t != null && depth++ < 2; t = t.parent) {
            Component[] components = CharacterComponents(t, characterType, false);
            if (components.Length > 0) return UniqueIdentity(components);
            // Some prefab versions put Character in a sibling of the visible avatar.
            // Search only a container with exactly one female root and one controller.
            int roots = 0;
            foreach (Transform child in t.GetComponentsInChildren<Transform>(true)) {
                if (child.name.StartsWith("Female Avatar Root", StringComparison.OrdinalIgnoreCase)) roots++;
                if (roots > 1) break;
            }
            if (roots != 1) break;
            Component[] siblings = CharacterComponents(t, characterType, true);
            if (siblings.Length == 1) return ReadIdentity(siblings[0]);
            if (siblings.Length > 1) break;
        }
        return null;
    }
    private void RefreshFemaleIdentities()
    {
        femaleRoots.Clear();
        if (characterType == null) characterType = FindGameType("Assets._ReusableScripts.CuchiCuchi.Character", "Assembly-CSharp", GameAssembly, "Assembly-D_C_Dependientes_ReSc");
        if (characterType == null || !typeof(Component).IsAssignableFrom(characterType)) return;
        HashSet<int> processed = new HashSet<int>();
        foreach (Component target in pollTargets) {
            if (target == null || !target.gameObject.scene.IsValid() || !target.gameObject.scene.isLoaded) continue;
            Transform root = FemaleRoot(target);
            if (root == null || !root.gameObject.activeInHierarchy || !processed.Add(root.GetInstanceID())) continue;
            try {
                CharacterVoiceIdentity identity = ResolveFemaleRoot(root);
                if (identity != null) { string alias = RuntimeAlias(root, String.IsNullOrWhiteSpace(identity.FullName) ? identity.Name : identity.FullName); if (identity.Id.StartsWith("live:", StringComparison.Ordinal)) identity.Id = alias; identity.Alias = alias; femaleRoots[root.GetInstanceID()] = identity; }
            } catch (Exception e) { Logger.LogWarning("SMA identity root error: " + e.Message); }
        }
        List<string> resolved = new List<string>();
        foreach (CharacterVoiceIdentity id in femaleRoots.Values) resolved.Add(id.Id + " " + id.FullName + " " + id.Name);
        resolved.Sort();
        string report = "type=" + characterType.FullName + " roots=" + processed.Count + " identified=" + femaleRoots.Count + " | " + String.Join("; ", resolved.ToArray());
        if (report != lastIdentityReport) { lastIdentityReport = report; Logger.LogInfo("SMA identities: " + report); }
    }
    private static bool VerifiedBarkIdentity(CharacterVoiceIdentity identity, string name) {
        Guid id, nameId;
        return identity != null && !PlaceholderName(name) && !Guid.TryParse(name, out nameId)
            && Guid.TryParse(identity.Id, out id) && id != Guid.Empty
            && id != new Guid("00000001-0000-0000-0000-000000000000");
    }
    private CharacterVoiceIdentity IdentityForBark(Component target)
    {
        Transform root = FemaleRoot(target);
        CharacterVoiceIdentity identity;
        return root != null && femaleRoots.TryGetValue(root.GetInstanceID(), out identity) ? identity : null;
    }
    private CharacterVoiceIdentity IdentityForName(string name)
    {
        if (PlaceholderName(name)) return null;
        string normalized = NormalizeName(name);
        CharacterVoiceIdentity found = null;
        foreach (CharacterVoiceIdentity identity in femaleRoots.Values) {
            if (!normalized.Equals(NormalizeName(identity.Name), StringComparison.OrdinalIgnoreCase) &&
                !normalized.Equals(NormalizeName(identity.FullName), StringComparison.OrdinalIgnoreCase)) continue;
            if (found != null && found.Id != identity.Id) return null; // ambiguous names never link IDs
            found = identity;
        }
        return found;
    }
    private static bool Visible(Component comp)
    {
        if (comp == null || !comp.gameObject.activeInHierarchy) return false;
        Behaviour b = comp as Behaviour;
        if (b != null && !b.isActiveAndEnabled) return false;
        object renderer = Read(comp, "canvasRenderer");
        if (renderer != null) {
            if (object.Equals(Read(renderer, "cull"), true)) return false;
            MethodInfo alpha = renderer.GetType().GetMethod("GetInheritedAlpha", Type.EmptyTypes);
            if (alpha != null && Convert.ToSingle(alpha.Invoke(renderer, null)) <= 0.02f) return false;
        }
        object color = Read(comp, "color");
        if (color is Color && ((Color)color).a <= 0.02f) return false;
        return true;
    }
    private static string NormalizeName(string name)
    {
        string value = CleanPoll(name).Normalize(NormalizationForm.FormD);
        StringBuilder result = new StringBuilder();
        foreach (char ch in value) if (System.Globalization.CharUnicodeInfo.GetUnicodeCategory(ch) != System.Globalization.UnicodeCategory.NonSpacingMark) result.Append(ch);
        return System.Text.RegularExpressions.Regex.Replace(result.ToString(), "\\s+", " ").Trim();
    }
    private static bool PlaceholderName(string name)
    {
        string n = NormalizeName(name);
        return n.Length == 0 || n.Equals("(NPC Name)", StringComparison.OrdinalIgnoreCase) || n.Equals("NPC Name", StringComparison.OrdinalIgnoreCase) || n.Equals("(Nome do NPC)", StringComparison.OrdinalIgnoreCase) || n.Equals("Nome do NPC", StringComparison.OrdinalIgnoreCase);
    }
    private bool NameAllowed(string name)
    {
        if (PlaceholderName(name)) return false;
        foreach (string allowed in pollNames.Value.Split('|')) if (!PlaceholderName(allowed) && NormalizeName(allowed).Equals(NormalizeName(name), StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }
    private string ResolveSpeakerName(Component c, out string method)
    {
        method = "none";
        if (c == null) return "";
        // The portrait label can be culled or disabled while its associated subtitle is still visible.
        // Require the shared subtitle panel to be active and use the current label, not an arbitrary NPC.
        Transform t = c.transform;
        while (t != null && !IsNpcPanel(t.name)) t = t.parent;
        if (t == null || !t.gameObject.activeInHierarchy) return "";
        c = ConcreteText(c);
        string raw = CleanPoll(Convert.ToString(Read(c, "text")));
        if (!PlaceholderName(raw)) { method = "label"; return raw; }
        // The translator can replace the placeholder only at rendering time. Only accept a recent
        // notice for this exact component and its current placeholder, never a global name cache.
        TranslationNotice notice;
        if (translatorLatest.TryGetValue(c.GetInstanceID(), out notice) && SameComponent(notice.Component, c)
            && (DateTime.UtcNow - notice.Received).TotalSeconds <= 3.0
            && CleanPoll(notice.Original) == raw && !PlaceholderName(notice.Translation)) {
            method = "fresh-render"; return CleanPoll(notice.Translation);
        }
        return "";
    }
    private static string CleanPoll(string value)
    {
        return System.Text.RegularExpressions.Regex.Replace(value ?? "", "<[^>]+>", "").Trim();
    }
    private void Update() { Tick("plugin-update"); }
    private void BeforeRenderTick() { Tick("before-render"); }
    internal void DriverDestroyed() { if (!quitting) Logger.LogWarning("SMA driver destroyed before quit; render fallback remains registered"); }
    internal void Tick(string route)
    {
        if (quitting || lastTickFrame == Time.frameCount) return;
        lastTickFrame = Time.frameCount;
        float heartbeatNow = Time.realtimeSinceStartup;
        if (heartbeatNow >= nextHeartbeat) {
            nextHeartbeat = heartbeatNow + 5f;
            tickRoute = route;
            Logger.LogInfo("SMA heartbeat: route=" + tickRoute + " poll=" + pollEnabled.Value + " source=" + source.Value + " translatorCallbacks=" + translatorCallbackCount + " textCallbacks=" + textCallbackCount + " subtitleCallbacks=" + subtitleCallbackCount + " nativeAccepted=" + nativeAccepted + " nativeSent=" + nativeSent + " boxUiSent=" + boxUiSent + " barkSent=" + barkSent + " barkBlocked=" + barkBlocked + " queue=" + spool);
        }
        float now = Time.realtimeSinceStartup;
        CheckBoxScene();
        if (inspectorEnabled && now >= nextInspector) { nextInspector = now + 1f; InspectRequested(); }
        if (nativeBox.Value && nativeHookRetries < 3 && now >= nextNativeHookRetry) {
            nativeHookRetries++; nextNativeHookRetry = now + 5f;
            TryHook("DialogSys", "PixelCrushers.DialogueSystem.UnityUIDialogueUI", "ShowSubtitle", 1);
            TryHook("DialogSys", "PixelCrushers.DialogueSystem.UnityUISubtitleControls", "ShowSubtitle", 1);
            TryHook("DialogueSystem", "PixelCrushers.DialogueSystem.ConversationView", "NotifyParticipantsOnConversationLine", 1);
            TryHook(GameAssembly, "Assets._ReusableScripts.CuchiCuchi.Dependentes.DialogueSystem.DialogueSystemCurrentLine", "OnConversationLine", 1);
            InstallBoxAlternatives();
        }
        if (!pollEnabled.Value) { DrainNativeBox(now); return; }
        if (now < nextPoll) return;
        nextPoll = now + pollSeconds;
        try {
            if (now >= nextTranslatorTry) { nextTranslatorTry = now + 3f; TryTranslatorHooks(); }
            if (now >= nextScan) {
                nextScan = now + 0.75f;
                pollTargets.Clear();
                HashSet<int> ids = new HashSet<int>();
                int count = 0;
                foreach (Type type in pollTypes) {
                    if (type == null) continue;
                    foreach (Component comp in FindTextComponents(type)) {
                        if (comp == null || !comp.gameObject.scene.IsValid() || !comp.gameObject.scene.isLoaded || !ids.Add(comp.GetInstanceID())) continue;
                        count++;
                        string path = ObjectPath(comp);
                        if (IsSubtitle(path) || IsSpeakerName(path) || FemaleBarkPath(path) || Matches(uiPaths.Value, path)) pollTargets.Add(comp);
                        else if (comp.gameObject.activeInHierarchy && boxDiscoveryPaths.Count < 48 &&
                            System.Text.RegularExpressions.Regex.IsMatch(path, @"subtitle|dialogue|conversation", System.Text.RegularExpressions.RegexOptions.IgnoreCase) && boxDiscoveryPaths.Add(path))
                            Logger.LogInfo("SMA BOX_DISCOVERY | unmatched active UI | path=" + path + " | type=" + comp.GetType().FullName);
                    }
                }
                if (now >= nextReport) {
                    nextReport = now + 5f;
                    Logger.LogInfo("SMA poll scan: components=" + count + " candidates=" + pollTargets.Count);
                    foreach (Component target in pollTargets) if (target != null) Logger.LogInfo("SMA poll target: " + ObjectPath(target) + " | " + target.GetType().FullName + " active=" + target.gameObject.activeInHierarchy);
                }
                RefreshRegistryNames();
                RefreshFemaleIdentities();
                List<int> expired = new List<int>();
                foreach (int id in pollStates.Keys) if (!ids.Contains(id)) expired.Add(id);
                foreach (int id in expired) pollStates.Remove(id);
                lock (barkWrites) {
                    List<int> stale = new List<int>();
                    foreach (int id in barkWrites.Keys) if (!ids.Contains(id)) stale.Add(id);
                    foreach (int id in stale) barkWrites.Remove(id);
                }
                lock (boxWrites) {
                    List<int> stale = new List<int>();
                    foreach (int id in boxWrites.Keys) if (!ids.Contains(id)) stale.Add(id);
                    foreach (int id in stale) boxWrites.Remove(id);
                }
            }
            lock (boxTargetLock) {
                foreach (Component c in boxTargetNotices) AddPollTarget(c);
                boxTargetNotices.Clear();
            }
            DrainTranslatorNotices();
#if SMA_IL2CPP
            PollFixedToolkitBox(now);
#endif
            foreach (TranslationNotice notice in translatorLatest.Values) {
                Component candidate = AsComponent(notice.Component);
                AddPollTarget(candidate);
            }
            Dictionary<string, string> names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            Dictionary<string, string> nameMethods = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (Component target in pollTargets) {
                if (target == null) continue;
                string path = ObjectPath(target);
                if (!IsSpeakerName(path)) continue;
                try {
                    string method;
                    string found = ResolveSpeakerName(target, out method);
                    string panel = PanelKey(target);
                    string existing;
                    if (!PlaceholderName(found)) {
                        if (!names.TryGetValue(panel, out existing)) { names[panel] = found; nameMethods[panel] = method; }
                        else if (!NormalizeName(existing).Equals(NormalizeName(found), StringComparison.OrdinalIgnoreCase)) { names[panel] = ""; nameMethods[panel] = "ambiguous"; }
                    }
                } catch (Exception e) { if (now >= nextError) { nextError = now + 5f; Logger.LogWarning("SMA name read error: " + e.Message); } }
            }
            HashSet<int> visitedTextIds = new HashSet<int>();
            foreach (Component target in pollTargets) {
                if (target == null) continue;
                // Unity instance IDs identify the same component on either backend.
                if (!visitedTextIds.Add(target.GetInstanceID())) continue;
                string path = ObjectPath(target);
                bool subtitle = IsSubtitle(path), bark = FemaleBarkPath(path);
                if (!subtitle && !bark) continue;
                try {
                int id = target.GetInstanceID();
                PollState state;
                if (!pollStates.TryGetValue(id, out state)) { state = new PollState(); pollStates[id] = state; }
                Component concrete = ConcreteText(target);
                bool visible = Visible(concrete);
                string current = CleanPoll(Convert.ToString(Read(concrete, "text")));
                string text = visible ? current : "";
                string evidenceRoute = "none";
                bool barkEvidence = false;
                if (bark && BarkRecoveryEnabled()) {
                    barkEvidence = FreshBarkEvidence(concrete, current, out evidenceRoute);
                    // Avatar popups can remain active while canvas alpha/cull changes.
                    // Only a matching recent setter/translation may substitute for that visual gate.
                    if (!visible && barkEvidence) text = current;
                    string probe = "active=" + target.gameObject.activeInHierarchy + " visible=" + visible +
                        " text=" + (current.Length > 0 ? "present" : "empty") + " evidence=" + evidenceRoute;
                    if (state.LastBarkProbe != probe) {
                        state.LastBarkProbe = probe; barkObserved++;
                        Logger.LogInfo("SMA BARK_OBSERVE | " + probe + " | chars=" + current.Length + " | path=" + path);
                    }
                    // Do not re-arm a delivered line just because the renderer faded.
                    if (!visible && !barkEvidence && current.Length > 0 && target.gameObject.activeInHierarchy) continue;
                }
                bool boxEvidence = false;
                if (subtitle && NativeBoxEnabled()) {
                    boxEvidence = FreshBoxEvidence(concrete, current, out evidenceRoute);
                    if (!visible && boxEvidence) text = current;
                }
                bool boxObservable = visible || boxEvidence;
                string name = "";
                if (subtitle) names.TryGetValue(PanelKey(target), out name);
                name = name ?? "";
                CharacterVoiceIdentity identity = subtitle ? IdentityForName(name) : IdentityForBark(target);
                if (bark && identity != null) name = String.IsNullOrWhiteSpace(identity.FullName) ? identity.Name : identity.FullName;
                bool registered = subtitle && !PlaceholderName(name) && registryNames.Contains(NormalizeName(name));
                bool authorizedName = NameAllowed(name) || (subtitle && identity != null) || registered;
                if (subtitle) {
                    string method;
                    nameMethods.TryGetValue(PanelKey(target), out method);
                    string diagnostic = "active=" + target.gameObject.activeInHierarchy + " visible=" + visible + " speaker=" + (name.Length > 0 ? name : "(unresolved)") + " nameSource=" + (method ?? "none") + " authorized=" + authorizedName + " registry=" + registered + " id=" + (identity == null ? "unresolved" : identity.Id) + " length=" + current.Length + " evidence=" + evidenceRoute;
                    if (state.LastDiagnostic != diagnostic) { state.LastDiagnostic = diagnostic; Logger.LogInfo("SMA subtitle check: " + diagnostic + " path=" + path); }
                }
                string original;
                bool ready = TranslatorText(target, text, out original);
                string canonical = ready && original.Length > 0 ? original : text;
                string spokenText = text;
                bool earlyTranslation = false;
                // Preserve the visible source as the key when the translation arrives.
                // This prevents restarting the stabilization timer or exporting twice.
                if (subtitle && boxObservable && !ready) {
                    string translated;
                    if (TrySubtitleTranslation(target, text, out translated)) {
                        spokenText = translated; ready = true; earlyTranslation = true;
                    }
                }
                // Native path wins. A visual translation enriches the same logical line;
                // a delayed portrait or animation cannot cause a second event.
                if (subtitle && boxObservable && NativeBoxEnabled()) {
                    BoxLine native = FindBoxLine(name, canonical, spokenText, now, true);
                    if (native == null && BoxDisplayMatches(state.Native,name,canonical,spokenText)) native = state.Native;
                    if (native == null && boxLines.Count > 0) {
                        BoxLine latest = boxLines[boxLines.Count-1];
                        if (!latest.Sent && BoxDisplayMatches(latest,name,canonical,spokenText)) native=latest;
                    }
                    if (native != null) {
                        // Never replace a full native line with a translated typewriter fragment.
                        if (ready && (!native.Sent || !String.IsNullOrEmpty(native.EventPath)) && (SameBoxText(canonical,native.Original) || SameBoxText(canonical,native.Spoken))) { native.Spoken = spokenText; native.Ready = true; }
                        state.Native=native;
                        state.Key = name + "\n" + canonical; state.Changed = now; state.Reported = true;
                        continue;
                    }
                    if (state.Native != null) { state.Native=null; state.Reported=false; }
                }
                if (subtitle && !boxObservable) {
                    state.Native=null;
                    // Preserve dedup when a delivered subtitle is temporarily culled.
                    if (target.gameObject.activeInHierarchy && current.Length > 0) continue;
                }
                string key = text.Length == 0 ? "" : name + "\n" + canonical;
                if (key != state.Key) { state.Key = key; state.Changed = now; state.Reported = false; }
                float stableWait = subtitle ? Math.Max(pollSeconds, normalReady) : floatingReady;
                float fallbackWait = subtitle ? normalFallback : floatingFallback;
                float wait = ready ? stableWait : (translatorEnabled.Value ? Math.Max(stableWait, fallbackWait) : stableWait);
                if (key.Length == 0 || state.Reported || now - state.Changed < wait) continue;
                bool authorized = subtitle ? authorizedName : pollFemaleBark.Value;
#if SMA_IL2CPP
                // CMA's controller hook is unavailable. Only permit the already verified
                // avatar popup, never arbitrary UI or a player identity.
                if (bark) authorized = enableCmaBark && VerifiedBarkIdentity(identity, name);
#else
                // Native Mono route stays primary. Hidden UI or missing controller may
                // use fresh evidence only with a verified avatar identity.
                if (bark && BarkRecoveryEnabled() && (!visible || !pollFemaleBark.Value))
                    authorized = VerifiedBarkIdentity(identity, name) && (visible || barkEvidence);
#endif
                if (!authorized && subtitle) continue; // retry when identity becomes available
                if (bark && !authorized) {
                    string reason = !BarkRecoveryEnabled() ? "disabled-or-native-policy" : "identity-unverified";
                    string diagnostic = "bark-blocked|" + reason + "|" + key;
                    if (state.LastDiagnostic != diagnostic) { state.LastDiagnostic = diagnostic; barkBlocked++; Logger.LogInfo("SMA BARK_DROP | reason=" + reason + " | chars=" + text.Length + " | path=" + path); }
                    if (!BarkRecoveryEnabled()) state.Reported = true;
                    continue; // an identity can resolve after the text becomes visible
                }
                // Translator-only mode must keep waiting when no translation is ready.
                // Diagnostic never exports; keep its original one-shot logging behavior.
                if (subtitle && source.Value.Equals("Translator", StringComparison.OrdinalIgnoreCase) && !ready) continue;
                if (!subtitle || source.Value.Equals("Diagnostic", StringComparison.OrdinalIgnoreCase)) state.Reported = true;
                Logger.LogInfo("SMA poll line: kind=" + (subtitle ? "subtitle" : "bark") + " speaker=" + name + " authorized=" + authorized + " length=" + text.Length + " path=" + path);
                if (subtitle) Logger.LogInfo("SMA caixa latency: capture_ms=" + ((int)((now-state.Changed)*1000f)) + " translation=" + (earlyTranslation ? "early-cache" : ready ? "rendered" : "fallback") + " chars=" + spokenText.Length);
                if (authorized && (Enabled("TextPoll") || (ready && Enabled("Translator")))) {
                    if (ready) Logger.LogInfo("SMA translator reused: path=" + path);
                    Transform root = bark ? FemaleRoot(target) : null;
                    string alias = identity != null ? identity.Alias : (root != null ? RuntimeAlias(root, name) : "");
                    string actor = identity != null ? identity.Id : (subtitle ? name : (alias.Length > 0 ? alias : path));
                    if (subtitle) {
                        // Reported only after atomic write or an explicitly recognized duplicate.
                        BoxLine uiLine = NativeBoxEnabled() ? NewUiBox(actor, name, alias, canonical, spokenText, ready, now) : null;
                        if (Export(ready ? "Translator" : "TextPoll", actor, name, spokenText, ready, alias, true, uiLine)) {
                            boxUiSent++;
                            Logger.LogInfo("SMA BOX_UI_QUEUED | evidence=" + evidenceRoute + " | chars=" + spokenText.Length + " | path=" + path);
                            if (uiLine != null) boxLines.Add(uiLine);
                            state.Reported = true;
                        } else state.Reported = true; // duplicate, already queued
                    } else {
                        if (Export(ready ? "Translator" : "TextPoll", actor, name, spokenText, ready, alias, false)) {
                            barkSent++;
                            if (!visible && barkEvidence) barkEvidenceUsed++;
                            Logger.LogInfo("SMA BARK_QUEUED | evidence=" + evidenceRoute + " | visible=" + visible + " | ready=" + ready + " | chars=" + spokenText.Length + " | capture_ms=" + (int)((now-state.Changed)*1000f) + " | path=" + path);
                        }
                    }
                    Logger.LogInfo("SMA identity event: " + (identity == null ? "unresolved; preserving fallback" : identity.Id) + " | " + name);
                }
                } catch (Exception e) {
                    if (now >= nextError) { nextError = now + 5f; Logger.LogWarning("SMA poll error: path=" + path + " | " + e); }
                }
            }
        } catch (Exception e) {
            if (now >= nextError) { nextError = now + 5f; Logger.LogWarning("SMA poll error: " + e); }
        } finally { DrainNativeBox(now); }
    }
    private int Install(string typeName, string methodName, int count, string callbackName)
    {
        try {
            Type type = FindGameType(typeName, GameAssembly);
            if (type == null) throw new TypeLoadException(typeName);
            int n = 0;
            foreach (MethodInfo method in type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)) {
                if (method.Name != methodName || method.ReturnType != typeof(bool) || method.IsAbstract) continue;
                ParameterInfo[] p = method.GetParameters();
                if (p.Length != count || p[0].ParameterType != typeof(string)) continue;
                if (count == 7 && (p[1].ParameterType != typeof(bool) || p[2].ParameterType != typeof(string))) continue;
                if (count == 2 && p[1].ParameterType != typeof(string)) continue;
                harmony.Patch(method, postfix: new HarmonyMethod(typeof(SMAVoiceCapture).GetMethod(callbackName, BindingFlags.Static | BindingFlags.Public)));
                n++; Logger.LogInfo("SMA bark hook installed: " + typeName + "." + methodName);
            }
            if (n == 0) Logger.LogWarning("SMA bark hook unavailable: " + typeName);
            return n;
        } catch (Exception e) { Logger.LogWarning("SMA bark hook error: " + e); return 0; }
    }
    // Additional Dialogue System variants. Only exact types and Subtitle-first methods;
    // never hook arbitrary text/menu methods or infer NPC identity from the active avatar.
    private int InstallBoxAlternatives() {
        if (!nativeBox.Value) return 0;
        int total = 0;
        total += TryHook(GameAssembly, "Assets._ReusableScripts.CuchiCuchi.Dependentes.DialogueSystem.DialogueSystemCurrentLine", "OnConversationLine", -1);
        string[] types = { "DialogueSystemController", "StandardDialogueUI", "StandardUISubtitlePanel", "StandardUISubtitleControls", "UnityUIDialogueUI", "UnityUISubtitleControls", "AbstractDialogueUI", "ConversationView", "DialogueSystemEvents" };
        foreach (string name in types) {
            Type t = FindGameType("PixelCrushers.DialogueSystem." + name);
            if (t == null) continue;
            foreach (string method in new string[] { "ShowSubtitle", "OnConversationLine", "StartSubtitle", "NotifyParticipantsOnConversationLine" })
                total += TryHook(t.Assembly.GetName().Name, t.FullName, method, -1);
        }
        if (total > 0) Logger.LogInfo("SMA BOX_ALTERNATIVE_HOOKS | installed=" + total);
        return total;
    }
    private int TryHook(string assemblyName, string typeName, string methodName, int count)
    {
        try {
            Type target = null;
            try { target = Assembly.Load(assemblyName).GetType(typeName, false); } catch (Exception) { }
            if (target == null) target = FindGameType(typeName);
            if (target == null) throw new TypeLoadException(typeName);
            MethodInfo callback = typeof(SMAVoiceCapture).GetMethod("AfterSubtitle", BindingFlags.Public | BindingFlags.Static);
            int total = 0; bool matched = false;
            foreach (MethodInfo m in target.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly)) {
                if (m.Name != methodName || m.IsAbstract || m.ContainsGenericParameters) continue;
                ParameterInfo[] parameters = m.GetParameters();
                if (parameters.Length == 0 || (count >= 0 && parameters.Length != count) || parameters[0].ParameterType.FullName != "PixelCrushers.DialogueSystem.Subtitle") continue;
                matched = true;
                if (hookedSubtitleMethods.Contains(m)) continue;
                try {
                    harmony.Patch(m, postfix: new HarmonyMethod(callback));
                    hookedSubtitleMethods.Add(m);
                    total++;
                    Logger.LogInfo("SMA voice hook installed: " + typeName + "." + methodName + " | args=" + parameters.Length);
                } catch (Exception e) { Logger.LogWarning("SMA BOX_HOOK_FAILED | " + typeName + "." + methodName + " | " + e.Message); }
            }
            if (!matched && count >= 0) Logger.LogWarning("SMA voice hook unavailable: " + typeName + "." + methodName);
            return total;
        } catch (Exception e) {
            Logger.LogWarning("SMA voice hook failed: " + typeName + "." + methodName + " | " + e.Message);
            return 0;
        }
    }
    private static Type FindGameType(string name, params string[] assemblies) {
        // Exact type lookup avoids Harmony's expensive GetTypes() sweep over broken IL2CPP wrappers.
        foreach (string assembly in assemblies) {
            try { Type t = Assembly.Load(assembly).GetType(name, false); if (t != null) return t; } catch (Exception) { }
        }
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies()) {
            try { Type t = assembly.GetType(name, false); if (t != null) return t; } catch (Exception) { }
        }
        return null;
    }
    private void InspectRequested() {
        string root = Directory.GetParent(Paths.BepInExRootPath).FullName;
        string request = Path.Combine(root, "SMA_INSPECIONAR.request");
        if (!File.Exists(request)) return;
        try {
            File.Delete(request);
            var result = new StringBuilder("SMA Voice - snapshot de componentes de texto (sem conteudo das falas)\n");
            var ids = new HashSet<int>(); int count = 0, failed = 0;
            foreach (Type type in pollTypes) {
                if (type == null) continue;
                try {
                    foreach (Component c in FindTextComponents(type)) {
                        try {
                            if (c == null || !c.gameObject.scene.IsValid() || !c.gameObject.scene.isLoaded || !ids.Add(c.GetInstanceID())) continue;
                            string text = Convert.ToString(Read(c, "text"));
                            result.Append(ObjectPath(c)).Append(" | ").Append(c.GetType().FullName)
                                .Append(" | id=").Append(c.GetInstanceID()).Append(" | active=").Append(c.gameObject.activeInHierarchy)
                                .Append(" | visible=").Append(Visible(c)).Append(" | chars=").Append(text == null ? 0 : text.Length).AppendLine();
                            count++;
                        } catch (Exception) { failed++; }
                    }
                } catch (Exception) { failed++; }
            }
            // Extra diagnostic routes only: never enqueue text from these scans.
            InspectExtraTextMesh(result);
            InspectToolkit(result);
            result.AppendLine("Total=" + count + " | falhas=" + failed);
            File.WriteAllText(Path.Combine(root,"SMA_INSPECTOR.txt"),result.ToString(),new UTF8Encoding(false));
            Logger.LogInfo("SMA inspector snapshot: components=" + count + " failures=" + failed);
        } catch (Exception e) { Logger.LogWarning("SMA inspector error: " + e.Message); }
    }
    private static object InspectRead(object obj, string member) {
        try { return Read(obj, member); } catch (Exception) { return null; }
    }
    private static string InspectLabel(object value) {
        try { return (Convert.ToString(value) ?? "").Replace("\r", " ").Replace("\n", " ").Replace("|", "/"); }
        catch (Exception) { return "(unavailable)"; }
    }
    private static string InspectFingerprint(string value) {
        // Stable across snapshots, without logging dialogue contents.
        unchecked { uint h = 2166136261u; foreach (char c in value) { h ^= c; h *= 16777619u; } return h.ToString("x8"); }
    }
    private static object InspectCast(object obj, Type type) {
        if (obj == null || type == null) return null;
        if (type.IsInstanceOfType(obj)) return obj;
#if SMA_IL2CPP
        Il2CppObjectBase native = obj as Il2CppObjectBase;
        if (native != null) return nativeCast.MakeGenericMethod(type).Invoke(native, null);
#endif
        return null;
    }
    private static object InspectChild(object node, int index) {
        const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
        // Prefer VisualElement.ElementAt; indexer is a fallback on other versions.
        Type t = node.GetType();
        MethodInfo m = t.GetMethod("ElementAt", flags, null, new Type[] { typeof(int) }, null);
        if (m == null) m = t.GetMethod("get_Item", flags, null, new Type[] { typeof(int) }, null);
        if (m != null) return m.Invoke(node, new object[] { index });
        object hierarchy = InspectRead(node, "hierarchy");
        if (hierarchy == null) return null;
        m = hierarchy.GetType().GetMethod("ElementAt", flags, null, new Type[] { typeof(int) }, null);
        if (m == null) m = hierarchy.GetType().GetMethod("get_Item", flags, null, new Type[] { typeof(int) }, null);
        return m == null ? null : m.Invoke(hierarchy, new object[] { index });
    }
    private static void InspectExtraTextMesh(StringBuilder result) {
        result.AppendLine("=== TEXTMESH CLASSICO ===");
        Type type = FindGameType("UnityEngine.TextMesh", "UnityEngine.TextRenderingModule", "UnityEngine");
        int count = 0, failed = 0;
        if (type != null) try {
            foreach (Component c in FindTextComponents(type)) {
                try {
                    if (c == null || !c.gameObject.scene.IsValid() || !c.gameObject.scene.isLoaded) continue;
                    string value = Convert.ToString(Read(c, "text")) ?? "";
                    result.Append(ObjectPath(c)).Append(" | TextMesh | active=").Append(c.gameObject.activeInHierarchy)
                        .Append(" | chars=").Append(value.Length).Append(" | hash=").Append(InspectFingerprint(value)).AppendLine(); count++;
                } catch (Exception) { failed++; }
            }
        } catch (Exception e) { failed++; result.AppendLine("TEXTMESH_ERROR | " + InspectLabel(e.GetBaseException().Message)); }
        result.AppendLine("TEXTMESH_TOTAL | available=" + (type != null) + " | count=" + count + " | failures=" + failed);
    }
    private static void InspectToolkit(StringBuilder result) {
        result.AppendLine("=== UI TOOLKIT (somente diagnostico) ===");
        Type document = FindGameType("UnityEngine.UIElements.UIDocument", "UnityEngine.UIElementsModule", "UnityEngine");
        Type visual = FindGameType("UnityEngine.UIElements.VisualElement", "UnityEngine.UIElementsModule", "UnityEngine");
        Type textType = FindGameType("UnityEngine.UIElements.TextElement", "UnityEngine.UIElementsModule", "UnityEngine");
        int docs = 0, nodes = 0, texts = 0, failed = 0;
        if (document == null || visual == null || textType == null) {
            result.AppendLine("UITK_UNAVAILABLE | document=" + (document != null) + " | visual=" + (visual != null) + " | text=" + (textType != null));
            return;
        }
        try {
            foreach (Component c in FindTextComponents(document)) {
                try {
                    if (c == null || !c.gameObject.scene.IsValid() || !c.gameObject.scene.isLoaded) continue;
                    string path = ObjectPath(c); docs++;
                    object root = Read(c, "rootVisualElement");
                    result.Append("UITK_DOC | ").Append(path).Append(" | id=").Append(c.GetInstanceID())
                        .Append(" | active=").Append(c.gameObject.activeInHierarchy).Append(" | root=").Append(root != null).AppendLine();
                    if (root != null) InspectToolkitNode(root, visual, textType, path, 0, 0, result, ref nodes, ref texts, ref failed);
                } catch (Exception e) { failed++; result.AppendLine("UITK_DOC_ERROR | " + InspectLabel(e.GetBaseException().Message)); }
            }
        } catch (Exception e) { failed++; result.AppendLine("UITK_SCAN_ERROR | " + InspectLabel(e.GetBaseException().Message)); }
        result.AppendLine("UITK_TOTAL | docs=" + docs + " | nodes=" + nodes + " | texts=" + texts + " | failures=" + failed + " | capped=" + (nodes >= 10000));
    }
    private static void InspectToolkitNode(object raw, Type visual, Type textType, string parent, int depth, int index, StringBuilder result, ref int nodes, ref int texts, ref int failed) {
        if (raw == null || depth > 64 || nodes >= 10000) return;
        nodes++;
        try {
            object node = InspectCast(raw, visual);
            if (node == null) { failed++; return; }
            string name = InspectLabel(InspectRead(node, "name"));
            string path = parent + "/" + (name.Length == 0 ? "element" : name) + "[" + index + "]";
            // Failure to inspect a text node must not suppress its descendants.
            try {
            object text = InspectCast(node, textType);
            if (text != null) {
                string value = Convert.ToString(Read(text, "text")) ?? "";
                object style = InspectRead(node, "resolvedStyle");
                result.Append("UITK_TEXT | ").Append(path).Append(" | chars=").Append(value.Length)
                    .Append(" | hash=").Append(InspectFingerprint(value)).Append(" | attached=").Append(InspectRead(node,"panel") != null)
                    .Append(" | visibleFlag=").Append(InspectLabel(InspectRead(node,"visible")))
                    .Append(" | display=").Append(InspectLabel(InspectRead(style,"display")))
                    .Append(" | bounds=").Append(InspectLabel(InspectRead(node,"worldBound"))).AppendLine(); texts++;
            }
            } catch (Exception e) {
                failed++; if (failed <= 12) result.AppendLine("UITK_TEXT_ERROR | " + path + " | " + InspectLabel(e.GetBaseException().Message));
            }
            object childCount = InspectRead(node, "childCount");
            if (childCount == null) { failed++; return; }
            int count = Math.Min(10000, Convert.ToInt32(childCount));
            for (int i=0; i<count && nodes<10000; i++) {
                try {
                    object child = InspectChild(node, i);
                    if (child == null) { failed++; continue; }
                    InspectToolkitNode(child, visual, textType, path, depth+1, i, result, ref nodes, ref texts, ref failed);
                } catch (Exception) { failed++; }
            }
        } catch (Exception e) {
            failed++; if (failed <= 12) result.AppendLine("UITK_NODE_ERROR | " + InspectLabel(e.GetBaseException().Message));
        }
    }
    private static Component AsComponent(object value) {
#if SMA_IL2CPP
        Component existing = value as Component;
        if (!object.ReferenceEquals(existing, null)) return existing;
        Il2CppObjectBase native = value as Il2CppObjectBase;
        return native == null ? null : native.TryCast<Component>();
#else
        return value as Component;
#endif
    }
    private Component ConcreteText(Component target) {
#if SMA_IL2CPP
        if (target != null && target.GetType().GetProperty("text", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance) == null && pollTypes != null) {
            foreach (Type type in pollTypes) {
                if (type == null) continue;
                try { Component cast = TypedComponent(target, type); if (cast != null) return cast; }
                catch (Exception) { }
            }
        }
#endif
        return target;
    }
#if SMA_IL2CPP
    // CMA 0.70.5: observed UIDocument /InterviewChatBar, with three sibling text elements.
    // Index 0 is the verified NPC name, index 1 is the changing line; index 2 is never voiced.
    private void ResetFixedBox() {
        fixedPending = null; fixedKey = ""; fixedReported = false; fixedLastSource = ""; fixedLastSpoken = ""; fixedLastActor = "";
    }
    private void RememberFixedNotice(TranslationNotice item) {
        if (!enableCmaFixedBox) return;
        Il2CppObjectBase native = item.Component as Il2CppObjectBase;
        if (native == null || native.Pointer == IntPtr.Zero) return;
        if (fixedNotices.Count >= 128 && !fixedNotices.ContainsKey(native.Pointer)) fixedNotices.Clear();
        fixedNotices[native.Pointer] = item;
        // The verified body pointer and exact source bind delayed notices to their
        // original event, even after the visible row has closed or advanced.
        string original = CleanPoll(item.Original), translated = CleanPoll(item.Translation);
        if (original.Length == 0 || translated.Length == 0 || SameBoxText(original,translated)) return;
        float now = Time.realtimeSinceStartup;
        foreach (BoxLine line in boxLines) {
            if (line.Failed || line.Ready || line.ToolkitPointer != native.Pointer ||
                String.IsNullOrEmpty(line.EventPath) || now-line.SentAt > 30f ||
                !SameBoxText(original,line.Original)) continue;
            line.Spoken = translated; line.Ready = true;
            PublishBoxTranslation(line);
        }
    }
    private void FixedDiagnostic(string reason) {
        if (fixedDiagnostic == reason) return;
        fixedDiagnostic = reason;
        Logger.LogInfo("SMA UITK_BOX_STATE | " + reason);
    }
    private bool FixedNodeShown(object node) {
        if (node == null || InspectRead(node,"panel") == null) return false;
        object bounds = InspectRead(node,"worldBound");
        object width = InspectRead(bounds,"width"), height = InspectRead(bounds,"height");
        if (width == null || height == null || !(Convert.ToSingle(width)>0f) || !(Convert.ToSingle(height)>0f)) return false;
        for (int i = 0; node != null && i < 32; i++) {
            object visual = InspectCast(node, fixedVisualType);
            if (visual == null) return false;
            object style = InspectRead(visual,"resolvedStyle");
            if (InspectLabel(InspectRead(style,"display")) != "Flex" ||
                InspectLabel(InspectRead(visual,"visible")) != "True") return false;
            node = InspectRead(visual,"parent");
        }
        return node == null;
    }
    private bool FixedTranslation(object body, string current, out string original, out string spoken) {
        original = current; spoken = current;
        if (!translatorEnabled.Value) return false;
        Il2CppObjectBase native = body as Il2CppObjectBase;
        TranslationNotice notice;
        if (native != null && fixedNotices.TryGetValue(native.Pointer,out notice) &&
            (DateTime.UtcNow-notice.Received).TotalSeconds <= 30) {
            string before = CleanPoll(notice.Original), after = CleanPoll(notice.Translation);
            if (before.Length > 0 && after.Length > 0 && before != after && (current == before || current == after)) {
                original = before; spoken = after; return true;
            }
        }
        try {
            if (getOriginal != null) {
                string raw = Convert.ToString(getOriginal.Invoke(null,new object[] { body }));
                string before = CleanPoll(raw);
                if (before.Length > 0) {
                    string after = CachedBoxTranslation(raw);
                    if (after.Length > 0 && before != after && (current == before || current == after)) {
                        original = before; spoken = after; return true;
                    }
                }
            }
        } catch (Exception) { }
        string cached = CachedBoxTranslation(current);
        if (cached.Length > 0 && cached != current) { spoken = cached; return true; }
        return false;
    }
    private void PollFixedToolkitBox(float now) {
        if (!enableCmaFixedBox || !NativeBoxEnabled() || !(Enabled("TextPoll") || Enabled("Translator"))) return;
        try {
            if (fixedDocumentType == null) fixedDocumentType = FindGameType("UnityEngine.UIElements.UIDocument", "UnityEngine.UIElementsModule", "UnityEngine");
            if (fixedVisualType == null) fixedVisualType = FindGameType("UnityEngine.UIElements.VisualElement", "UnityEngine.UIElementsModule", "UnityEngine");
            if (fixedTextType == null) fixedTextType = FindGameType("UnityEngine.UIElements.TextElement", "UnityEngine.UIElementsModule", "UnityEngine");
            if (fixedDocumentType == null || fixedVisualType == null || fixedTextType == null) return;
            if (now >= nextFixedScan) {
                nextFixedScan = now + 1f;
                Component found = null;
                foreach (Component c in FindTextComponents(fixedDocumentType)) {
                    if (c == null || !c.gameObject.scene.IsValid() || !c.gameObject.scene.isLoaded || !c.gameObject.activeInHierarchy) continue;
                    if (ObjectPath(c) != "/InterviewChatBar") continue;
                    if (found != null && found.GetInstanceID() != c.GetInstanceID()) { found = null; break; }
                    found = c;
                }
                if (found == null || fixedDocument == null || found.GetInstanceID() != fixedDocument.GetInstanceID()) ResetFixedBox();
                fixedDocument = found;
            }
            if (fixedDocument == null || !fixedDocument.gameObject.activeInHierarchy) { FixedDiagnostic("document-missing-or-inactive"); ResetFixedBox(); return; }
            object root = InspectCast(Read(fixedDocument,"rootVisualElement"),fixedVisualType);
            if (root == null || InspectLabel(InspectRead(root,"name")) != "InterviewChatBar-container") { FixedDiagnostic("root-layout-mismatch"); ResetFixedBox(); return; }
            object first = InspectCast(InspectChild(root,0),fixedVisualType);
            object row = first == null ? null : InspectCast(InspectChild(first,0),fixedVisualType);
            if (row == null || Convert.ToInt32(InspectRead(row,"childCount")) != 3) { FixedDiagnostic("row-layout-mismatch"); ResetFixedBox(); return; }
            object nameNode = InspectCast(InspectChild(row,0),fixedTextType);
            object bodyNode = InspectCast(InspectChild(row,1),fixedTextType);
            if (nameNode == null || bodyNode == null || !FixedNodeShown(nameNode) || !FixedNodeShown(bodyNode)) { FixedDiagnostic("text-hidden-or-missing"); ResetFixedBox(); return; }
            string label = CleanPoll(Convert.ToString(Read(nameNode,"text")));
            string raw = CleanPoll(Convert.ToString(Read(bodyNode,"text")));
            if (raw.Length < 2 || PlaceholderName(label)) { FixedDiagnostic("empty-text-or-name"); ResetFixedBox(); return; }
            CharacterVoiceIdentity identity = IdentityForName(label);
            if (!VerifiedBarkIdentity(identity,label)) { FixedDiagnostic("identity-unverified | nameHash="+InspectFingerprint(label)); ResetFixedBox(); return; }
            FixedDiagnostic("verified-npc-line");
            string name = String.IsNullOrWhiteSpace(identity.FullName) ? identity.Name : identity.FullName;
            string key = identity.Id + "|" + raw;
            if (key != fixedKey) {
                fixedKey = key; fixedChanged = now; fixedReported = false; fixedObserved++;
                Logger.LogInfo("SMA UITK_BOX_OBSERVE | speaker="+name+" | chars="+raw.Length+" | hash="+InspectFingerprint(raw));
            }
            string original, spoken;
            bool ready = FixedTranslation(bodyNode,raw,out original,out spoken);
            if (fixedPending != null && fixedPending.Actor == identity.Id && ready &&
                (SameBoxText(original,fixedPending.Original) || SameBoxText(raw,fixedPending.Original)) &&
                now-fixedPending.SentAt <= 30f) {
                fixedPending.Spoken = spoken; fixedPending.Ready = true;
                PublishBoxTranslation(fixedPending);
                fixedLastSpoken = spoken; fixedReported = true;
                return;
            }
            if (fixedReported) return;
            if (now-fixedChanged < Math.Max(pollSeconds,ready ? normalReady : normalFallback)) return;
            if (!ready && !Enabled("TextPoll")) return;
            if (fixedLastActor == identity.Id && (SameBoxText(original,fixedLastSource) || SameBoxText(raw,fixedLastSpoken) || SameBoxText(spoken,fixedLastSpoken))) { fixedReported = true; return; }
            BoxLine existing = FindBoxLine(name,original,spoken,now,false);
            if (existing != null) { fixedReported = true; return; }
            // Keep the normal-box event protocol and local translation fallback; do not mark unknown text ready.
            BoxLine line = NewUiBox(identity.Id,name,identity.Alias,original,spoken,ready,now);
            Il2CppObjectBase bodyNative = bodyNode as Il2CppObjectBase;
            if (bodyNative != null) line.ToolkitPointer = bodyNative.Pointer;
            // Reuse the event-specific late translation protocol used by native boxes.
            if (Export("UITKBox",identity.Id,name,spoken,ready,identity.Alias,true,line)) {
                boxUiSent++; fixedSent++; boxLines.Add(line); fixedPending = line;
                Logger.LogInfo("SMA UITK_BOX_QUEUED | speaker="+name+" | chars="+spoken.Length+" | ready="+ready+" | capture_ms="+(int)((now-fixedChanged)*1000f));
            }
            fixedLastActor = identity.Id; fixedLastSource = original; fixedLastSpoken = spoken; fixedReported = true;
        } catch (Exception e) {
            if (now >= nextFixedError) { nextFixedError = now+5f; Logger.LogWarning("SMA UITK_BOX_ERROR | "+e.GetBaseException().Message); }
        }
    }
#endif
    private static bool SameComponent(object value, Component c) {
#if SMA_IL2CPP
        Component other = AsComponent(value);
        return other != null && c != null && other.GetInstanceID() == c.GetInstanceID();
#else
        return object.ReferenceEquals(value, c);
#endif
    }
#if SMA_IL2CPP
    private static readonly MethodInfo nativeCast = typeof(Il2CppObjectBase).GetMethod("TryCast");
    private static Component TypedComponent(Il2CppObjectBase obj, Type type) {
        if (obj == null) return null;
        return nativeCast.MakeGenericMethod(type).Invoke(obj, null) as Component;
    }
#endif
    private static IEnumerable<Component> FindTextComponents(Type type) {
#if SMA_IL2CPP
        foreach (UnityEngine.Object obj in Resources.FindObjectsOfTypeAll(Il2CppType.From(type))) {
            Component component = TypedComponent(obj, type);
            if (component != null) yield return component;
        }
#else
        foreach (UnityEngine.Object obj in Resources.FindObjectsOfTypeAll(type)) {
            Component component = obj as Component;
            if (component != null) yield return component;
        }
#endif
    }
    private static Component[] CharacterComponents(Transform root, Type type, bool children) {
#if SMA_IL2CPP
        var nativeType = Il2CppType.From(type);
        var native = children ? root.GetComponentsInChildren(nativeType, true) : root.GetComponents(nativeType);
        List<Component> result = new List<Component>();
        foreach (var obj in native) {
            Component component = TypedComponent(obj, type);
            if (component != null) result.Add(component);
        }
        return result.ToArray();
#else
        return children ? root.GetComponentsInChildren(type, true) : root.GetComponents(type);
#endif
    }
    private static object Read(object o, string name)
    {
        if (o == null) return null;
        const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
        Type t = o.GetType();
        PropertyInfo p = t.GetProperty(name, flags);
        if (p != null) return p.GetValue(o, null);
        FieldInfo f = t.GetField(name, flags);
        return f == null ? null : f.GetValue(o);
    }
    public static void AfterSubtitle(object __0, MethodBase __originalMethod)
    {
        if (object.ReferenceEquals(instance, null)) return;
        try { instance.Capture(__0, __originalMethod); } catch (Exception e) { instance.Logger.LogWarning("SMA capture error: " + e); }
    }
    private bool NativeBoxEnabled() { return nativeBox.Value && (Enabled("Subtitle") || Enabled("TextPoll") || Enabled("Translator")); }
    private void CheckBoxScene() {
        int scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().handle;
        if (scene == boxScene) return;
        boxScene = scene; boxLines.Clear();
#if SMA_IL2CPP
        fixedDocument = null; nextFixedScan = 0; fixedNotices.Clear(); ResetFixedBox();
#endif
        List<string> staleBoxKeys = new List<string>();
        foreach (string key in recent.Keys) if (key.StartsWith("box|", StringComparison.Ordinal)) staleBoxKeys.Add(key);
        foreach (string key in staleBoxKeys) recent.Remove(key);
        // Reset only box state, not the working floating-bark state.
        foreach (Component c in pollTargets) if (c != null && IsSubtitle(ObjectPath(c))) {
            int id = c.GetInstanceID(); pollStates.Remove(id); translatorLatest.Remove(id);
            lock (boxWrites) boxWrites.Remove(id);
        }
    }
    private static string BoxText(string text) { return System.Text.RegularExpressions.Regex.Replace(CleanPoll(text), "\\s+", " "); }
    private static bool SameBoxText(string a, string b) { return a.Length > 0 && b.Length > 0 && BoxText(a) == BoxText(b); }
    private BoxLine FindBoxLine(string name, string original, string spoken, float now, bool allowMissingName) {
        BoxLine found = null;
        foreach (BoxLine line in boxLines) {
            // Bound the native/UI reconciliation window, but allow a pending line to survive a slow portrait.
            if (line.Failed || now - (line.Sent ? line.SentAt : line.Created) > 3f) continue;
            if (PlaceholderName(name)) { if (!allowMissingName) continue; }
            else if (!NormalizeName(name).Equals(NormalizeName(line.Name), StringComparison.OrdinalIgnoreCase)) continue;
            if (!(SameBoxText(original,line.Original) || SameBoxText(original,line.Spoken) || SameBoxText(spoken,line.Original) || SameBoxText(spoken,line.Spoken))) continue;
            if (found != null && found != line) return null;
            found = line;
        }
        return found;
    }
    private static bool BoxDisplayMatches(BoxLine line, string name, string original, string spoken) {
        if (line == null || line.Failed || original.Length == 0) return false;
        if (!PlaceholderName(name) && !NormalizeName(name).Equals(NormalizeName(line.Name), StringComparison.OrdinalIgnoreCase)) return false;
        if (SameBoxText(original,line.Original) || SameBoxText(original,line.Spoken) || SameBoxText(spoken,line.Original) || SameBoxText(spoken,line.Spoken)) return true;
        // A typewriter UI can expose prefixes instead of the full native sentence.
        return !PlaceholderName(name) && original.Length >= 3 && BoxText(line.Original).StartsWith(BoxText(original), StringComparison.Ordinal);
    }
    private BoxLine NewUiBox(string actor, string name, string alias, string original, string spoken, bool ready, float now) {
        return new BoxLine { Actor=actor, Name=name, Alias=alias, Original=original, Raw=original, Spoken=spoken, Ready=ready, Sent=true, Origin="UI", Created=now, LastSeen=now, SentAt=now };
    }
    private void PublishBoxTranslation(BoxLine line) {
        if (!line.Ready || line.TranslationPublished || String.IsNullOrEmpty(line.EventPath)) return;
        string path=Path.ChangeExtension(line.EventPath,".boxtr");
        try {
            File.WriteAllText(path+".tmp",Convert.ToBase64String(Encoding.UTF8.GetBytes(line.Spoken)),new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(path+".tmp",path);
            line.TranslationPublished=true;
            Logger.LogInfo("SMA BOX_TRANSLATION_UPDATE | id="+Path.GetFileNameWithoutExtension(path)+" | ms="+((int)((Time.realtimeSinceStartup-line.Created)*1000f)));
        } catch (Exception e) { Logger.LogWarning("SMA BOX_TRANSLATION_UPDATE_FAILED: "+e.Message); }
        finally { try { if (File.Exists(path+".tmp")) File.Delete(path+".tmp"); } catch (IOException) {} }
    }
    private string CachedBoxTranslation(string original) {
        if (!translatorEnabled.Value || getTranslation == null) return "";
        try { return CleanPoll(Convert.ToString(getTranslation.Invoke(null, new object[] { original }))); }
        catch (Exception) { return ""; }
    }
    private void DrainNativeBox(float now) {
        if (!NativeBoxEnabled()) return;
        for (int i=0; i<boxLines.Count; i++) {
            BoxLine line=boxLines[i];
            if (line.Sent && (String.IsNullOrEmpty(line.EventPath) || line.TranslationPublished || now-line.SentAt > 30f)) continue;
            if (!line.Ready) {
                string translated=CachedBoxTranslation(line.Raw ?? line.Original);
                if (translated.Length == 0 && line.Raw != line.Original) translated=CachedBoxTranslation(line.Original);
                if (translated.Length > 0 && !SameBoxText(translated,line.Original)) { line.Spoken=translated; line.Ready=true; }
            }
            if (line.Sent) { PublishBoxTranslation(line); continue; }
            if (!line.Ready && source.Value.Equals("Translator", StringComparison.OrdinalIgnoreCase)) {
                if (now-line.Created > 3f) { line.Sent=true; line.Failed=true; line.SentAt=now; Logger.LogWarning("SMA BOX_DROP translation-only | chars=" + line.Original.Length); }
                continue;
            }
            if (!line.Ready && translatorEnabled.Value && now-line.Created < normalFallback) continue;
            try {
                bool queued=Export("NativeBox",line.Actor,line.Name,line.Spoken,line.Ready,line.Alias,true,line);
                line.Sent=true; line.SentAt=now;
                if (queued) nativeSent++;
                Logger.LogInfo("SMA BOX_NATIVE " + (queued ? "queued" : "duplicate") + " origin=" + line.Origin + " speaker=" + line.Name + " chars=" + line.Spoken.Length + " ready=" + line.Ready + " capture_ms=" + ((int)((now-line.Created)*1000f)));
            } catch (Exception e) {
                Logger.LogWarning("SMA BOX_WRITE_FAILED: " + e.Message);
                if (now-line.Created > 5f) { line.Sent=true; line.Failed=true; line.SentAt=now; Logger.LogWarning("SMA BOX_DROP write failed"); }
            }
        }
        boxLines.RemoveAll(delegate(BoxLine line) { return line.Sent && now-line.SentAt > (String.IsNullOrEmpty(line.EventPath) || line.TranslationPublished ? 3f : 30f); });
    }
    private static object ReadEither(object obj, string first, string second) { return Read(obj,first) ?? Read(obj,second); }
    private void Capture(object subtitle, MethodBase method)
    {
        string origin = method == null ? "unknown" : method.DeclaringType.Name + "." + method.Name;
        System.Threading.Interlocked.Increment(ref subtitleCallbackCount);
        if (!NativeBoxEnabled()) return;
        CheckBoxScene();
        object speaker = ReadEither(subtitle, "speakerInfo", "SpeakerInfo");
        if (speaker == null) { Logger.LogWarning("SMA BOX_DROP no speakerInfo at " + origin); return; }
        string id = Convert.ToString(ReadEither(speaker,"id","Id"));
        string name = CleanPoll(Convert.ToString(ReadEither(speaker,"Name","name")));
        object player = ReadEither(speaker,"IsPlayer","isPlayer"), npc = ReadEither(speaker,"IsNPC","isNPC");
        object formatted = ReadEither(subtitle,"formattedText","FormattedText");
        string raw = formatted as string ?? Convert.ToString(ReadEither(formatted,"text","Text"));
        if (String.IsNullOrWhiteSpace(raw)) raw=Convert.ToString(ReadEither(subtitle,"text","Text"));
        string text=CleanPoll(raw);
        if (!object.Equals(player,false) || !object.Equals(npc,true) || id == "00000001-0000-0000-0000-000000000000" || String.IsNullOrWhiteSpace(text)) {
            Logger.LogInfo("SMA BOX_DROP native flags/text | origin=" + origin + " player=" + player + " npc=" + npc + " chars=" + text.Length); return;
        }
        CharacterVoiceIdentity identity=IdentityForName(name);
        bool verified=IsAllowed(id) || NameAllowed(name) || identity != null || (!PlaceholderName(name) && registryNames.Contains(NormalizeName(name)));
        if (!verified && (!nativeUnknownNpc.Value || PlaceholderName(name))) {
            Logger.LogInfo("SMA BOX_DROP native authorization | origin=" + origin + " speaker=" + name); return;
        }
        float now=Time.realtimeSinceStartup;
        BoxLine existing=FindBoxLine(name,text,text,now,false);
        if (existing != null) { existing.LastSeen=now; return; }
        // Late-translation records must not block new native dialogue.
        if (boxLines.Count >= 128) {
            int oldSent=boxLines.FindIndex(delegate(BoxLine line) { return line.Sent; });
            if (oldSent >= 0) boxLines.RemoveAt(oldSent);
            else { Logger.LogWarning("SMA BOX_DROP native backlog full"); return; }
        }
        Guid guid;
        string actor=identity != null ? identity.Id : (Guid.TryParse(id,out guid) && guid != Guid.Empty ? guid.ToString("D") : (PlaceholderName(name) ? id : name));
        boxLines.Add(new BoxLine { Actor=actor, Name=name, Alias=identity != null ? identity.Alias : "", Original=text, Raw=raw, Spoken=text, Origin=origin, Created=now, LastSeen=now });
        nativeAccepted++;
        Logger.LogInfo("SMA BOX_ACCEPT native | origin=" + origin + " speaker=" + name + " verifiedModel=" + verified + " chars=" + text.Length);
    }

    private bool Enabled(string route)
    {
        return source.Value.Equals(route, StringComparison.OrdinalIgnoreCase) || source.Value.Equals("Hybrid", StringComparison.OrdinalIgnoreCase);
    }
    private bool IsAllowed(string id)
    {
        if (String.IsNullOrWhiteSpace(id)) return false;
        foreach (string item in allowedIds.Value.Split(',')) if (item.Trim() == id) return true;
        return false;
    }
    private int TryTextHook(string assemblyName, string typeName)
    {
        try {
            Type type = Assembly.Load(assemblyName).GetType(typeName, true);
            MethodInfo setter = type.GetMethod("set_text", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new Type[] { typeof(string) }, null);
            if (setter == null || setter.IsAbstract) throw new MissingMethodException(typeName, "set_text");
            harmony.Patch(setter, postfix: new HarmonyMethod(typeof(SMAVoiceCapture).GetMethod("AfterText", BindingFlags.Public | BindingFlags.Static)));
            Logger.LogInfo("SMA text hook installed: " + typeName);
            return 1;
        } catch (Exception e) { Logger.LogWarning("SMA text hook unavailable: " + typeName + " | " + e.Message); return 0; }
    }
    public static void AfterText(object __instance, string __0)
    {
        if (object.ReferenceEquals(instance, null)) return;
        System.Threading.Interlocked.Increment(ref instance.textCallbackCount);
        if (String.IsNullOrWhiteSpace(__0) && !instance.BarkRecoveryEnabled() && !instance.nativeBox.Value) return;
        try {
            string path = ObjectPath(__instance);
            Component c = AsComponent(__instance);
            if (c != null && instance.BarkRecoveryEnabled() && instance.FemaleBarkPath(path))
                instance.RememberBarkWrite(c, __0);
            if (c != null && instance.NativeBoxEnabled() && IsSubtitle(path)) instance.RememberBoxWrite(c, __0);
            if (String.IsNullOrWhiteSpace(__0)) return;
            if (instance.nativeBox.Value && c != null && (IsSubtitle(path) || IsSpeakerName(path))) {
                lock (instance.boxTargetLock) if (instance.boxTargetNotices.Count < 256 && !instance.boxTargetNotices.Contains(c)) instance.boxTargetNotices.Add(c);
            }
            if (!instance.uiFallback.Value || String.IsNullOrWhiteSpace(instance.uiPaths.Value)) return;
            if (!Matches(instance.uiPaths.Value, path)) return;
            instance.Logger.LogInfo("SMA text UI: path=" + path + " length=" + __0.Length);
            if (instance.Enabled("TextUI")) instance.Export("TextUI", path, "", __0);
        } catch (Exception e) { instance.Logger.LogWarning("SMA text capture error: " + e.Message); }
    }
    private static string ObjectPath(object obj)
    {
        Component comp = AsComponent(obj);
        if (comp == null) return "";
        Transform t = comp.transform;
        string path = "";
        while (t != null) { path = "/" + t.name + path; t = t.parent; }
        return path;
    }
    public static void AfterController(object __instance, string __0, bool __1, string __2, bool __result)
    {
        if (object.ReferenceEquals(instance, null)) return;
        try {
            string path = ObjectPath(__instance);
            string text = String.IsNullOrWhiteSpace(__2) ? __0 : __2;
            instance.Logger.LogInfo("SMA bark controller: accepted=" + __result + " vocalizar=" + __1 + " path=" + path + " length=" + (text ?? "").Length);
            if (__result && __1 && instance.Enabled("Controller") && Matches(instance.allowedPaths.Value, path))
                instance.Export("Controller", path, "", text);
        } catch (Exception e) { instance.Logger.LogWarning("SMA bark capture error: " + e); }
    }
    public static void AfterUI(object __instance, string __0, string __1, bool __result)
    {
        if (object.ReferenceEquals(instance, null)) return;
        try {
            string name = __1 ?? "";
            instance.Logger.LogInfo("SMA bark UI: accepted=" + __result + " speaker=" + name + " path=" + ObjectPath(__instance) + " length=" + (__0 ?? "").Length);
            if (__result && instance.Enabled("UI") && Matches(instance.allowedNames.Value, name))
                instance.Export("UI", name, name, __0);
        } catch (Exception e) { instance.Logger.LogWarning("SMA bark capture error: " + e); }
    }
    private static bool Matches(string list, string value)
    {
        if (String.IsNullOrWhiteSpace(value)) return false;
        foreach (string item in list.Split('|')) if (item.Trim().Equals(value, StringComparison.Ordinal)) return true;
        return false;
    }
    private bool Export(string route, string actor, string name, string text, bool translated = false, string alias = "", bool normalBox = false, BoxLine linkedBox = null)
    {
        if (String.IsNullOrWhiteSpace(text)) return false;
        DateTime now = DateTime.UtcNow;
        // Different routes can report the same subtitle in rapid succession.
        // Text-only dedup is intentionally short and only applied after authorization.
        string normalized = System.Text.RegularExpressions.Regex.Replace(text.Trim(), "\\s+", " ");
        Guid voiceId;
        if (Guid.TryParse(actor, out voiceId)) normalized = voiceId.ToString("D") + "|" + normalized;
        if (normalBox) normalized = "box|" + (PlaceholderName(name) ? actor : NormalizeName(name).ToUpperInvariant()) + "|" + BoxText(text);
        DateTime last;
        if (recent.TryGetValue(normalized, out last) && (now - last).TotalMilliseconds < captureDedupMs) { if (normalBox) Logger.LogInfo("SMA BOX_DROP capture duplicate | speaker=" + name); return false; }
        if (recent.Count > 256) recent.Clear();
        string path = Path.Combine(spool, now.Ticks.ToString("D19") + "-" + Guid.NewGuid().ToString("N") + ".evt");
        string payload = actor.Replace("\r", "").Replace("\n", "") + "\n" + Convert.ToBase64String(Encoding.UTF8.GetBytes(name)) + "\n" + Convert.ToBase64String(Encoding.UTF8.GetBytes(text)) + "\n" + (translated ? "pt-ready" : "translate") + "\n" + (String.IsNullOrEmpty(alias) ? "-" : alias);
        // The optional sixth line is emitted only for the normal dialogue box.
        if (normalBox) payload += "\nbox";
        bool liveTranslation = normalBox && !translated && linkedBox != null && translatorEnabled.Value && translatorInstalled;
        if (liveTranslation) payload += "\ntranslation-update";
        try {
            File.WriteAllText(path + ".tmp", payload, new UTF8Encoding(false));
            File.Move(path + ".tmp", path);
        } finally { if (File.Exists(path + ".tmp")) File.Delete(path + ".tmp"); }
        if (liveTranslation) linkedBox.EventPath=path;
        recent[normalized] = now;
        Logger.LogInfo("SMA queued: route=" + route + " actor=" + actor + " length=" + text.Length + " id=" + Path.GetFileNameWithoutExtension(path));
        return true;
    }
    private void OnDisable() { if (!quitting) Logger.LogWarning("SMA plugin owner disabled; independent driver remains active"); }
    private void OnDestroy() { if (!quitting) Logger.LogWarning("SMA plugin owner destroyed; independent driver/render fallback retain managed state"); }
    private void Shutdown()
    {
        if (quitting) return;
        quitting = true;
#if !SMA_IL2CPP
        Application.onBeforeRender -= BeforeRenderTick;
        Application.quitting -= Shutdown;
#endif
        Logger.LogInfo("SMA SESSION_CAPTURE_END | textCallbacks=" + textCallbackCount + " translatorCallbacks=" + translatorCallbackCount + " subtitleCallbacks=" + subtitleCallbackCount + " nativeAccepted=" + nativeAccepted + " nativeSent=" + nativeSent + " boxUiSent=" + boxUiSent);
#if SMA_IL2CPP
        Logger.LogInfo("SMA SESSION_UITK_BOX_END | observed="+fixedObserved+" | queued="+fixedSent);
#endif
        Logger.LogInfo("SMA SESSION_BARK_END | observed=" + barkObserved + " barkSent=" + barkSent + " barkBlocked=" + barkBlocked + " evidenceUsed=" + barkEvidenceUsed);
        if (harmony != null) harmony.UnpatchSelf();
        instance = null;
    }
}

public sealed class SMAVoiceTickDriver : MonoBehaviour
{
#if SMA_IL2CPP
    public SMAVoiceTickDriver(IntPtr ptr) : base(ptr) { }
    private void Update() { SMAVoiceCapture.DriverTick(); }
    private void OnApplicationQuit() { SMAVoiceCapture.DriverQuit(); }
#else
    internal SMAVoiceCapture Owner;
    private void Update() { if (!object.ReferenceEquals(Owner, null)) Owner.Tick("persistent-driver"); }
    private void OnDestroy() { if (!object.ReferenceEquals(Owner, null)) Owner.DriverDestroyed(); }
#endif
}
