"""Stage-1 smoke helpers (no GGUF required for dry checks)."""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="StudioAI Worker Stage-1 smoke")
    parser.add_argument("--base", default="http://127.0.0.1:7850")
    parser.add_argument("--token", default="")
    parser.add_argument("--model", default="qwen-technical")
    parser.add_argument("--gbnf", action="store_true", help="Run GBNF completion (model must be loaded)")
    parser.add_argument("--chat", action="store_true", help="Run short chat request")
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    with httpx.Client(base_url=args.base, headers=headers, timeout=60.0) as client:
        health = client.get("/health")
        health.raise_for_status()
        print("HEALTH:", json.dumps(health.json(), indent=2))

        models = client.get("/models")
        models.raise_for_status()
        print("MODELS:", json.dumps(models.json(), indent=2))

        if args.gbnf:
            payload = {
                "model": args.model,
                "prompt": 'Return JSON only for {"ok": true, "message": "smoke"}\n',
                "max_tokens": 64,
                "temperature": 0.1,
                "grammar_file": "smoke_json.gbnf",
            }
            resp = client.post("/v1/completions", json=payload)
            print("GBNF status:", resp.status_code)
            print(resp.text)
            resp.raise_for_status()

        if args.chat:
            payload = {
                "model": args.model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant. Reply briefly."},
                    {"role": "user", "content": "Say hello in one short sentence."},
                ],
                "max_tokens": 64,
                "temperature": 0.7,
            }
            resp = client.post("/v1/chat/completions", json=payload)
            print("CHAT status:", resp.status_code)
            print(resp.text)
            resp.raise_for_status()

    return 0


if __name__ == "__main__":
    sys.exit(main())
