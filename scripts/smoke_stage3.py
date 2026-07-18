"""Stage-3 smoke: offline batch + FTS (JoyCaption/Bridge optional).

Typical FTS acceptance (fixtures already generated + indexed)::

    python scripts/smoke_stage3.py --generate 0 --skip-batch

Full offline re-index without Qwen::

    python scripts/smoke_stage3.py --generate 0 --no-merge

With Qwen merge (Heimserver must stay responsive for ~120 calls)::

    python scripts/smoke_stage3.py --generate 0
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", default=str(ROOT / "testdata" / "batch_poses"))
    parser.add_argument(
        "--generate",
        type=int,
        default=120,
        help="Generate N fixtures first (0=skip)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Skip Qwen merge (offline fallback; recommended for FTS smoke)",
    )
    parser.add_argument(
        "--skip-batch",
        action="store_true",
        help="Do not re-run batch; only run FTS queries against the existing store",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    fixtures = Path(args.fixtures)
    py = sys.executable

    if args.generate > 0:
        subprocess.check_call(
            [
                py,
                str(ROOT / "scripts" / "generate_batch_fixtures.py"),
                "--out",
                str(fixtures),
                "--count",
                str(args.generate),
            ],
            cwd=str(ROOT),
        )

    if not args.skip_batch:
        batch_cmd = [py, "-m", "studio_ai_core.cli_index", "batch", str(fixtures)]
        if args.no_merge:
            batch_cmd.append("--no-merge")
        if args.limit:
            batch_cmd.extend(["--limit", str(args.limit)])
        print("RUN:", " ".join(batch_cmd))
        if not args.no_merge:
            print(
                "NOTE: merge calls Qwen once per pose; 120× can timeout the Worker. "
                "Prefer --no-merge for FTS smoke, or --skip-batch if already indexed."
            )
        subprocess.check_call(batch_cmd, cwd=str(ROOT))
    else:
        print("SKIP batch (using existing index store)")

    queries_path = fixtures / "fts_queries.json"
    if not queries_path.is_file():
        print(f"Missing {queries_path}; generate fixtures first.", file=sys.stderr)
        return 2

    meta = json.loads(queries_path.read_text(encoding="utf-8"))
    # Prefer the extra fixed queries at the end
    queries = [q for q in meta["queries"] if " " in q["query"]][-12:]
    ok = 0
    fail = 0
    for item in queries:
        q = item["query"]
        proc = subprocess.run(
            [py, "-m", "studio_ai_core.cli_index", "search", q, "--limit", "5"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        out = proc.stdout + proc.stderr
        needle = item.get("expect_contains", "")
        if "hits=0" in out:
            hit = False
        elif needle.lower() in out.lower():
            hit = True
        else:
            hit = " 1." in out or " 1 " in out
        status = "OK" if hit else "FAIL"
        if hit:
            ok += 1
        else:
            fail += 1
        print(f"[{status}] {q!r}  expect~{needle!r}")
        if not hit:
            print(out[:400])

    print(f"FTS: {ok} ok / {fail} fail (of {len(queries)})")
    return 0 if fail == 0 and ok >= 10 else 2


if __name__ == "__main__":
    raise SystemExit(main())
