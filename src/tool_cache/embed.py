"""Embeddings for tool cache — remote-only, uses langcache endpoint.

Env vars:
  TOOL_CACHE_EMBED_URL    OpenAI-compatible /v1/embeddings base URL (required)
  TOOL_CACHE_EMBED_MODEL  model name sent in request (default: langcache)
  TOOL_CACHE_EMBED_DIM    explicit dimension override (default: probe remote)
"""

import json
import os
import urllib.request

_dim: int | None = None


def available() -> bool:
  return bool(os.environ.get("TOOL_CACHE_EMBED_URL"))


def embed_text(text: str) -> list[float] | None:
  url = os.environ.get("TOOL_CACHE_EMBED_URL")
  if not url:
    return None
  model = os.environ.get("TOOL_CACHE_EMBED_MODEL", "langcache")
  payload = json.dumps({"model": model, "input": [text]}).encode()
  req = urllib.request.Request(
    f"{url.rstrip('/')}/v1/embeddings",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
  )
  try:
    with urllib.request.urlopen(req, timeout=10) as resp:
      return json.loads(resp.read())["data"][0]["embedding"]
  except Exception:
    return None


def dimension() -> int:
  global _dim
  if explicit := os.environ.get("TOOL_CACHE_EMBED_DIM"):
    return int(explicit)
  if _dim is None:
    vec = embed_text("probe")
    _dim = len(vec) if vec else 384
  return _dim
