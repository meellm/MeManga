"""Recent search queries for the Search page's chip row."""

from __future__ import annotations

from typing import List

from ._base import StateDomain


class SearchHistoryStore(StateDomain):
    """Deduplicated recent search queries, newest first."""

    __slots__ = ()

    def add(self, query: str, limit: int = 8) -> None:
        """Push a query onto the deduped recent-search list (newest first)."""
        if not query or not query.strip():
            return
        q = query.strip()
        with self._backend._locked() as data:
            history = data.get("search_history", []) or []
            # Dedupe by case-insensitive match, then prepend.
            history = [h for h in history if h.lower() != q.lower()]
            history.insert(0, q)
            data["search_history"] = history[:limit]
            self._backend._mark_dirty()

    def get_recent(self, limit: int = 8) -> List[str]:
        """Recent queries, newest first."""
        with self._backend._locked() as data:
            return list(data.get("search_history", []) or [])[:limit]

    def clear(self) -> None:
        """Forget every recent query."""
        with self._backend._locked() as data:
            data["search_history"] = []
            self._backend._mark_dirty()
