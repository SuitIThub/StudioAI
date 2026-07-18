# Connectivity review (StudioAI Plugin ↔ Core)

## Why Bridge / Timeline / CopyScript work — and our client did not

| Plugin | Direction | Stack | Notes |
|--------|-----------|--------|--------|
| **StudioPoseBridge** | Inbound server | `HttpListener` | Core is the client (httpx). Plugin never calls Core. |
| **Timeline Web** | Inbound server | `HttpListener` (+ optional TLS `TcpListener`) | Browser/remote is the client. Live updates = SSE, not WebSocket. |
| **CopyScript** | **Outbound client** | **`UnityWebRequest` + coroutines** | Same problem class as StudioAI → Core. |
| **PoseBrowser updates** | Outbound | `UnityWebRequest` | GitHub checks. |
| **StudioAI (broken path)** | Outbound | HttpClient → HttpWebRequest → raw `TcpClient` | Fought Mono instead of using Unity’s HTTP stack. |

Ghost-port ranges (Bridge 7100–7199, Core 7200–7299) are still correct for **bind after hard kills**. That was never the root failure of Probe/Search.

## Root cause of the Probe failures

1. Core **was** on `7200` and returned valid JSON (`contract_version: 0.4.0`, `status: degraded` is fine).
2. Plugin reinvented HTTP. Under Unity Mono, reads were often **truncated**.
3. UI showed `health not core json: {"status":"degraded","contract_version":"0.4.0"...` — the **truncated prefix** looked valid; full parse failed (silent catch).
4. httpx lines to `:7100` in the Core log are **Core→Bridge** side effects of `/health`, not proof the plugin finished reading the body.

## Fix (v0.6.0)

Outbound Core calls use **`UnityWebRequest`** (CopyScript pattern) on the Unity main thread via coroutines:

- Discover once on 7200–7299 using `/health/live`
- Lock URL for the process
- Search via `POST /v1/search`

`StudioAi.Contracts.StudioAiCoreClient` (raw TCP) is no longer used by the BepInEx plugin.
