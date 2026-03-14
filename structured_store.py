"""
structured_store.py – Query interface for the extracted JSON data store
=======================================================================

Loads extracted_data.json (produced by extract.py) and exposes a set of
focused query methods used by the RAGWorkflow routing step.

All methods return plain dicts so callers have no dependency on any
particular ORM or DB – just JSON-serialisable Python objects.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class StructuredStore:
    """
    In-memory query layer over the extracted JSON knowledge base.

    Usage::

        store = StructuredStore(EXTRACTED_DATA_PATH)
        if store.is_available:
            decisions = store.get_all("decisions")
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict = {}
        self._load()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        else:
            self._data = {
                "schema_version": "1.0",
                "items": {
                    "decisions": [], "rules": [], "warnings": [],
                    "dependencies": [], "changes": [],
                },
            }

    def reload(self) -> None:
        """Re-read from disk (call after running extract.py)."""
        self._load()

    @property
    def is_available(self) -> bool:
        """True if the store was loaded from an existing file with at least one item."""
        items = self._data.get("items", {})
        return self._path.exists() and any(len(v) > 0 for v in items.values())

    # ── Query helpers ─────────────────────────────────────────────────────────

    @property
    def _items(self) -> dict[str, list[dict]]:
        return self._data.get("items", {})

    # ── Public API ────────────────────────────────────────────────────────────

    def get_all(self, item_type: str) -> list[dict]:
        """Return every item of a given type (decisions / rules / warnings / dependencies / changes)."""
        return list(self._items.get(item_type, []))

    def get_all_items(self) -> list[dict]:
        """Return all items across all types, each annotated with its type."""
        result: list[dict] = []
        for item_type, items in self._items.items():
            for item in items:
                result.append({"type": item_type, **item})
        return result

    def get_by_tags(self, tags: list[str]) -> list[dict]:
        """Return items (any type) whose tags overlap with the given list."""
        tags_lower = {t.lower() for t in tags}
        result: list[dict] = []
        for item_type, items in self._items.items():
            for item in items:
                item_tags = {t.lower() for t in item.get("tags", [])}
                if item_tags & tags_lower:
                    result.append({"type": item_type, **item})
        return result

    def get_recent(self, days: int = 7) -> list[dict]:
        """Return items (any type) observed within the last *days* days."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        result: list[dict] = []
        for item_type, items in self._items.items():
            for item in items:
                observed = item.get("observed_at")
                if not observed:
                    continue
                try:
                    dt = datetime.fromisoformat(observed)
                    # Make timezone-aware if naive
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt >= cutoff:
                        result.append({"type": item_type, **item})
                except ValueError:
                    pass
        return result

    def search_text(self, query: str, item_type: str | None = None) -> list[dict]:
        """Full-text substring search across all (or a specific) item type."""
        q = query.lower()
        result: list[dict] = []
        scope = {item_type: self._items[item_type]} if item_type and item_type in self._items else self._items
        for itype, items in scope.items():
            for item in items:
                text = json.dumps(item, ensure_ascii=False).lower()
                if q in text:
                    result.append({"type": itype, **item})
        return result

    def get_by_scope(self, scope: str) -> list[dict]:
        """Return rules whose scope matches the given area (ui, api, db, auth, …)."""
        scope_lower = scope.lower()
        return [
            item for item in self._items.get("rules", [])
            if scope_lower in item.get("scope", "").lower()
        ]

    def get_by_severity(self, severity: str) -> list[dict]:
        """Return warnings with the given severity (high / medium / low)."""
        return [
            item for item in self._items.get("warnings", [])
            if item.get("severity", "").lower() == severity.lower()
        ]

    # ── Metadata ──────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        return {
            "generated_at": self._data.get("generated_at"),
            "counts": {k: len(v) for k, v in self._items.items()},
        }
