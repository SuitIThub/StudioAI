using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using BepInEx;
using BepInEx.Configuration;
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
        public const string PluginVersion = "0.5.0";

        private ConfigEntry<string> _coreUrl = null!;
        private ConfigEntry<int> _searchLimit = null!;
        private ConfigEntry<KeyboardShortcut> _hotkeySearchClipboard = null!;

        private void Awake()
        {
            _coreUrl = Config.Bind(
                "Core",
                "BaseUrl",
                "http://127.0.0.1:7860",
                "StudioAI Core base URL");
            _searchLimit = Config.Bind("Search", "Limit", 40, "Max FTS hits to push into Pose Browser");
            _hotkeySearchClipboard = Config.Bind(
                "Hotkeys",
                "SearchClipboard",
                new KeyboardShortcut(KeyCode.F8),
                "Search Core with clipboard text and filter Pose Browser grid");

            Logger.LogInfo($"{PluginName} v{PluginVersion} (expects contract {ContractVersions.Expected})");
        }

        private void Update()
        {
            if (_hotkeySearchClipboard.Value.IsDown())
                _ = RunClipboardSearchAsync();
        }

        private async Task RunClipboardSearchAsync()
        {
            string query = "";
            try
            {
                query = GUIUtility.systemCopyBuffer?.Trim() ?? "";
            }
            catch (Exception ex)
            {
                Logger.LogWarning($"Clipboard read failed: {ex.Message}");
                return;
            }

            if (string.IsNullOrEmpty(query))
            {
                Logger.LogInfo("Clipboard empty – nothing to search");
                return;
            }

            await SearchAndFilterAsync(query).ConfigureAwait(true);
        }

        /// <summary>Public entry for other plugins / future UI (Stage 5b).</summary>
        public async Task SearchAndFilterAsync(string query)
        {
            try
            {
                using var client = new StudioAiCoreClient(_coreUrl.Value);
                var (ok, detail) = await client.CheckContractAsync().ConfigureAwait(true);
                if (!ok)
                {
                    Logger.LogError($"StudioAI Core contract check failed: {detail}");
                    return;
                }

                var result = await client.SearchAsync(query, _searchLimit.Value).ConfigureAwait(true);
                var hits = result?.Hits ?? new List<SearchHitDto>();
                var paths = hits
                    .Select(h => h.Path)
                    .Where(p => !string.IsNullOrWhiteSpace(p))
                    .Cast<string>()
                    .ToList();

                // Fallback: pose_id when path missing (offline batch fixtures)
                if (paths.Count == 0)
                {
                    paths = hits
                        .Select(h => h.PoseId)
                        .Where(p => !string.IsNullOrWhiteSpace(p))
                        .Cast<string>()
                        .ToList();
                }

                bool pushed = TryPushAiSearchToPoseBrowser(paths);
                Logger.LogInfo(
                    $"AI search '{query}' → {hits.Count} hits, {paths.Count} paths, " +
                    $"PoseBrowser={(pushed ? "filtered" : "unavailable")}");
            }
            catch (Exception ex)
            {
                Logger.LogError($"AI search failed: {ex.Message}");
            }
        }

        public bool TryClearAiFilter() => TryClearAiSearchOnPoseBrowser();

        private static bool TryPushAiSearchToPoseBrowser(IList<string> paths)
        {
            try
            {
                var t = FindPoseBrowserExternalApi();
                if (t == null) return false;
                var m = t.GetMethod("TrySetAiSearchResults", BindingFlags.Public | BindingFlags.Static);
                if (m == null) return false;
                var result = m.Invoke(null, new object[] { paths });
                return result is true;
            }
            catch
            {
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
                return m.Invoke(null, null) is true;
            }
            catch
            {
                return false;
            }
        }

        private static Type? FindPoseBrowserExternalApi()
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
                    // ignore reflection-only / unload issues
                }
            }
            return null;
        }
    }
}
