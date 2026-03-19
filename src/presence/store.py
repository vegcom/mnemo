"""JSONL conversation store — source of truth for conversation history.

Each line is one turn:
  {"type": "turn", "session_id": "...", "role": "user|assistant",
   "content": "...", "timestamp": "..."}

The qdrant Index is a derived view. If it dies, rebuild from this file.
"""

import json
import os
import uuid
from datetime import datetime, UTC
from pathlib import Path

from .index import Index

_STORE_DEFAULT = Path.home() / ".config" / "mnemo" / "presence.jsonl"
_INDEX_DEFAULT = Path.home() / ".config" / "mnemo" / "presence_qdrant"


class PresenceStore:
    """Append-only JSONL chat log with qdrant semantic search.

    Parameters
    ----------
    path:
        Where to write the JSONL log.
        Default: MNEMO_PRESENCE_STORE_PATH env var, then ~/.config/mnemo/presence.jsonl
    session_id:
        Identifier for this conversation session.
        Auto-generated (UUID4) if not provided.
    qdrant_path:
        Local qdrant storage dir (used when no remote qdrant is configured).
        Default: MNEMO_PRESENCE_INDEX_PATH env var, then ~/.config/mnemo/presence_qdrant/
    """

    def __init__(
        self,
        path: Path | str | None = None,
        session_id: str | None = None,
        qdrant_path: Path | str | None = None,
    ):
        if path is None:
            env = os.environ.get("MNEMO_PRESENCE_STORE_PATH", "")
            path = Path(env) if env else _STORE_DEFAULT
        self.path = Path(path)
        self.session_id = session_id or str(uuid.uuid4())

        if qdrant_path is None:
            env = os.environ.get("MNEMO_PRESENCE_INDEX_PATH", "")
            qdrant_path = Path(env) if env else _INDEX_DEFAULT
        self._index = Index(local_path=qdrant_path)

    def append(self, role: str, content: str) -> dict:
        """Append a conversation turn, index it, and return the record."""
        record = {
            "type": "turn",
            "session_id": self.session_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        self._index.upsert(record)
        return record

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Semantic search over all stored turns.

        Falls back to substring search if qdrant/sentence-transformers
        are unavailable.
        """
        results = self._index.search(query, limit=limit)
        if results:
            return results
        return self._fallback_search(query, limit)

    def _fallback_search(self, query: str, limit: int) -> list[dict]:
        """Substring search over the JSONL file when qdrant is unavailable."""
        if not self.path.exists():
            return []
        q = query.lower()
        hits = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if q in rec.get("content", "").lower():
                        hits.append(rec)
                except json.JSONDecodeError:
                    continue
        return hits[-limit:]

    def recent(self, n: int = 20) -> list[dict]:
        """Return the last n turns from the log."""
        if not self.path.exists():
            return []
        turns = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("type") == "turn":
                        turns.append(rec)
                except json.JSONDecodeError:
                    continue
        return turns[-n:]

    def rebuild_index(self) -> int:
        """Rebuild qdrant index from the JSONL file. Returns turns indexed."""
        if not self.path.exists():
            return 0
        turns = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("type") == "turn":
                        turns.append(rec)
                except json.JSONDecodeError:
                    continue
        return self._index.bootstrap(turns)
