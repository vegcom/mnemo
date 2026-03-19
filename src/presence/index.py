"""Qdrant index — read-optimised semantic search over conversation turns.

Not the source of truth. Rebuild from JSONL if it dies.
Local-first: QdrantClient(path=...), no server needed.
Remote optional via PRESENCE_QDRANT_URL env var.
"""

import logging
import os
import uuid
from pathlib import Path

from . import embed

log = logging.getLogger(__name__)

_qdrant_available = None


def _check_qdrant() -> bool:
    global _qdrant_available
    if _qdrant_available is None:
        try:
            from qdrant_client import QdrantClient  # noqa: F401
            _qdrant_available = True
        except ImportError:
            _qdrant_available = False
    return _qdrant_available


class Index:
    """Qdrant-backed semantic index over conversation turns."""

    def __init__(
        self,
        local_path: Path | str | None = None,
        remote_url: str | None = None,
    ):
        # MNEMO_CONVERSATION_COLLECTION is intentionally separate from MNEMO_PRESENCE_COLLECTION
        # (which belongs to cozy-presence). Never share a collection with cozy-presence.
        self.collection = os.environ.get("MNEMO_CONVERSATION_COLLECTION", "mnemo-conversation")
        self.local_path = Path(
            local_path
            or os.environ.get("MNEMO_PRESENCE_INDEX_PATH")
            or Path.home() / ".config" / "mnemo" / "presence_qdrant"
        )
        # PRESENCE_QDRANT_URL → QDRANT_REMOTE_URL (global salt-provisioned) → local embedded
        self.remote_url = (
            remote_url
            or os.environ.get("PRESENCE_QDRANT_URL")
            or os.environ.get("QDRANT_REMOTE_URL")
        )
        self._client = None
        self._backend: str = "unknown"

    @property
    def available(self) -> bool:
        return _check_qdrant() and embed.available()

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not _check_qdrant():
            return None
        from qdrant_client import QdrantClient
        if self.remote_url:
            try:
                self._client = QdrantClient(url=self.remote_url)
                self._backend = "remote"
                log.info("qdrant backend: remote %s", self.remote_url)
                return self._client
            except Exception as exc:
                log.warning("qdrant remote %s failed (%s) — falling back to local", self.remote_url, exc)
        self.local_path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(self.local_path))
        self._backend = "local"
        log.info("qdrant backend: local %s", self.local_path)
        return self._client

    def _ensure_collection(self, client) -> None:
        from qdrant_client.models import Distance, VectorParams
        names = [c.name for c in client.get_collections().collections]
        if self.collection not in names:
            client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=embed.dimension(), distance=Distance.COSINE),
            )

    def upsert(self, turn: dict) -> bool:
        """Index a single conversation turn. Returns True on success."""
        client = self._get_client()
        if client is None or not embed.available():
            return False

        text = turn.get("content", "")
        if not text:
            return False

        vector = embed.embed_text(text)
        if vector is None:
            return False

        self._ensure_collection(client)

        from qdrant_client.models import PointStruct
        client.upsert(
            collection_name=self.collection,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "session_id": turn.get("session_id", ""),
                    "role": turn.get("role", ""),
                    "content": turn.get("content", ""),
                    "timestamp": turn.get("timestamp", ""),
                },
            )],
        )
        return True

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Semantic + keyword search. Runs vector and text-filter queries in parallel,
        merges by timestamp, deduplicates. Keyword path rescues short/unique terms
        (e.g. 'zutto') that score poorly with vector search alone."""
        client = self._get_client()
        if client is None:
            return []

        def _fmt(hit, score: float) -> dict:
            return {
                "session_id": hit.payload.get("session_id", ""),
                "role": hit.payload.get("role", ""),
                "content": hit.payload.get("content", ""),
                "timestamp": hit.payload.get("timestamp", ""),
                "score": score,
            }

        seen: set[str] = set()
        merged: list[dict] = []

        # --- keyword filter path (always runs, no embed needed) ---
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchText
            kw = client.scroll(
                collection_name=self.collection,
                scroll_filter=Filter(must=[FieldCondition(
                    key="content", match=MatchText(text=query),
                )]),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            for hit in kw[0]:
                key = hit.payload.get("timestamp", "") + hit.payload.get("content", "")
                if key not in seen:
                    seen.add(key)
                    merged.append(_fmt(hit, 1.0))
        except Exception:
            log.debug("keyword filter path failed", exc_info=True)

        # --- vector path ---
        if embed.available():
            vector = embed.embed_text(query)
            if vector is not None:
                try:
                    results = client.query_points(
                        collection_name=self.collection,
                        query=vector,
                        limit=limit,
                    )
                    for hit in results.points:
                        key = hit.payload.get("timestamp", "") + hit.payload.get("content", "")
                        if key not in seen:
                            seen.add(key)
                            merged.append(_fmt(hit, hit.score))
                except Exception:
                    log.debug("vector search path failed", exc_info=True)

        # sort keyword hits first (score=1.0), then vector by score desc
        merged.sort(key=lambda r: r["score"], reverse=True)
        return merged[:limit]

    def bootstrap(self, turns: list[dict]) -> int:
        """Rebuild index from a list of turn dicts. Drops and recreates the collection.
        Returns number indexed."""
        client = self._get_client()
        if client is None or not embed.available():
            return 0

        # Drop existing collection so rebuild is idempotent and collision-free.
        names = [c.name for c in client.get_collections().collections]
        if self.collection in names:
            client.delete_collection(self.collection)
        self._ensure_collection(client)

        from qdrant_client.models import PointStruct

        points = []
        for turn in turns:
            text = turn.get("content", "")
            if not text:
                continue
            vector = embed.embed_text(text)
            if vector is None:
                continue
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "session_id": turn.get("session_id", ""),
                    "role": turn.get("role", ""),
                    "content": turn.get("content", ""),
                    "timestamp": turn.get("timestamp", ""),
                },
            ))

        batch_size = 100
        for i in range(0, len(points), batch_size):
            client.upsert(collection_name=self.collection, points=points[i:i + batch_size])

        return len(points)

    def count(self) -> int:
        client = self._get_client()
        if client is None:
            return 0
        try:
            return client.get_collection(self.collection).points_count or 0
        except Exception:
            return 0
