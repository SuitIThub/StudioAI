using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using BepInEx;
using BepInEx.Configuration;
using KKAPI.Studio.UI;
using StudioAi.Contracts;
using UnityEngine;

namespace StudioAi.Plugin
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    [BepInProcess("StudioNEOV2")]
    [BepInDependency("com.hs2.sandbox.posebrowser", BepInDependency.DependencyFlags.SoftDependency)]
    public class StudioAiPlugin : BaseUnityPlugin
    {
        public const string PluginGuid = "com.suitji.studio_ai";
        public const string PluginName = "StudioAI";
        public const string PluginVersion = "0.8.1";

        public static StudioAiPlugin Instance { get; private set; }

        public static bool IsSearchBusy { get; private set; }
        public static bool IsProbeBusy { get; private set; }
        public static bool IsIndexBusy { get; private set; }
        public static string LastStatus { get; private set; } = "";
        public static string LastIndexStatus { get; private set; } = "";
        public static string LastCoreUrl { get; private set; } = "";
        public static string LastQuery { get; private set; } = "";
        public static int LastHitCount { get; private set; }

        private ConfigEntry<string> _coreUrl;
        private ConfigEntry<int> _searchLimit;
        private ConfigEntry<bool> _verboseLog;
        private ConfigEntry<bool> _indexUseJoycaption;
        private ConfigEntry<bool> _indexUseMerge;
        private ConfigEntry<int> _indexCharacterId;
        private ConfigEntry<KeyboardShortcut> _hotkeySearchClipboard;
        private ConfigEntry<KeyboardShortcut> _hotkeyChat;

        private StudioAiChatWindow _chat;
        private Texture2D _chatIcon;
        private ToolbarToggle _chatToolbarToggle;
        private bool _syncingToolbar;

        internal string CoreUrlHint => _coreUrl.Value;

        private void Awake()
        {
            Instance = this;
            _coreUrl = Config.Bind(
                "Core",
                "BaseUrl",
                "http://127.0.0.1:7200",
                "Preferred Core URL. Discovers 7200–7299 once via UnityWebRequest, then locks.");
            _searchLimit = Config.Bind("Search", "Limit", 40, "Max FTS hits to push into Pose Browser");
            _verboseLog = Config.Bind(
                "Logging",
                "Verbose",
                true,
                "Write HTTP discover/probe/search detail to BepInEx LogOutput.log ([dbg] lines).");
            _indexUseJoycaption = Config.Bind(
                "Index",
                "UseJoyCaption",
                true,
                "Run JoyCaption during index (required for real semantic captions). Needs VRAM; first call is slow.");
            _indexUseMerge = Config.Bind(
                "Index",
                "UseMerge",
                true,
                "Qwen+GBNF merge when Worker online.");
            _indexCharacterId = Config.Bind(
                "Index",
                "CharacterId",
                0,
                "Studio character id for Bridge capture while indexing (pose is applied first via PoseBrowser).");
            _hotkeySearchClipboard = Config.Bind(
                "Hotkeys",
                "SearchClipboard",
                new KeyboardShortcut(KeyCode.None),
                "Optional clipboard AI search.");
            _hotkeyChat = Config.Bind(
                "Hotkeys",
                "ToggleChat",
                new KeyboardShortcut(KeyCode.F9),
                "Show/hide StudioAI Chat window.");

            StudioAiLog.Bind(Logger);
            StudioAiLog.Verbose = _verboseLog.Value;
            _verboseLog.SettingChanged += (_, __) => StudioAiLog.Verbose = _verboseLog.Value;

            _chat = new StudioAiChatWindow(this);

            StudioAiLog.Info(
                PluginName + " v" + PluginVersion +
                " (contract " + ContractVersions.Expected +
                "; Chat toolbar + F9; PB=search+index)");
        }

        private void Start()
        {
            // Same pattern as HS2-Sandbox PoseBrowser / CopyScript plugins.
            _chatIcon = ToolbarIconLoader.LoadPng("chat-icon.png");
            _chatToolbarToggle = CustomToolbarButtons.AddLeftToolbarToggle(
                _chatIcon,
                onValueChanged: val =>
                {
                    if (_syncingToolbar) return;
                    _chat?.SetVisible(val);
                });
            _chatToolbarToggle.Value = _chat != null && _chat.Visible;

            if (_chat != null)
            {
                _chat.VisibilityChanged += visible =>
                {
                    if (_chatToolbarToggle == null) return;
                    _syncingToolbar = true;
                    try { _chatToolbarToggle.Value = visible; }
                    finally { _syncingToolbar = false; }
                };
            }

            StudioAiLog.Info("StudioAI Chat registered on Studio left toolbar");
        }

        private void OnDestroy()
        {
            if (ReferenceEquals(Instance, this))
                Instance = null;
        }

        private void Update()
        {
            if (_hotkeySearchClipboard.Value.MainKey != KeyCode.None &&
                _hotkeySearchClipboard.Value.IsDown())
                RunClipboardSearch();

            if (_hotkeyChat.Value.MainKey != KeyCode.None &&
                _hotkeyChat.Value.IsDown())
                _chat.Toggle();

            _chat?.Tick();
        }

        private void OnGUI()
        {
            _chat?.OnGUI();
        }

        public static string TryBeginSearch(string query)
        {
            if (Instance == null)
            {
                StudioAiLog.Error("TryBeginSearch: Instance is null");
                return "StudioAI Instance is null (plugin not awake?)";
            }

            if (string.IsNullOrEmpty(query) || query.Trim().Length == 0)
            {
                StudioAiLog.Warn("TryBeginSearch: empty query");
                return "Empty query";
            }

            if (IsSearchBusy)
            {
                StudioAiLog.Warn("TryBeginSearch: already busy");
                return "Search already in progress";
            }

            StudioAiLog.Info("AI search start: '" + query.Trim() + "'");
            Instance.StartCoroutine(Instance.SearchCoroutine(query.Trim()));
            return "";
        }

        public static string TryBeginIndexRoot(string poseRoot)
        {
            if (Instance == null)
                return "StudioAI Instance is null";
            if (string.IsNullOrEmpty(poseRoot) || !Directory.Exists(poseRoot))
                return "Pose root missing: " + poseRoot;
            if (IsIndexBusy)
                return "Index already running";

            var paths = new List<string>();
            try
            {
                foreach (var f in Directory.EnumerateFiles(poseRoot, "*.png", SearchOption.AllDirectories))
                    paths.Add(f);
                if (paths.Count == 0)
                {
                    foreach (var d in Directory.EnumerateDirectories(poseRoot, "*", SearchOption.AllDirectories))
                    {
                        if (File.Exists(Path.Combine(d, "pose_compact.txt")))
                            paths.Add(d);
                    }
                }
            }
            catch (Exception ex)
            {
                return "Enumerate failed: " + ex.Message;
            }

            if (paths.Count == 0)
                return "No poses found under " + poseRoot;

            Instance.StartCoroutine(Instance.IndexPathsCoroutine(paths, "all"));
            return "";
        }

        public static string TryBeginIndexPaths(IList<string> absolutePaths)
        {
            if (Instance == null)
                return "StudioAI Instance is null";
            if (absolutePaths == null || absolutePaths.Count == 0)
                return "No paths";
            if (IsIndexBusy)
                return "Index already running";

            var list = absolutePaths.Where(p => !string.IsNullOrEmpty(p)).Distinct().ToList();
            Instance.StartCoroutine(Instance.IndexPathsCoroutine(list, "selection"));
            return "";
        }

        public static string TryClearIndex()
        {
            if (Instance == null)
                return "StudioAI Instance is null";
            if (IsIndexBusy)
                return "Index busy — wait for current job";
            Instance.StartCoroutine(Instance.ClearIndexCoroutine());
            return "";
        }

        public static bool TryClearAiFilterStatic()
        {
            if (Instance != null)
                return Instance.TryClearAiFilter();
            return PoseBrowserClearFallback();
        }

        public static string ProbeCore()
        {
            if (Instance == null)
            {
                StudioAiLog.Error("ProbeCore: Instance is null");
                return "FAIL: StudioAI Instance is null";
            }

            if (IsProbeBusy)
            {
                StudioAiLog.Debug("ProbeCore: already busy → " + LastStatus);
                return LastStatus;
            }

            StudioAiLog.Info("ProbeCore: starting…");
            Instance.StartCoroutine(Instance.ProbeCoroutine());
            return LastStatus;
        }

        public static bool TryShowPoseInBrowser(string path)
        {
            if (string.IsNullOrEmpty(path)) return false;
            try
            {
                var t = FindPoseBrowserExternalApi();
                if (t == null) return false;
                var m = t.GetMethod("TrySetAiSearchResults", BindingFlags.Public | BindingFlags.Static);
                if (m == null) return false;
                return Equals(m.Invoke(null, new object[] { new[] { path } }), true);
            }
            catch (Exception ex)
            {
                StudioAiLog.Error("Show pose in browser failed", ex);
                return false;
            }
        }

        public static bool TryApplyPose(string path)
        {
            if (string.IsNullOrEmpty(path)) return false;
            try
            {
                var t = FindPoseBrowserExternalApi();
                if (t == null) return false;
                var m = t.GetMethod("TryApplyPoseByPath", BindingFlags.Public | BindingFlags.Static, null,
                    new[] { typeof(string) }, null);
                if (m == null)
                    m = t.GetMethod("TryApplyPoseByPath", BindingFlags.Public | BindingFlags.Static);
                if (m == null) return false;
                return Equals(m.Invoke(null, new object[] { path }), true);
            }
            catch (Exception ex)
            {
                StudioAiLog.Error("Apply pose failed", ex);
                return false;
            }
        }

        private IEnumerator ProbeCoroutine()
        {
            IsProbeBusy = true;
            LastStatus = "Probing Core (UnityWebRequest)…";
            StudioAiCoreUnityClient.Invalidate();

            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_coreUrl.Value, err => discoverErr = err);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                LastStatus = "FAIL: " + discoverErr;
                StudioAiLog.Error(LastStatus);
                IsProbeBusy = false;
                yield break;
            }

            LastCoreUrl = StudioAiCoreUnityClient.LockedBaseUrl;
            string contractErr = null;
            string contractVer = null;
            yield return StudioAiCoreUnityClient.GetLiveContract(
                ver => contractVer = ver,
                err => contractErr = err);

            if (!string.IsNullOrEmpty(contractErr))
            {
                LastStatus = "FAIL: " + contractErr;
                StudioAiLog.Error(LastStatus);
                IsProbeBusy = false;
                yield break;
            }

            LastStatus = "OK: " + LastCoreUrl + " contract=" + contractVer;
            StudioAiLog.Info(LastStatus);
            IsProbeBusy = false;
        }

        private void RunClipboardSearch()
        {
            string query;
            try
            {
                query = GUIUtility.systemCopyBuffer != null ? GUIUtility.systemCopyBuffer.Trim() : "";
            }
            catch (Exception ex)
            {
                StudioAiLog.Error("Clipboard read failed", ex);
                return;
            }

            if (string.IsNullOrEmpty(query))
            {
                LastStatus = "Clipboard empty";
                StudioAiLog.Warn(LastStatus);
                return;
            }

            TryBeginSearch(query);
        }

        private IEnumerator SearchCoroutine(string query)
        {
            IsSearchBusy = true;
            LastQuery = query ?? "";
            LastHitCount = 0;
            LastStatus = "Searching…";

            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_coreUrl.Value, err => discoverErr = err);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                LastStatus = "Core discover failed: " + discoverErr;
                StudioAiLog.Error(LastStatus);
                IsSearchBusy = false;
                yield break;
            }

            LastCoreUrl = StudioAiCoreUnityClient.LockedBaseUrl;

            string contractErr = null;
            yield return StudioAiCoreUnityClient.GetLiveContract(_ => { }, err => contractErr = err);
            if (!string.IsNullOrEmpty(contractErr))
            {
                LastStatus = "Core contract check failed: " + contractErr;
                StudioAiLog.Error(LastStatus);
                IsSearchBusy = false;
                yield break;
            }

            SearchResponse result = null;
            string searchErr = null;
            yield return StudioAiCoreUnityClient.Search(
                query,
                _searchLimit.Value,
                r => result = r,
                err => searchErr = err);

            if (!string.IsNullOrEmpty(searchErr))
            {
                LastStatus = "AI search failed: " + searchErr;
                StudioAiLog.Error(LastStatus);
                IsSearchBusy = false;
                yield break;
            }

            var hits = result != null && result.Hits != null ? result.Hits : new List<SearchHitDto>();
            LastHitCount = hits.Count;
            var paths = hits
                .Select(h => h.Path)
                .Where(p => !string.IsNullOrEmpty(p))
                .Cast<string>()
                .ToList();
            if (paths.Count == 0)
            {
                paths = hits
                    .Select(h => h.PoseId)
                    .Where(p => !string.IsNullOrEmpty(p))
                    .Cast<string>()
                    .ToList();
            }

            bool pushed = TryPushAiSearchToPoseBrowser(paths);
            LastStatus = hits.Count + " hits, " + paths.Count + " paths · PoseBrowser=" +
                         (pushed ? "filtered" : "unavailable");
            if (!pushed)
                StudioAiLog.Warn("AI search: PoseBrowser filter push unavailable");
            StudioAiLog.Info("AI search '" + query + "' → " + LastStatus + " @ " + LastCoreUrl);
            IsSearchBusy = false;
        }

        private IEnumerator IndexPathsCoroutine(List<string> paths, string label)
        {
            IsIndexBusy = true;
            LastIndexStatus = "Indexing " + label + " (" + paths.Count + ") LIVE…";
            LastStatus = LastIndexStatus;
            StudioAiLog.Info(LastIndexStatus + " (apply pose → Core capture → JoyCaption → merge)");

            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_coreUrl.Value, err => discoverErr = err);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                LastIndexStatus = "Index failed: " + discoverErr;
                LastStatus = LastIndexStatus;
                StudioAiLog.Error(LastIndexStatus);
                IsIndexBusy = false;
                yield break;
            }

            LastCoreUrl = StudioAiCoreUnityClient.LockedBaseUrl;

            // One pose at a time: apply in Studio, then full Core pipeline
            var indexed = 0;
            var errors = 0;
            var summaries = new List<string>();
            for (var i = 0; i < paths.Count; i++)
            {
                var path = paths[i];
                LastIndexStatus = "Indexing " + label + " " + (i + 1) + "/" + paths.Count + ": " + Path.GetFileName(path);
                LastStatus = LastIndexStatus;
                StudioAiLog.Info(LastIndexStatus);

                bool applied = TryApplyPose(path);
                StudioAiLog.Info("Apply before index: " + path + " → " + applied);
                // Let Studio settle FK / mesh before Bridge screenshots
                yield return new WaitForSecondsRealtime(0.5f);

                string body = null;
                string err = null;
                yield return StudioAiCoreUnityClient.IndexPaths(
                    new List<string> { path },
                    _indexUseJoycaption.Value,
                    _indexUseMerge.Value,
                    _indexCharacterId.Value,
                    t => body = t,
                    e => err = e);

                if (!string.IsNullOrEmpty(err))
                {
                    errors++;
                    StudioAiLog.Error("Index failed for " + path + ": " + err);
                    summaries.Add(Path.GetFileName(path) + " FAIL " + TruncateForLog(err, 120));
                    continue;
                }

                var summary = StudioAiSearchJson.SummarizeIndexResponse(body ?? "");
                summaries.Add(summary);
                StudioAiLog.Info("Index result: " + summary + " raw=" + TruncateForLog(body, 300));

                var mark = body != null ? body.IndexOf("\"indexed\"", StringComparison.Ordinal) : -1;
                if (mark >= 0)
                {
                    var n = 0;
                    for (var p = mark + 9; p < body!.Length; p++)
                    {
                        if (body[p] >= '0' && body[p] <= '9')
                            n = n * 10 + (body[p] - '0');
                        else if (n > 0 || body[p] == ',')
                            break;
                    }
                    indexed += n > 0 ? n : 1;
                }
                else
                    indexed++;
            }

            LastIndexStatus = "Index " + label + " done: indexed≈" + indexed +
                              ", errors=" + errors + " @ " + LastCoreUrl +
                              " · " + string.Join(" | ", summaries);
            LastStatus = LastIndexStatus;
            StudioAiLog.Info(LastIndexStatus);
            IsIndexBusy = false;
        }

        private IEnumerator ClearIndexCoroutine()
        {
            IsIndexBusy = true;
            LastIndexStatus = "Clearing pose index…";
            LastStatus = LastIndexStatus;
            StudioAiLog.Info(LastIndexStatus);

            string discoverErr = null;
            yield return StudioAiCoreUnityClient.EnsureResolved(_coreUrl.Value, err => discoverErr = err);
            if (!string.IsNullOrEmpty(discoverErr))
            {
                LastIndexStatus = "Clear failed: " + discoverErr;
                LastStatus = LastIndexStatus;
                StudioAiLog.Error(LastIndexStatus);
                IsIndexBusy = false;
                yield break;
            }

            LastCoreUrl = StudioAiCoreUnityClient.LockedBaseUrl;
            string body = null;
            string err = null;
            yield return StudioAiCoreUnityClient.ClearIndex(t => body = t, e => err = e);
            if (!string.IsNullOrEmpty(err))
            {
                LastIndexStatus = "Clear failed: " + err;
                LastStatus = LastIndexStatus;
                StudioAiLog.Error(LastIndexStatus);
                IsIndexBusy = false;
                yield break;
            }

            var deleted = StudioAiSearchJson.TryReadJsonString(body, "deleted");
            // deleted is numeric — Summarize-style
            var summary = body ?? "";
            var n = 0;
            var mark = summary.IndexOf("\"deleted\"", StringComparison.Ordinal);
            if (mark >= 0)
            {
                for (var p = mark + 9; p < summary.Length; p++)
                {
                    if (summary[p] >= '0' && summary[p] <= '9')
                        n = n * 10 + (summary[p] - '0');
                    else if (n > 0 || summary[p] == ',')
                        break;
                }
            }

            LastIndexStatus = "Index cleared: deleted=" + n + " @ " + LastCoreUrl;
            LastStatus = LastIndexStatus;
            StudioAiLog.Info(LastIndexStatus + " raw=" + TruncateForLog(body, 200));
            IsIndexBusy = false;
        }

        private static string TruncateForLog(string s, int max)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Replace("\r", " ").Replace("\n", " ");
            return s.Length <= max ? s : s.Substring(0, max) + "…";
        }

        public bool TryClearAiFilter()
        {
            var ok = TryClearAiSearchOnPoseBrowser();
            StudioAiLog.Debug("Clear AI filter → " + ok);
            return ok;
        }

        private static bool PoseBrowserClearFallback()
        {
            try
            {
                var t = FindPoseBrowserExternalApi();
                if (t == null) return false;
                var m = t.GetMethod("TryClearAiSearchResults", BindingFlags.Public | BindingFlags.Static);
                return m != null && Equals(m.Invoke(null, null), true);
            }
            catch (Exception ex)
            {
                StudioAiLog.Error("PoseBrowser clear fallback failed", ex);
                return false;
            }
        }

        private static bool TryPushAiSearchToPoseBrowser(IList<string> paths)
        {
            try
            {
                var t = FindPoseBrowserExternalApi();
                if (t == null)
                {
                    StudioAiLog.Warn("PoseBrowserExternalApi type not found");
                    return false;
                }

                var m = t.GetMethod("TrySetAiSearchResults", BindingFlags.Public | BindingFlags.Static);
                if (m == null)
                {
                    StudioAiLog.Warn("TrySetAiSearchResults missing on PoseBrowser");
                    return false;
                }

                return Equals(m.Invoke(null, new object[] { paths }), true);
            }
            catch (Exception ex)
            {
                StudioAiLog.Error("Push AI results failed", ex);
                return false;
            }
        }

        private static bool TryClearAiSearchOnPoseBrowser()
        {
            try
            {
                var t = FindPoseBrowserExternalApi();
                if (t == null) return false;
                var m = t.GetMethod("TryClearAiSearchResults", BindingFlags.Public | BindingFlags.Static);
                if (m == null) return false;
                return Equals(m.Invoke(null, null), true);
            }
            catch (Exception ex)
            {
                StudioAiLog.Error("Clear AI search failed", ex);
                return false;
            }
        }

        private static Type FindPoseBrowserExternalApi()
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    var t = asm.GetType("HS2SandboxPlugin.PoseBrowserExternalApi");
                    if (t != null) return t;
                }
                catch
                {
                    // ignore
                }
            }

            return null;
        }
    }
}
