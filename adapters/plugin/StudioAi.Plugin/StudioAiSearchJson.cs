using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using StudioAi.Contracts;

namespace StudioAi.Plugin
{
    /// <summary>
    /// Hand-rolled JSON for Core search — no Newtonsoft / JsonUtility in Unity plugin path.
    /// (HS2-Sandbox: no-jsonutility.mdc; Newtonsoft needs System.Numerics which Unity Mono lacks.)
    /// </summary>
    internal static class StudioAiSearchJson
    {
        public static string BuildSearchRequest(string query, int limit)
        {
            var sb = new StringBuilder(64 + (query?.Length ?? 0));
            sb.Append("{\"query\":\"").Append(Escape(query)).Append("\",\"limit\":")
              .Append(limit.ToString(CultureInfo.InvariantCulture)).Append('}');
            return sb.ToString();
        }

        public static SearchResponse ParseSearchResponse(string json)
        {
            var resp = new SearchResponse
            {
                Query = TryReadString(json, "query"),
                Count = TryReadInt(json, "count") ?? 0,
                Hits = new List<SearchHitDto>()
            };

            if (!TryFindArray(json, "hits", out var arrStart, out var arrEnd))
                return resp;

            var i = arrStart;
            while (i < arrEnd)
            {
                while (i < arrEnd && (json[i] == ',' || char.IsWhiteSpace(json[i])))
                    i++;
                if (i >= arrEnd || json[i] != '{')
                    break;
                if (!TryExtractObject(json, i, out var objEnd))
                    break;
                var obj = json.Substring(i, objEnd - i);
                resp.Hits.Add(new SearchHitDto
                {
                    PoseId = TryReadString(obj, "pose_id"),
                    Path = TryReadString(obj, "path"),
                    Description = TryReadString(obj, "description"),
                    Snippet = TryReadString(obj, "snippet"),
                    Score = TryReadDouble(obj, "score") ?? 0,
                    Tags = TryReadStringArray(obj, "tags")
                });
                i = objEnd;
            }

            if (resp.Count == 0 && resp.Hits.Count > 0)
                resp.Count = resp.Hits.Count;
            return resp;
        }

        public static string BuildIndexPathsRequest(
            IList<string> paths,
            bool useJoycaption,
            bool useMerge,
            int characterId)
        {
            var sb = new StringBuilder(160 + (paths != null ? paths.Count * 64 : 0));
            sb.Append("{\"paths\":[");
            if (paths != null)
            {
                for (var i = 0; i < paths.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append('"').Append(Escape(paths[i])).Append('"');
                }
            }
            sb.Append("],\"character_id\":").Append(characterId.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"use_joycaption\":").Append(useJoycaption ? "true" : "false");
            sb.Append(",\"use_merge\":").Append(useMerge ? "true" : "false");
            sb.Append(",\"allow_stub\":false}");
            return sb.ToString();
        }

        public static string BuildLookupRequest(IList<string> paths)
        {
            var sb = new StringBuilder(64 + (paths != null ? paths.Count * 64 : 0));
            sb.Append("{\"paths\":[");
            if (paths != null)
            {
                for (var i = 0; i < paths.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append('"').Append(Escape(paths[i])).Append('"');
                }
            }
            sb.Append("]}");
            return sb.ToString();
        }

        public static string BuildChatRequest(IList<StudioAiChatMessage> messages, string persona, bool stream)
        {
            var sb = new StringBuilder(256);
            sb.Append("{\"stream\":").Append(stream ? "true" : "false");
            if (!string.IsNullOrEmpty(persona))
                sb.Append(",\"persona\":\"").Append(Escape(persona)).Append('"');
            sb.Append(",\"messages\":[");
            if (messages != null)
            {
                for (var i = 0; i < messages.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    var m = messages[i];
                    sb.Append("{\"role\":\"").Append(Escape(m.Role ?? "user")).Append("\",\"content\":\"")
                      .Append(Escape(m.Content ?? "")).Append("\"}");
                }
            }
            sb.Append("]}");
            return sb.ToString();
        }

        public static string ExtractChatAssistantContent(string json)
        {
            // Prefer message.content nested object
            var msgIdx = json != null ? json.IndexOf("\"message\"", StringComparison.Ordinal) : -1;
            if (msgIdx >= 0)
            {
                var slice = json.Substring(msgIdx);
                var content = TryReadString(slice, "content");
                if (!string.IsNullOrEmpty(content))
                    return content;
            }
            return TryReadString(json, "content");
        }

        public static string BuildFeedbackAnalyzeRequest(int characterId, string instruction, bool polish)
        {
            var sb = new StringBuilder(128);
            sb.Append("{\"character_id\":").Append(characterId.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"camera_source\":\"studio_active\"");
            sb.Append(",\"polish_with_chat\":").Append(polish ? "true" : "false");
            if (!string.IsNullOrEmpty(instruction))
                sb.Append(",\"instruction\":\"").Append(Escape(instruction)).Append('"');
            sb.Append('}');
            return sb.ToString();
        }

        public static string BuildFeedbackWatchStartRequest(int characterId, float debounceS)
        {
            return "{\"character_id\":" + characterId.ToString(CultureInfo.InvariantCulture) +
                   ",\"camera_source\":\"studio_active\",\"debounce_s\":" +
                   debounceS.ToString(CultureInfo.InvariantCulture) + "}";
        }

        public static string SummarizeIndexResponse(string json)
        {
            if (string.IsNullOrEmpty(json))
                return "empty response";

            var indexed = TryReadInt(json, "indexed");
            var store = TryReadInt(json, "total_in_store");
            var ok = json.IndexOf("\"ok\":true", StringComparison.Ordinal) >= 0
                     || json.IndexOf("\"ok\": true", StringComparison.Ordinal) >= 0;

            var ids = new List<string>();
            if (TryFindArray(json, "items", out var start, out var end))
            {
                var i = start;
                while (i < end && ids.Count < 8)
                {
                    while (i < end && (json[i] == ',' || char.IsWhiteSpace(json[i])))
                        i++;
                    if (i >= end || json[i] != '{')
                        break;
                    if (!TryExtractObject(json, i, out var objEnd))
                        break;
                    var obj = json.Substring(i, objEnd - i);
                    var id = TryReadString(obj, "pose_id");
                    var src = TryReadString(obj, "source");
                    if (!string.IsNullOrEmpty(id))
                        ids.Add(string.IsNullOrEmpty(src) ? id : id + "(" + src + ")");
                    i = objEnd;
                }
            }

            var errN = 0;
            if (TryFindArray(json, "errors", out var es, out var ee) && ee > es)
            {
                // crude: count '{' in errors array
                for (var k = es; k < ee; k++)
                    if (json[k] == '{') errN++;
            }

            var sb = new StringBuilder();
            sb.Append(ok ? "OK" : "FAIL");
            sb.Append(" indexed=").Append(indexed.HasValue ? indexed.Value.ToString(CultureInfo.InvariantCulture) : "?");
            sb.Append(" store=").Append(store.HasValue ? store.Value.ToString(CultureInfo.InvariantCulture) : "?");
            if (errN > 0)
                sb.Append(" errors=").Append(errN.ToString(CultureInfo.InvariantCulture));
            if (ids.Count > 0)
                sb.Append(" ids=[").Append(string.Join(", ", ids)).Append(']');
            return sb.ToString();
        }

        public static string TryReadJsonString(string json, string key) => TryReadString(json, key);

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var sb = new StringBuilder(s.Length + 8);
            foreach (var c in s)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"': sb.Append("\\\""); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ') sb.AppendFormat(CultureInfo.InvariantCulture, "\\u{0:x4}", (int)c);
                        else sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }

        private static string TryReadString(string json, string key)
        {
            var search = "\"" + key + "\"";
            var i = json.IndexOf(search, StringComparison.Ordinal);
            if (i < 0) return null;
            var colon = json.IndexOf(':', i + search.Length);
            if (colon < 0) return null;
            var p = colon + 1;
            while (p < json.Length && char.IsWhiteSpace(json[p])) p++;
            if (p >= json.Length) return null;
            if (json[p] == 'n') return null; // null
            if (json[p] != '"') return null;
            return UnescapeQuoted(json, p, out _);
        }

        public static int? TryReadInt(string json, string key)
        {
            var raw = TryReadNumberToken(json, key);
            if (raw == null) return null;
            if (int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var v))
                return v;
            return null;
        }

        private static double? TryReadDouble(string json, string key)
        {
            var raw = TryReadNumberToken(json, key);
            if (raw == null) return null;
            if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var v))
                return v;
            return null;
        }

        private static string TryReadNumberToken(string json, string key)
        {
            var search = "\"" + key + "\"";
            var i = json.IndexOf(search, StringComparison.Ordinal);
            if (i < 0) return null;
            var colon = json.IndexOf(':', i + search.Length);
            if (colon < 0) return null;
            var p = colon + 1;
            while (p < json.Length && char.IsWhiteSpace(json[p])) p++;
            if (p >= json.Length || json[p] == 'n') return null;
            var start = p;
            while (p < json.Length && "0123456789+-.eE".IndexOf(json[p]) >= 0)
                p++;
            return p > start ? json.Substring(start, p - start) : null;
        }

        private static List<string> TryReadStringArray(string json, string key)
        {
            var list = new List<string>();
            if (!TryFindArray(json, key, out var start, out var end))
                return list;
            var i = start;
            while (i < end)
            {
                while (i < end && (json[i] == ',' || char.IsWhiteSpace(json[i])))
                    i++;
                if (i >= end) break;
                if (json[i] != '"') break;
                var s = UnescapeQuoted(json, i, out var after);
                if (s != null) list.Add(s);
                i = after;
            }
            return list;
        }

        private static bool TryFindArray(string json, string key, out int contentStart, out int contentEnd)
        {
            contentStart = 0;
            contentEnd = 0;
            var search = "\"" + key + "\"";
            var i = json.IndexOf(search, StringComparison.Ordinal);
            if (i < 0) return false;
            var colon = json.IndexOf(':', i + search.Length);
            if (colon < 0) return false;
            var p = colon + 1;
            while (p < json.Length && char.IsWhiteSpace(json[p])) p++;
            if (p >= json.Length || json[p] != '[') return false;
            var depth = 0;
            for (var j = p; j < json.Length; j++)
            {
                var c = json[j];
                if (c == '"')
                {
                    UnescapeQuoted(json, j, out var after);
                    j = after - 1;
                    continue;
                }
                if (c == '[') depth++;
                else if (c == ']')
                {
                    depth--;
                    if (depth == 0)
                    {
                        contentStart = p + 1;
                        contentEnd = j;
                        return true;
                    }
                }
            }
            return false;
        }

        private static bool TryExtractObject(string json, int openBrace, out int endExclusive)
        {
            endExclusive = openBrace;
            if (openBrace < 0 || openBrace >= json.Length || json[openBrace] != '{')
                return false;
            var depth = 0;
            for (var j = openBrace; j < json.Length; j++)
            {
                var c = json[j];
                if (c == '"')
                {
                    UnescapeQuoted(json, j, out var after);
                    j = after - 1;
                    continue;
                }
                if (c == '{') depth++;
                else if (c == '}')
                {
                    depth--;
                    if (depth == 0)
                    {
                        endExclusive = j + 1;
                        return true;
                    }
                }
            }
            return false;
        }

        private static string UnescapeQuoted(string json, int openQuote, out int indexAfterClose)
        {
            indexAfterClose = openQuote;
            if (openQuote < 0 || openQuote >= json.Length || json[openQuote] != '"')
                return null;
            var sb = new StringBuilder();
            var i = openQuote + 1;
            while (i < json.Length)
            {
                var c = json[i];
                if (c == '"')
                {
                    indexAfterClose = i + 1;
                    return sb.ToString();
                }
                if (c == '\\' && i + 1 < json.Length)
                {
                    var esc = json[i + 1];
                    switch (esc)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (i + 5 < json.Length &&
                                int.TryParse(json.Substring(i + 2, 4), NumberStyles.HexNumber,
                                    CultureInfo.InvariantCulture, out var code))
                            {
                                sb.Append((char)code);
                                i += 6;
                                continue;
                            }
                            sb.Append(esc);
                            break;
                        default: sb.Append(esc); break;
                    }
                    i += 2;
                    continue;
                }
                sb.Append(c);
                i++;
            }
            return null;
        }
    }
}
