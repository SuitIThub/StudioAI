"""SQLite + FTS5 pose index store."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from studio_ai_core.indexing import INDEX_VERSION

# Words that break AND-queries when absent from short index text ("kneeling from behind")
_FTS_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "with",
        "by",
        "her",
        "his",
        "their",
        "a",
        "is",
        "are",
        "be",
        "as",
    }
)
_TOKEN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_\-]*")


def _fts_match_query(raw: str) -> str:
    """Build an FTS5 MATCH string: drop stopwords, AND remaining terms."""
    tokens = [t.lower() for t in _TOKEN.findall(raw or "")]
    keep = [t for t in tokens if t not in _FTS_STOP]
    if not keep:
        keep = tokens
    # Quote tokens so hyphens / underscores stay literal
    return " ".join(f'"{t}"' if any(c in t for c in "_-") else t for t in keep)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SearchHit:
    pose_id: str
    path: str | None
    description: str
    tags: list[str]
    score: float
    snippet: str


class PoseIndexStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS poses (
              pose_id TEXT PRIMARY KEY,
              path TEXT,
              description TEXT NOT NULL DEFAULT '',
              tags_json TEXT NOT NULL DEFAULT '[]',
              synonyms_json TEXT NOT NULL DEFAULT '[]',
              posecode_raw TEXT,
              posecode_text TEXT,
              posecode_tags_json TEXT NOT NULL DEFAULT '[]',
              captures_json TEXT NOT NULL DEFAULT '{}',
              captions_json TEXT NOT NULL DEFAULT '{}',
              index_version TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS poses_fts USING fts5(
              pose_id UNINDEXED,
              description,
              tags,
              synonyms,
              posecode_text,
              captions,
              tokenize = 'porter unicode61'
            );
            """
        )
        self._conn.commit()
        self._ensure_fts_captions_column()

    def _ensure_fts_captions_column(self) -> None:
        """Older DBs may lack captions in FTS; rebuild virtual table if needed."""
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='poses_fts'"
        ).fetchone()
        sql = (row["sql"] if row else "") or ""
        if "captions" in sql:
            return
        cur = self._conn.cursor()
        cur.executescript(
            """
            DROP TABLE IF EXISTS poses_fts;
            CREATE VIRTUAL TABLE poses_fts USING fts5(
              pose_id UNINDEXED,
              description,
              tags,
              synonyms,
              posecode_text,
              captions,
              tokenize = 'porter unicode61'
            );
            """
        )
        # Reindex existing rows
        for r in self._conn.execute("SELECT * FROM poses").fetchall():
            caps = json.loads(r["captions_json"] or "{}")
            caption_blob = " ".join(str(v) for v in caps.values() if v)
            cur.execute(
                """
                INSERT INTO poses_fts (
                  pose_id, description, tags, synonyms, posecode_text, captions
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    r["pose_id"],
                    r["description"] or "",
                    " ".join(json.loads(r["tags_json"] or "[]")),
                    " ".join(json.loads(r["synonyms_json"] or "[]")),
                    r["posecode_text"] or "",
                    caption_blob,
                ),
            )
        self._conn.commit()

    def upsert(
        self,
        *,
        pose_id: str,
        path: str | None,
        description: str,
        tags: list[str],
        synonyms: list[str],
        posecode_raw: str | None,
        posecode_text: str | None,
        posecode_tags: list[str],
        captures: dict[str, Any] | None = None,
        captions: dict[str, str] | None = None,
        index_version: str = INDEX_VERSION,
    ) -> None:
        now = _utc_now()
        tags_json = json.dumps(tags, ensure_ascii=False)
        synonyms_json = json.dumps(synonyms, ensure_ascii=False)
        posecode_tags_json = json.dumps(posecode_tags, ensure_ascii=False)
        captures_json = json.dumps(captures or {}, ensure_ascii=False)
        captions_json = json.dumps(captions or {}, ensure_ascii=False)

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO poses (
              pose_id, path, description, tags_json, synonyms_json,
              posecode_raw, posecode_text, posecode_tags_json,
              captures_json, captions_json, index_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pose_id) DO UPDATE SET
              path=excluded.path,
              description=excluded.description,
              tags_json=excluded.tags_json,
              synonyms_json=excluded.synonyms_json,
              posecode_raw=excluded.posecode_raw,
              posecode_text=excluded.posecode_text,
              posecode_tags_json=excluded.posecode_tags_json,
              captures_json=excluded.captures_json,
              captions_json=excluded.captions_json,
              index_version=excluded.index_version,
              updated_at=excluded.updated_at
            """,
            (
                pose_id,
                path,
                description,
                tags_json,
                synonyms_json,
                posecode_raw,
                posecode_text,
                posecode_tags_json,
                captures_json,
                captions_json,
                index_version,
                now,
                now,
            ),
        )
        cur.execute("DELETE FROM poses_fts WHERE pose_id = ?", (pose_id,))
        caption_blob = " ".join(str(v) for v in (captions or {}).values() if v)
        cur.execute(
            """
            INSERT INTO poses_fts (
              pose_id, description, tags, synonyms, posecode_text, captions
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pose_id,
                description,
                " ".join(tags),
                " ".join(synonyms),
                posecode_text or "",
                caption_blob,
            ),
        )
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM poses").fetchone()
        return int(row["c"])

    def clear_all(self) -> int:
        """Delete every pose row and FTS entries. Returns previous count."""
        before = self.count()
        self._conn.execute("DELETE FROM poses_fts")
        self._conn.execute("DELETE FROM poses")
        self._conn.commit()
        return before

    def get(self, pose_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM poses WHERE pose_id = ?", (pose_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def search(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        q = (query or "").strip()
        if not q:
            return []
        match_q = _fts_match_query(q)
        # Prefer FTS MATCH; fall back to LIKE if query has FTS syntax issues
        try:
            rows = self._conn.execute(
                """
                SELECT p.pose_id, p.path, p.description, p.tags_json,
                       bm25(poses_fts) AS score,
                       snippet(poses_fts, 1, '[', ']', '…', 12) AS snip
                FROM poses_fts
                JOIN poses p ON p.pose_id = poses_fts.pose_id
                WHERE poses_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (match_q, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{q}%"
            rows = self._conn.execute(
                """
                SELECT pose_id, path, description, tags_json, 0.0 AS score, description AS snip
                FROM poses
                WHERE description LIKE ? OR tags_json LIKE ? OR posecode_text LIKE ?
                   OR captions_json LIKE ?
                LIMIT ?
                """,
                (like, like, like, like, limit),
            ).fetchall()

        hits: list[SearchHit] = []
        for row in rows:
            tags = json.loads(row["tags_json"] or "[]")
            hits.append(
                SearchHit(
                    pose_id=row["pose_id"],
                    path=row["path"],
                    description=row["description"] or "",
                    tags=tags if isinstance(tags, list) else [],
                    score=float(row["score"] or 0),
                    snippet=row["snip"] or "",
                )
            )
        return hits

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "pose_id": row["pose_id"],
            "path": row["path"],
            "description": row["description"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "synonyms": json.loads(row["synonyms_json"] or "[]"),
            "posecode_raw": row["posecode_raw"],
            "posecode_text": row["posecode_text"],
            "posecode_tags": json.loads(row["posecode_tags_json"] or "[]"),
            "captures": json.loads(row["captures_json"] or "{}"),
            "captions": json.loads(row["captions_json"] or "{}"),
            "index_version": row["index_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
