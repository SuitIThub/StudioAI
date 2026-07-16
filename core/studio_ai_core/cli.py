"""Interactive CLI chat against StudioAI Core."""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def _print_help() -> None:
    print(
        "Commands:\n"
        "  /persona <id>   switch persona (stheno|satyr)\n"
        "  /personas       list personas\n"
        "  /health         show core + worker health\n"
        "  /structured     run GBNF JSON smoke via Core\n"
        "  /quit           exit\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StudioAI Core chat CLI (Stage 2)")
    parser.add_argument("--base", default="http://127.0.0.1:7860", help="Core base URL")
    parser.add_argument("--persona", default="stheno")
    parser.add_argument("--no-stream", action="store_true")
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    persona = args.persona
    history: list[dict[str, str]] = []

    print(f"StudioAI chat → {base}  persona={persona}")
    print("Type /help for commands.\n")

    with httpx.Client(base_url=base, timeout=180.0) as client:
        try:
            health = client.get("/health")
            health.raise_for_status()
            h = health.json()
            online = (h.get("worker") or {}).get("online")
            print(f"Core status={h.get('status')}  worker_online={online}")
            if not online:
                print("WARNING: Worker offline – chat will fail until Heimserver is up.")
            print()
        except httpx.HTTPError as exc:
            print(f"ERROR: Core unreachable at {base}: {exc}", file=sys.stderr)
            return 1

        while True:
            try:
                line = input(f"[{persona}] you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/help":
                _print_help()
                continue
            if line == "/personas":
                resp = client.get("/v1/personas")
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
                continue
            if line == "/health":
                resp = client.get("/health")
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
                continue
            if line.startswith("/persona"):
                parts = line.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: /persona <stheno|satyr>")
                    continue
                persona = parts[1].strip()
                history.clear()
                print(f"Switched to persona '{persona}' (history cleared).")
                continue
            if line == "/structured":
                payload = {
                    "prompt": 'Return JSON only for {"ok": true, "message": "stage2"}\n',
                    "grammar_file": "smoke_json.gbnf",
                    "max_tokens": 64,
                    "temperature": 0.1,
                }
                resp = client.post("/v1/structured", json=payload)
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
                continue

            history.append({"role": "user", "content": line})
            payload = {
                "messages": history,
                "persona": persona,
                "stream": not args.no_stream,
            }

            try:
                if args.no_stream:
                    resp = client.post("/v1/chat", json=payload)
                    if resp.status_code == 503:
                        print("OFFLINE:", resp.json())
                        history.pop()
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    content = (data.get("message") or {}).get("content", "")
                    print(f"[{persona}] bot> {content}\n")
                    history.append({"role": "assistant", "content": content})
                else:
                    content_parts: list[str] = []
                    print(f"[{persona}] bot> ", end="", flush=True)
                    with client.stream("POST", "/v1/chat", json=payload) as resp:
                        if resp.status_code == 503:
                            print("\nOFFLINE:", resp.read().decode())
                            history.pop()
                            continue
                        if resp.status_code >= 400:
                            print("\nERROR:", resp.read().decode())
                            history.pop()
                            continue
                        for raw in resp.iter_lines():
                            if not raw or not raw.startswith("data:"):
                                continue
                            data_str = raw[5:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                obj = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            if obj.get("type") == "error":
                                print(f"\nERROR [{obj.get('code')}]: {obj.get('message')}")
                                content_parts.clear()
                                break
                            if obj.get("type") == "meta":
                                continue
                            # OpenAI chunk
                            choices = obj.get("choices") or []
                            if choices:
                                delta = choices[0].get("delta") or {}
                                piece = delta.get("content") or ""
                                if piece:
                                    content_parts.append(piece)
                                    print(piece, end="", flush=True)
                    print("\n")
                    content = "".join(content_parts)
                    if content:
                        history.append({"role": "assistant", "content": content})
                    else:
                        history.pop()
            except httpx.HTTPError as exc:
                print(f"Request failed: {exc}")
                if history and history[-1]["role"] == "user":
                    history.pop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
