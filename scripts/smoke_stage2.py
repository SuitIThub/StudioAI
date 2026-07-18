"""Stage-2 smoke against running Core (and Worker behind it)."""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="StudioAI Core Stage-2 smoke")
    parser.add_argument("--base", default="http://127.0.0.1:7200", help="Core URL")
    parser.add_argument("--persona", default="stheno")
    parser.add_argument("--chat", action="store_true", help="Run multi-turn chat")
    parser.add_argument("--structured", action="store_true", help="Run Qwen+GBNF probe")
    parser.add_argument("--offline-check", action="store_true", help="Only verify health shape")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base, timeout=180.0) as client:
        health = client.get("/health")
        health.raise_for_status()
        h = health.json()
        print("HEALTH:", json.dumps(h, indent=2, ensure_ascii=False))

        personas = client.get("/v1/personas")
        personas.raise_for_status()
        print("PERSONAS:", json.dumps(personas.json(), indent=2, ensure_ascii=False))

        if args.offline_check:
            return 0

        if not (h.get("worker") or {}).get("online"):
            print(
                "Worker offline – chat/structured will return 503. "
                "Start Heimserver worker, then re-run with --chat / --structured.",
                file=sys.stderr,
            )
            return 2

        if args.chat:
            history = [
                {"role": "user", "content": "Reply with exactly one short sentence: hello."},
            ]
            r1 = client.post(
                "/v1/chat",
                json={"messages": history, "persona": args.persona, "stream": False},
            )
            print("CHAT1 status:", r1.status_code)
            print(r1.text)
            r1.raise_for_status()
            msg1 = (r1.json().get("message") or {}).get("content", "")
            history.append({"role": "assistant", "content": msg1})
            history.append(
                {
                    "role": "user",
                    "content": "What did I ask you to say? Answer in one short sentence.",
                }
            )
            r2 = client.post(
                "/v1/chat",
                json={"messages": history, "persona": args.persona, "stream": False},
            )
            print("CHAT2 status:", r2.status_code)
            print(r2.text)
            r2.raise_for_status()

        if args.structured:
            resp = client.post(
                "/v1/structured",
                json={
                    "prompt": 'Return JSON only for {"ok": true, "message": "stage2"}\n',
                    "grammar_file": "smoke_json.gbnf",
                    "max_tokens": 64,
                    "temperature": 0.1,
                },
            )
            print("STRUCTURED status:", resp.status_code)
            print(resp.text)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                print("WARNING: JSON parse failed:", data.get("parse_error"), file=sys.stderr)
                return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
