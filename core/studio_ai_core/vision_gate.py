"""Exclusive JoyCaption / vision GPU access for Index vs Scene-Feedback."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class VisionGate:
    """
    Serializes JoyCaption use on the main PC.

    - ``indexing`` flag: Watch must pause while an index job is in progress
      (even between individual caption calls).
    - ``hold(owner)``: exclusive lock around actual VLM inference.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: str | None = None
        self._index_depth = 0

    @property
    def owner(self) -> str | None:
        return self._owner

    @property
    def locked(self) -> bool:
        return self._lock.locked()

    @property
    def indexing(self) -> bool:
        return self._index_depth > 0

    def begin_index(self) -> None:
        self._index_depth += 1

    def end_index(self) -> None:
        self._index_depth = max(0, self._index_depth - 1)

    @asynccontextmanager
    async def hold(self, owner: str) -> AsyncIterator[None]:
        async with self._lock:
            self._owner = owner
            try:
                yield
            finally:
                self._owner = None

    def status(self) -> dict[str, object]:
        return {
            "locked": self.locked,
            "owner": self._owner,
            "indexing": self.indexing,
            "index_depth": self._index_depth,
        }
