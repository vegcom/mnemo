"""Qdrant-backed semantic tool call cache.

Env vars:
  TOOL_CACHE_COLLECTION   qdrant collection name (default: mnemo-tool-cache)
  TOOL_CACHE_QDRANT_URL   qdrant server URL (falls back to QDRANT_REMOTE_URL)
  TOOL_CACHE_THRESHOLD    default similarity threshold (default: 0.92)
"""

import os
import uuid
from datetime import UTC, datetime

_qdrant_available: bool | None = None


def _check_qdrant() -> bool:
  global _qdrant_available
  if _qdrant_available is None:
    try:
      from qdrant_client import QdrantClient  # noqa: F401
      _qdrant_available = True
    except ImportError:
      _qdrant_available = False
  return _qdrant_available


class ToolCacheStore:
  DEFAULT_THRESHOLD = 0.92

  def __init__(self) -> None:
    self.collection = os.environ.get("TOOL_CACHE_COLLECTION", "mnemo-tool-cache")
    self.remote_url = (
      os.environ.get("TOOL_CACHE_QDRANT_URL")
      or os.environ.get("QDRANT_REMOTE_URL")
    )
    self._client = None

  @property
  def available(self) -> bool:
    from . import embed
    return _check_qdrant() and embed.available()

  def _get_client(self):
    if self._client is not None:
      return self._client
    if not _check_qdrant() or not self.remote_url:
      return None
    from qdrant_client import QdrantClient
    try:
      self._client = QdrantClient(url=self.remote_url)
      return self._client
    except Exception:
      return None

  def _ensure_collection(self, client) -> None:
    from qdrant_client.models import Distance, VectorParams
    from . import embed
    names = [c.name for c in client.get_collections().collections]
    if self.collection not in names:
      client.create_collection(
        collection_name=self.collection,
        vectors_config=VectorParams(size=embed.dimension(), distance=Distance.COSINE),
      )

  def lookup(
    self,
    tool: str,
    args: str,
    threshold: float = DEFAULT_THRESHOLD,
  ) -> dict | None:
    """Return the best cached hit above threshold, or None."""
    from . import embed
    client = self._get_client()
    if client is None or not embed.available():
      return None

    vector = embed.embed_text(f"{tool}: {args}")
    if vector is None:
      return None

    try:
      results = client.query_points(
        collection_name=self.collection,
        query=vector,
        limit=1,
        score_threshold=threshold,
      )
    except Exception:
      return None

    if not results.points:
      return None

    hit = results.points[0]
    return {
      "id": str(hit.id),
      "tool": hit.payload.get("tool", ""),
      "args": hit.payload.get("args", ""),
      "result": hit.payload.get("result", ""),
      "timestamp": hit.payload.get("timestamp", ""),
      "score": hit.score,
    }

  def store(self, tool: str, args: str, result: str) -> bool:
    """Embed and store a tool call result. Returns True on success."""
    from . import embed
    client = self._get_client()
    if client is None or not embed.available():
      return False

    vector = embed.embed_text(f"{tool}: {args}")
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
          "tool": tool,
          "args": args,
          "result": result,
          "timestamp": datetime.now(UTC).isoformat(),
        },
      )],
    )
    return True

  def invalidate(self, point_id: str) -> bool:
    """Delete a cached entry by ID. Returns True on success."""
    client = self._get_client()
    if client is None:
      return False
    try:
      from qdrant_client.models import PointIdsList
      client.delete(
        collection_name=self.collection,
        points_selector=PointIdsList(points=[point_id]),
      )
      return True
    except Exception:
      return False
