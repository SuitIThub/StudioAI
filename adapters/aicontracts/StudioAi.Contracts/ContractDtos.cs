using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace StudioAi.Contracts
{
    /// <summary>Core contract version this client was built against (must match Core /health).</summary>
    public static class ContractVersions
    {
        public const string Expected = "0.4.0";
    }

    /// <summary>StudioAI Core listen / discover range (mirrors Python core_ports.py).</summary>
    public static class CorePorts
    {
        public const int PortMin = 7200;
        public const int PortMax = 7299;
        /// <summary>HTTP read timeout once a TCP port is open (short connect is separate).</summary>
        public const int DiscoverTimeoutMs = 5000;
        public const int TcpProbeTimeoutMs = 200;

        public static IEnumerable<int> ScanOrder(int? preferred)
        {
            var span = PortMax - PortMin + 1;
            var start = preferred.HasValue && preferred.Value >= PortMin && preferred.Value <= PortMax
                ? preferred.Value
                : PortMin;
            for (var i = 0; i < span; i++)
                yield return PortMin + ((start - PortMin + i) % span);
        }

        public static void ParseHint(string? baseUrl, out string host, out int? preferredPort)
        {
            host = "127.0.0.1";
            preferredPort = null;
            var raw = (baseUrl ?? "").Trim().TrimEnd('/');
            if (string.IsNullOrEmpty(raw) ||
                string.Equals(raw, "auto", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(raw, "discover", StringComparison.OrdinalIgnoreCase))
                return;

            if (!raw.Contains("://"))
                raw = "http://" + raw;
            if (!Uri.TryCreate(raw, UriKind.Absolute, out var uri))
                return;
            host = string.IsNullOrEmpty(uri.Host) ? "127.0.0.1" : uri.Host;
            if (!uri.IsDefaultPort)
                preferredPort = uri.Port;
        }

        public static bool IsCoreHealthJson(string json)
        {
            try
            {
                var obj = JObject.Parse(ExtractJsonObject(json));
                var token = obj["contract_version"];
                if (token == null || token.Type == JTokenType.Null)
                    return false;
                var ver = token.Type == JTokenType.String ? (string?)token : token.ToString();
                return !string.IsNullOrEmpty(ver);
            }
            catch
            {
                return false;
            }
        }

        /// <summary>Pull JSON object out of chunked/trailing HTTP debris.</summary>
        public static string ExtractJsonObject(string raw)
        {
            if (string.IsNullOrEmpty(raw))
                return "";
            var start = raw.IndexOf('{');
            var end = raw.LastIndexOf('}');
            if (start >= 0 && end > start)
                return raw.Substring(start, end - start + 1);
            return raw.Trim();
        }
    }

    public sealed class CoreHealthResponse
    {
        [JsonProperty("status")]
        public string? Status { get; set; }

        [JsonProperty("contract_version")]
        public string? ContractVersion { get; set; }

        [JsonProperty("worker")]
        public JObject? Worker { get; set; }

        [JsonProperty("bridge")]
        public JObject? Bridge { get; set; }
    }

    public sealed class SearchRequest
    {
        [JsonProperty("query")]
        public string Query { get; set; } = "";

        [JsonProperty("limit")]
        public int Limit { get; set; } = 20;
    }

    public sealed class SearchHitDto
    {
        [JsonProperty("pose_id")]
        public string? PoseId { get; set; }

        [JsonProperty("path")]
        public string? Path { get; set; }

        [JsonProperty("description")]
        public string? Description { get; set; }

        [JsonProperty("tags")]
        public List<string>? Tags { get; set; }

        [JsonProperty("score")]
        public double Score { get; set; }

        [JsonProperty("snippet")]
        public string? Snippet { get; set; }
    }

    public sealed class SearchResponse
    {
        [JsonProperty("query")]
        public string? Query { get; set; }

        [JsonProperty("count")]
        public int Count { get; set; }

        [JsonProperty("hits")]
        public List<SearchHitDto>? Hits { get; set; }
    }

    /// <summary>
    /// Thin HTTP client for StudioAI Core. Uses <see cref="HttpWebRequest"/> (Unity Mono–safe).
    /// Discovers port 7200–7299 on first use.
    /// </summary>
    public sealed class StudioAiCoreClient : IDisposable
    {
        private static readonly object DiscoverLock = new object();
        private static string? _discoveredBaseUrl;

        private readonly string _hintUrl;
        private readonly int _timeoutMs;
        private string _baseUrl;
        private bool _resolved;

        public StudioAiCoreClient(string baseUrl, float timeoutSeconds = 30f)
        {
            _hintUrl = string.IsNullOrWhiteSpace(baseUrl) ? "http://127.0.0.1:7200" : baseUrl.TrimEnd('/');
            _timeoutMs = Math.Max(1000, (int)(timeoutSeconds * 1000f));
            _baseUrl = _discoveredBaseUrl ?? _hintUrl;
            _resolved = _discoveredBaseUrl != null;
        }

        public string BaseUrl => _baseUrl;

        public static void InvalidateDiscovery()
        {
            lock (DiscoverLock)
                _discoveredBaseUrl = null;
        }

        public void EnsureResolved()
        {
            if (_resolved && _discoveredBaseUrl != null)
            {
                _baseUrl = _discoveredBaseUrl;
                return;
            }

            lock (DiscoverLock)
            {
                if (_discoveredBaseUrl != null)
                {
                    _baseUrl = _discoveredBaseUrl;
                    _resolved = true;
                    return;
                }

                _discoveredBaseUrl = DiscoverCoreBaseUrl(_hintUrl);
                _baseUrl = _discoveredBaseUrl;
                _resolved = true;
            }
        }

        public Task EnsureResolvedAsync()
        {
            EnsureResolved();
            return Task.CompletedTask;
        }

        /// <summary>
        /// One-shot discovery: walk 7200–7299 until Core /health matches, then stop.
        /// Result is cached in <see cref="_discoveredBaseUrl"/> for the process.
        /// </summary>
        public static string DiscoverCoreBaseUrl(string hintUrl)
        {
            CorePorts.ParseHint(hintUrl, out var host, out var preferred);
            var probed = 0;
            string? lastErr = null;

            if (preferred.HasValue)
            {
                var preferredBase = "http://" + host + ":" + preferred.Value;
                probed++;
                if (ProbeCoreHealth(preferredBase, CorePorts.DiscoverTimeoutMs, out lastErr) != null)
                    return preferredBase;
            }

            foreach (var port in CorePorts.ScanOrder(preferred))
            {
                if (preferred.HasValue && port == preferred.Value)
                    continue;
                if (!TcpPortOpen(host, port, CorePorts.TcpProbeTimeoutMs))
                    continue;
                probed++;
                var baseUrl = "http://" + host + ":" + port;
                if (ProbeCoreHealth(baseUrl, CorePorts.DiscoverTimeoutMs, out lastErr) != null)
                    return baseUrl;
            }

            throw new Exception(
                "No StudioAI Core on " + host + ":" + CorePorts.PortMin + "-" + CorePorts.PortMax +
                " (HTTP probes=" + probed + ")" +
                (string.IsNullOrEmpty(lastErr) ? "" : "; last=" + lastErr));
        }

        private static bool TcpPortOpen(string host, int port, int timeoutMs)
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var ar = client.BeginConnect(host, port, null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(timeoutMs))
                        return false;
                    client.EndConnect(ar);
                    return client.Connected;
                }
            }
            catch
            {
                return false;
            }
        }

        private static string? ProbeCoreHealth(string baseUrl, int timeoutMs, out string? error)
        {
            error = null;
            try
            {
                var json = HttpGetString(baseUrl.TrimEnd('/') + "/health/live", timeoutMs);
                if (CorePorts.IsCoreHealthJson(json))
                    return json;
                error = "live not core json: " + Truncate(json, 80);
            }
            catch (Exception ex)
            {
                error = "live: " + ex.GetType().Name + " " + ex.Message;
            }

            try
            {
                var json = HttpGetString(baseUrl.TrimEnd('/') + "/health", timeoutMs);
                if (CorePorts.IsCoreHealthJson(json))
                    return json;
                error = "health not core json: " + Truncate(json, 80);
                return null;
            }
            catch (Exception ex)
            {
                error = "health: " + ex.GetType().Name + " " + ex.Message;
                return null;
            }
        }

        private static string Truncate(string? s, int n)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Replace("\r", " ").Replace("\n", " ");
            return s.Length <= n ? s : s.Substring(0, n) + "…";
        }

        public CoreHealthResponse? GetHealth()
        {
            EnsureResolved();
            try
            {
                var live = HttpGetString(_baseUrl.TrimEnd('/') + "/health/live", Math.Min(_timeoutMs, 5000));
                var parsed = JsonConvert.DeserializeObject<CoreHealthResponse>(live);
                if (parsed != null && !string.IsNullOrEmpty(parsed.ContractVersion))
                    return parsed;
            }
            catch
            {
                // fall through
            }

            var json = HttpGetString(_baseUrl.TrimEnd('/') + "/health", _timeoutMs);
            return JsonConvert.DeserializeObject<CoreHealthResponse>(json);
        }

        public Task<CoreHealthResponse?> GetHealthAsync() => Task.FromResult(GetHealth());

        public string? CheckContract(out string detail)
        {
            detail = "";
            try
            {
                EnsureResolved();
            }
            catch (Exception ex)
            {
                detail = ex.Message;
                return detail;
            }

            try
            {
                var health = GetHealth();
                if (health == null)
                {
                    detail = "Core unreachable";
                    return detail;
                }

                var v = health.ContractVersion ?? "";
                if (!string.Equals(v, ContractVersions.Expected, StringComparison.Ordinal))
                {
                    detail = "contract_version mismatch: core=" + v + ", plugin expects " + ContractVersions.Expected;
                    return detail;
                }

                detail = v;
                return null;
            }
            catch (Exception ex)
            {
                detail = ex.Message;
                return detail;
            }
        }

        public Task<ContractCheckResult> CheckContractAsync()
        {
            var err = CheckContract(out var detail);
            return Task.FromResult(new ContractCheckResult
            {
                Ok = err == null,
                Detail = detail
            });
        }

        public SearchResponse? Search(string query, int limit = 20)
        {
            EnsureResolved();
            var body = JsonConvert.SerializeObject(new SearchRequest { Query = query, Limit = limit });
            var json = HttpPostJson(_baseUrl.TrimEnd('/') + "/v1/search", body, _timeoutMs);
            return JsonConvert.DeserializeObject<SearchResponse>(json);
        }

        public Task<SearchResponse?> SearchAsync(string query, int limit = 20) =>
            Task.FromResult(Search(query, limit));

        /// <summary>
        /// Unity Mono-safe HTTP via raw TCP. HttpWebRequest often never reaches loopback from BepInEx.
        /// </summary>
        private static string HttpGetString(string url, int timeoutMs)
        {
            var uri = new Uri(url);
            var body = RawHttp(uri, "GET", null, null, timeoutMs, out var status);
            if (status < 200 || status >= 300)
                throw new Exception("HTTP " + status + " from " + url);
            return body;
        }

        private static string HttpPostJson(string url, string jsonBody, int timeoutMs)
        {
            var uri = new Uri(url);
            var body = RawHttp(uri, "POST", jsonBody, "application/json; charset=utf-8", timeoutMs, out var status);
            if (status < 200 || status >= 300)
                throw new Exception("Search failed " + status + ": " + Truncate(body, 200));
            return body;
        }

        private static string RawHttp(
            Uri uri,
            string method,
            string? body,
            string? contentType,
            int timeoutMs,
            out int statusCode)
        {
            statusCode = 0;
            var host = uri.Host;
            var port = uri.IsDefaultPort ? 80 : uri.Port;
            var path = string.IsNullOrEmpty(uri.PathAndQuery) ? "/" : uri.PathAndQuery;
            var bodyBytes = body != null ? Encoding.UTF8.GetBytes(body) : null;

            using (var client = new TcpClient())
            {
                var ar = client.BeginConnect(host, port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs))
                    throw new TimeoutException("TCP connect timeout " + host + ":" + port);
                client.EndConnect(ar);
                client.NoDelay = true;
                client.ReceiveTimeout = timeoutMs;
                client.SendTimeout = timeoutMs;

                using (var stream = client.GetStream())
                {
                    var header = new StringBuilder();
                    // HTTP/1.0 → usually Content-Length, avoids chunked bodies from uvicorn
                    header.Append(method).Append(' ').Append(path).Append(" HTTP/1.0\r\n");
                    header.Append("Host: ").Append(host).Append(':').Append(port).Append("\r\n");
                    header.Append("Connection: close\r\n");
                    header.Append("Accept: application/json\r\n");
                    if (bodyBytes != null)
                    {
                        header.Append("Content-Type: ").Append(contentType ?? "application/octet-stream").Append("\r\n");
                        header.Append("Content-Length: ").Append(bodyBytes.Length).Append("\r\n");
                    }

                    header.Append("\r\n");
                    var headerBytes = Encoding.ASCII.GetBytes(header.ToString());
                    stream.Write(headerBytes, 0, headerBytes.Length);
                    if (bodyBytes != null)
                        stream.Write(bodyBytes, 0, bodyBytes.Length);
                    stream.Flush();

                    using (var ms = new MemoryStream())
                    {
                        var buf = new byte[8192];
                        int n;
                        while ((n = stream.Read(buf, 0, buf.Length)) > 0)
                            ms.Write(buf, 0, n);

                        var raw = Encoding.UTF8.GetString(ms.ToArray());
                        var sep = raw.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                        var sepLen = 4;
                        if (sep < 0)
                        {
                            sep = raw.IndexOf("\n\n", StringComparison.Ordinal);
                            sepLen = 2;
                        }

                        if (sep < 0)
                            throw new Exception("Malformed HTTP response");

                        var head = raw.Substring(0, sep);
                        var respBody = raw.Substring(sep + sepLen);
                        if (head.IndexOf("Transfer-Encoding: chunked", StringComparison.OrdinalIgnoreCase) >= 0)
                            respBody = DecodeChunkedBody(respBody);

                        var firstLine = head.Split('\n')[0].Trim();
                        var parts = firstLine.Split(' ');
                        if (parts.Length >= 2 && int.TryParse(parts[1], out var code))
                            statusCode = code;
                        return CorePorts.ExtractJsonObject(respBody);
                    }
                }
            }
        }

        private static string DecodeChunkedBody(string body)
        {
            var sb = new StringBuilder();
            var i = 0;
            while (i < body.Length)
            {
                var lineEnd = body.IndexOf("\r\n", i, StringComparison.Ordinal);
                var lineSep = 2;
                if (lineEnd < 0)
                {
                    lineEnd = body.IndexOf('\n', i);
                    lineSep = 1;
                }

                if (lineEnd < 0)
                    break;

                var sizeLine = body.Substring(i, lineEnd - i).Trim();
                var semi = sizeLine.IndexOf(';');
                if (semi >= 0)
                    sizeLine = sizeLine.Substring(0, semi).Trim();
                if (!int.TryParse(sizeLine, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var size))
                    break;
                if (size == 0)
                    break;

                i = lineEnd + lineSep;
                if (i + size > body.Length)
                {
                    sb.Append(body.Substring(i));
                    break;
                }

                sb.Append(body, i, size);
                i += size;
                if (i + 1 < body.Length && body[i] == '\r' && body[i + 1] == '\n')
                    i += 2;
                else if (i < body.Length && body[i] == '\n')
                    i += 1;
            }

            return sb.Length > 0 ? sb.ToString() : body;
        }

        public void Dispose()
        {
        }
    }

    public sealed class ContractCheckResult
    {
        public bool Ok { get; set; }
        public string Detail { get; set; } = "";
    }
}
