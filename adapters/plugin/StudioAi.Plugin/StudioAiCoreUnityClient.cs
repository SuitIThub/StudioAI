using System;
using System.Collections;
using System.Text;
using StudioAi.Contracts;
using UnityEngine.Networking;

namespace StudioAi.Plugin
{
    /// <summary>
    /// Outbound Core client using UnityWebRequest — same stack as CopyScript / PoseBrowser update checks.
    /// Do not use HttpClient, HttpWebRequest, or hand-rolled TCP from BepInEx plugins.
    /// </summary>
    internal static class StudioAiCoreUnityClient
    {
        public const int PortMin = 7200;
        public const int PortMax = 7299;

        private static string _lockedBaseUrl;

        public static string LockedBaseUrl => _lockedBaseUrl;

        public static void Invalidate()
        {
            if (!string.IsNullOrEmpty(_lockedBaseUrl))
                StudioAiLog.Debug("Invalidate locked Core URL was " + _lockedBaseUrl);
            _lockedBaseUrl = null;
        }

        public static IEnumerator EnsureResolved(string hintUrl, Action<string> onError)
        {
            if (!string.IsNullOrEmpty(_lockedBaseUrl))
            {
                StudioAiLog.Debug("Core already locked: " + _lockedBaseUrl);
                yield break;
            }

            ParseHint(hintUrl, out var host, out var preferred);
            StudioAiLog.Debug(
                "Discover Core host=" + host +
                " preferred=" + (preferred.HasValue ? preferred.Value.ToString() : "none") +
                " range=" + PortMin + "-" + PortMax);

            string lastErr = null;

            if (preferred.HasValue)
            {
                var preferredBase = "http://" + host + ":" + preferred.Value;
                string body = null;
                yield return GetText(preferredBase + "/health/live", 3, (ok, text, err) =>
                {
                    if (ok && LooksLikeCore(text)) body = text;
                    else lastErr = SummarizeFail(err, text);
                });
                if (body != null)
                {
                    _lockedBaseUrl = preferredBase;
                    StudioAiLog.Info("Core LOCKED (preferred): " + _lockedBaseUrl);
                    yield break;
                }
            }

            for (var port = PortMin; port <= PortMax; port++)
            {
                if (preferred.HasValue && port == preferred.Value)
                    continue;

                var baseUrl = "http://" + host + ":" + port;
                string body = null;
                yield return GetText(baseUrl + "/health/live", 2, (ok, text, err) =>
                {
                    if (ok && LooksLikeCore(text)) body = text;
                    else lastErr = SummarizeFail(err, text);
                });
                if (body != null)
                {
                    _lockedBaseUrl = baseUrl;
                    StudioAiLog.Info("Core LOCKED (scan): " + _lockedBaseUrl);
                    yield break;
                }
            }

            var fail =
                "No StudioAI Core on " + host + ":" + PortMin + "-" + PortMax +
                (string.IsNullOrEmpty(lastErr) ? "" : "; last=" + lastErr);
            StudioAiLog.Error(fail);
            onError?.Invoke(fail);
        }

        public static IEnumerator GetLiveContract(Action<string> onOk, Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                var msg = "Core URL not locked";
                StudioAiLog.Error(msg);
                onErr?.Invoke(msg);
                yield break;
            }

            StudioAiLog.Debug("GET " + _lockedBaseUrl + "/health/live (contract check)");
            yield return GetText(_lockedBaseUrl + "/health/live", 5, (ok, text, err) =>
            {
                if (!ok || !LooksLikeCore(text))
                {
                    var msg = err ?? SummarizeFail("health/live failed", text);
                    StudioAiLog.Error(msg);
                    onErr?.Invoke(msg);
                    return;
                }

                var ver = ExtractContractVersion(text);
                if (string.IsNullOrEmpty(ver))
                {
                    var msg = "no contract_version in response: " + Truncate(text, 200);
                    StudioAiLog.Error(msg);
                    onErr?.Invoke(msg);
                    return;
                }

                if (!string.Equals(ver, ContractVersions.Expected, StringComparison.Ordinal))
                {
                    var msg = "contract_version mismatch: core=" + ver + ", plugin expects " + ContractVersions.Expected;
                    StudioAiLog.Error(msg);
                    onErr?.Invoke(msg);
                    return;
                }

                StudioAiLog.Debug("contract ok: " + ver + " body=" + Truncate(text, 160));
                onOk?.Invoke(ver);
            });
        }

        public static IEnumerator Search(string query, int limit, Action<SearchResponse> onOk, Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                var msg = "Core URL not locked";
                StudioAiLog.Error(msg);
                onErr?.Invoke(msg);
                yield break;
            }

            var payload = StudioAiSearchJson.BuildSearchRequest(query, limit);
            StudioAiLog.Debug("POST " + _lockedBaseUrl + "/v1/search q=" + Truncate(query, 80) + " limit=" + limit);
            yield return PostJson(_lockedBaseUrl + "/v1/search", payload, 60, (ok, text, err) =>
            {
                if (!ok)
                {
                    var msg = err ?? "search failed";
                    StudioAiLog.Error(msg);
                    onErr?.Invoke(msg);
                    return;
                }

                try
                {
                    var resp = StudioAiSearchJson.ParseSearchResponse(text ?? "");
                    var count = resp != null && resp.Hits != null ? resp.Hits.Count : 0;
                    StudioAiLog.Debug("search JSON ok, hits=" + count);
                    onOk?.Invoke(resp);
                }
                catch (Exception ex)
                {
                    StudioAiLog.Error("search JSON parse failed", ex);
                    onErr?.Invoke("search JSON: " + ex.Message);
                }
            });
        }

        public static IEnumerator IndexPaths(
            System.Collections.Generic.IList<string> paths,
            bool useJoycaption,
            bool useMerge,
            int characterId,
            Action<string> onOk,
            Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            var payload = StudioAiSearchJson.BuildIndexPathsRequest(paths, useJoycaption, useMerge, characterId);
            StudioAiLog.Info(
                "POST /v1/index/paths count=" + (paths != null ? paths.Count : 0) +
                " char=" + characterId + " joycaption=" + useJoycaption);
            // Live index: Bridge capture + JoyCaption can take minutes per pose
            yield return PostJson(_lockedBaseUrl + "/v1/index/paths", payload, 900, (ok, text, err) =>
            {
                if (!ok)
                {
                    onErr?.Invoke(err ?? "index/paths failed");
                    return;
                }

                onOk?.Invoke(text ?? "");
            });
        }

        public static IEnumerator LookupIndex(
            System.Collections.Generic.IList<string> paths,
            Action<string> onOk,
            Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            var payload = StudioAiSearchJson.BuildLookupRequest(paths);
            StudioAiLog.Info("POST /v1/index/lookup count=" + (paths != null ? paths.Count : 0));
            yield return PostJson(_lockedBaseUrl + "/v1/index/lookup", payload, 30, (ok, text, err) =>
            {
                if (!ok)
                {
                    onErr?.Invoke(err ?? "index/lookup failed");
                    return;
                }

                onOk?.Invoke(text ?? "");
            });
        }

        public static IEnumerator ClearIndex(Action<string> onOk, Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            StudioAiLog.Info("POST /v1/index/clear");
            yield return PostJson(_lockedBaseUrl + "/v1/index/clear", "{}", 30, (ok, text, err) =>
            {
                if (!ok)
                {
                    onErr?.Invoke(err ?? "index/clear failed");
                    return;
                }

                onOk?.Invoke(text ?? "");
            });
        }

        public static IEnumerator Chat(
            System.Collections.Generic.IList<StudioAiChatMessage> messages,
            string persona,
            Action<string> onOk,
            Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            var payload = StudioAiSearchJson.BuildChatRequest(messages, persona, stream: false);
            yield return PostJson(_lockedBaseUrl + "/v1/chat", payload, 180, (ok, text, err) =>
            {
                if (!ok)
                {
                    onErr?.Invoke(err ?? "chat failed");
                    return;
                }

                var content = StudioAiSearchJson.ExtractChatAssistantContent(text);
                if (string.IsNullOrEmpty(content))
                    onErr?.Invoke("empty chat response: " + Truncate(text, 200));
                else
                    onOk?.Invoke(content);
            });
        }

        public static IEnumerator FeedbackAnalyze(
            int characterId,
            string instruction,
            bool polish,
            Action<string, string> onOk,
            Action<string> onErr)
        {
            // onOk(captionOrPolish, imagePath)
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            var payload = StudioAiSearchJson.BuildFeedbackAnalyzeRequest(characterId, instruction, polish);
            yield return PostJson(_lockedBaseUrl + "/v1/scene-feedback/analyze", payload, 180, (ok, text, err) =>
            {
                if (!ok)
                {
                    onErr?.Invoke(err ?? "feedback analyze failed");
                    return;
                }

                if (text != null && text.IndexOf("\"paused\"", StringComparison.Ordinal) >= 0 &&
                    text.IndexOf("true", StringComparison.Ordinal) >= 0)
                {
                    onErr?.Invoke("feedback paused (index running)");
                    return;
                }

                var caption = StudioAiSearchJson.TryReadJsonString(text, "polish");
                if (string.IsNullOrEmpty(caption))
                    caption = StudioAiSearchJson.TryReadJsonString(text, "caption");
                var imagePath = StudioAiSearchJson.TryReadJsonString(text, "image_path");
                onOk?.Invoke(caption ?? text ?? "", imagePath);
            });
        }

        public static IEnumerator FeedbackWatchStart(int characterId, float debounceS, Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            var payload = StudioAiSearchJson.BuildFeedbackWatchStartRequest(characterId, debounceS);
            yield return PostJson(_lockedBaseUrl + "/v1/scene-feedback/watch/start", payload, 30, (ok, text, err) =>
            {
                if (!ok) onErr?.Invoke(err ?? "watch start failed");
            });
        }

        public static IEnumerator FeedbackWatchStop(Action<string> onErr)
        {
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            yield return PostJson(_lockedBaseUrl + "/v1/scene-feedback/watch/stop", "{}", 15, (ok, text, err) =>
            {
                if (!ok) onErr?.Invoke(err ?? "watch stop failed");
            });
        }

        public static IEnumerator FeedbackLatest(Action<string, string, string> onOk, Action<string> onErr)
        {
            // onOk(caption, imagePath, rawJson)
            if (string.IsNullOrEmpty(_lockedBaseUrl))
            {
                onErr?.Invoke("Core URL not locked");
                yield break;
            }

            yield return GetText(_lockedBaseUrl + "/v1/scene-feedback/latest", 10, (ok, text, err) =>
            {
                if (!ok)
                {
                    onErr?.Invoke(err ?? "latest failed");
                    return;
                }

                var caption = StudioAiSearchJson.TryReadJsonString(text, "polish");
                if (string.IsNullOrEmpty(caption))
                    caption = StudioAiSearchJson.TryReadJsonString(text, "caption");
                var imagePath = StudioAiSearchJson.TryReadJsonString(text, "image_path");
                onOk?.Invoke(caption ?? "", imagePath, text ?? "");
            });
        }

        public static bool LooksLikeCore(string text) =>
            !string.IsNullOrEmpty(text) &&
            text.IndexOf("\"contract_version\"", StringComparison.Ordinal) >= 0;

        public static string ExtractContractVersion(string json)
        {
            if (string.IsNullOrEmpty(json)) return null;
            const string key = "\"contract_version\"";
            var i = json.IndexOf(key, StringComparison.Ordinal);
            if (i < 0) return null;
            i = json.IndexOf(':', i + key.Length);
            if (i < 0) return null;
            i = json.IndexOf('"', i + 1);
            if (i < 0) return null;
            var j = json.IndexOf('"', i + 1);
            if (j < 0) return null;
            return json.Substring(i + 1, j - i - 1);
        }

        private static void ParseHint(string hint, out string host, out int? preferred)
        {
            host = "127.0.0.1";
            preferred = null;
            var raw = (hint ?? "").Trim().TrimEnd('/');
            if (string.IsNullOrEmpty(raw) ||
                string.Equals(raw, "auto", StringComparison.OrdinalIgnoreCase))
                return;
            if (!raw.Contains("://"))
                raw = "http://" + raw;
            if (!Uri.TryCreate(raw, UriKind.Absolute, out var uri))
                return;
            host = string.IsNullOrEmpty(uri.Host) ? "127.0.0.1" : uri.Host;
            if (!uri.IsDefaultPort)
                preferred = uri.Port;
        }

        private static string SummarizeFail(string err, string text)
        {
            if (!string.IsNullOrEmpty(err))
                return err + (string.IsNullOrEmpty(text) ? "" : " body=" + Truncate(text, 120));
            if (!string.IsNullOrEmpty(text))
                return "not core json: " + Truncate(text, 120);
            return "empty response";
        }

        private static string Truncate(string s, int max)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Replace("\r", " ").Replace("\n", " ");
            return s.Length <= max ? s : s.Substring(0, max) + "…";
        }

        private static IEnumerator GetText(string url, int timeoutSec, Action<bool, string, string> done)
        {
            StudioAiLog.Debug("HTTP GET " + url + " timeout=" + timeoutSec + "s");
            using (var req = UnityWebRequest.Get(url))
            {
                req.timeout = timeoutSec;
                yield return req.SendWebRequest();
                if (req.isNetworkError || req.isHttpError)
                {
                    var err = req.responseCode + " " + req.error;
                    StudioAiLog.Debug("HTTP GET fail " + url + " → " + err);
                    done(false, null, err);
                    yield break;
                }

                var text = req.downloadHandler != null ? req.downloadHandler.text : null;
                StudioAiLog.Debug(
                    "HTTP GET ok " + url + " bytes=" + (text != null ? text.Length : 0) +
                    " snippet=" + Truncate(text, 100));
                done(true, text, null);
            }
        }

        private static IEnumerator PostJson(string url, string json, int timeoutSec, Action<bool, string, string> done)
        {
            StudioAiLog.Debug("HTTP POST " + url + " timeout=" + timeoutSec + "s bodyBytes=" + (json != null ? Encoding.UTF8.GetByteCount(json) : 0));
            var bytes = Encoding.UTF8.GetBytes(json ?? "{}");
            using (var req = new UnityWebRequest(url, "POST"))
            {
                req.uploadHandler = new UploadHandlerRaw(bytes);
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                req.timeout = timeoutSec;
                yield return req.SendWebRequest();
                if (req.isNetworkError || req.isHttpError)
                {
                    var body = req.downloadHandler != null ? req.downloadHandler.text : "";
                    var err = req.responseCode + " " + req.error + " " + Truncate(body, 200);
                    StudioAiLog.Error("HTTP POST fail " + url + " → " + err);
                    done(false, null, err);
                    yield break;
                }

                var text = req.downloadHandler != null ? req.downloadHandler.text : null;
                StudioAiLog.Debug(
                    "HTTP POST ok " + url + " bytes=" + (text != null ? text.Length : 0));
                done(true, text, null);
            }
        }
    }
}
