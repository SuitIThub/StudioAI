using System;
using System.Collections.Generic;
using System.Net.Http;
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

    /// <summary>Thin HTTP client for StudioAI Core (Stage 5a).</summary>
    public sealed class StudioAiCoreClient : IDisposable
    {
        private readonly HttpClient _http;

        public StudioAiCoreClient(string baseUrl, float timeoutSeconds = 30f)
        {
            _http = new HttpClient
            {
                BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"),
                Timeout = TimeSpan.FromSeconds(timeoutSeconds)
            };
        }

        public async Task<CoreHealthResponse?> GetHealthAsync()
        {
            var resp = await _http.GetAsync("health").ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode) return null;
            var json = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            return JsonConvert.DeserializeObject<CoreHealthResponse>(json);
        }

        public async Task<(bool ok, string? detail)> CheckContractAsync()
        {
            var health = await GetHealthAsync().ConfigureAwait(false);
            if (health == null)
                return (false, "Core unreachable");
            var v = health.ContractVersion ?? "";
            if (!string.Equals(v, ContractVersions.Expected, StringComparison.Ordinal))
                return (false, $"contract_version mismatch: core={v}, plugin expects {ContractVersions.Expected}");
            return (true, v);
        }

        public async Task<SearchResponse?> SearchAsync(string query, int limit = 20)
        {
            var body = JsonConvert.SerializeObject(new SearchRequest { Query = query, Limit = limit });
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var resp = await _http.PostAsync("v1/search", content).ConfigureAwait(false);
            var json = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode)
                throw new HttpRequestException($"Search failed {(int)resp.StatusCode}: {json}");
            return JsonConvert.DeserializeObject<SearchResponse>(json);
        }

        public void Dispose() => _http.Dispose();
    }
}
