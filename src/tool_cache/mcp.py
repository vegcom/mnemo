"""mnemo tool cache MCP server — semantic dedup/cache for tool calls.

Exposes three tools: cache_lookup, cache_store, cache_invalidate.
Runs as a stdio MCP server; wrap with mcp-proxy for HTTP.

Env vars:
  TOOL_CACHE_EMBED_URL      langcache embedding server (e.g. http://papaya:30801)
  TOOL_CACHE_EMBED_MODEL    model name (default: langcache)
  TOOL_CACHE_EMBED_DIM      dimension override (default: probe remote, fallback 384)
  TOOL_CACHE_COLLECTION     qdrant collection (default: mnemo-tool-cache)
  TOOL_CACHE_QDRANT_URL     qdrant URL (falls back to QDRANT_REMOTE_URL)
  TOOL_CACHE_THRESHOLD      default similarity threshold (default: 0.92)
"""

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("tool_cache_mcp")

_src = str(__import__("pathlib").Path(__file__).parent.parent)
if _src not in sys.path:
  sys.path.insert(0, _src)

mcp = FastMCP(
  "tool-cache",
  instructions=(
    "Semantic cache for tool calls. "
    "Call cache_lookup before executing a tool; call cache_store after to persist results."
  ),
)

_store = None


def _get_store():
  global _store
  if _store is None:
    from tool_cache.store import ToolCacheStore
    _store = ToolCacheStore()
  return _store


@mcp.tool()
def cache_lookup(tool: str, args: str, threshold: float = 0.92) -> dict:
  """Check if a semantically similar tool call has been cached.

  Args:
    tool: Tool name (e.g. 'bash', 'search_memory').
    args: Arguments as a string (JSON or natural language description).
    threshold: Similarity threshold 0-1 (default 0.92 — langcache is tuned for dedup).

  Returns:
    {"hit": true, "tool": ..., "args": ..., "result": ..., "score": ...} on hit,
    {"hit": false} on miss.
  """
  log.info("cache_lookup: tool=%r args=%r threshold=%s", tool, args[:80], threshold)
  try:
    result = _get_store().lookup(tool, args, threshold)
    if result is None:
      log.info("cache_lookup: miss")
      return {"hit": False}
    log.info("cache_lookup: hit score=%.3f", result.get("score", 0))
    return {"hit": True, **result}
  except Exception as exc:
    log.exception("cache_lookup error")
    return {"hit": False, "error": str(exc)}


@mcp.tool()
def cache_store(tool: str, args: str, result: str) -> dict:
  """Store a tool call result in the semantic cache.

  Args:
    tool: Tool name.
    args: Arguments as a string.
    result: Result to cache (summary or full output).

  Returns:
    {"stored": true} on success, {"stored": false, "error": ...} on failure.
  """
  log.info("cache_store: tool=%r args=%r", tool, args[:80])
  try:
    ok = _get_store().store(tool, args, result)
    log.info("cache_store: stored=%s", ok)
    return {"stored": ok}
  except Exception as exc:
    log.exception("cache_store error")
    return {"stored": False, "error": str(exc)}


@mcp.tool()
def cache_invalidate(point_id: str) -> dict:
  """Remove a specific entry from the cache by its qdrant point ID.

  Args:
    point_id: UUID of the cache entry to delete (from a cache_lookup hit).

  Returns:
    {"deleted": true} on success.
  """
  log.info("cache_invalidate: point_id=%r", point_id)
  try:
    ok = _get_store().invalidate(point_id)
    log.info("cache_invalidate: deleted=%s", ok)
    return {"deleted": ok}
  except Exception as exc:
    log.exception("cache_invalidate error")
    return {"deleted": False, "error": str(exc)}


def main() -> None:
  threshold = os.environ.get("TOOL_CACHE_THRESHOLD")
  if threshold:
    # pre-warm store with env threshold visible to tools at runtime
    _get_store()

  transport = os.getenv("MCP_PROXY_TRANSPORT", "stdio")
  if transport == "streamablehttp":
    port = int(os.getenv("FASTMCP_PORT", "8000"))
    host = os.getenv("FASTMCP_HOST", "127.0.0.1")
    mcp.settings.port = port
    mcp.settings.host = host
    mcp.settings.stateless_http = True
    mcp.settings.json_response = True
    log.info("starting as streamable-http (stateless) on %s:%d", host, port)
    mcp.run(transport="streamable-http")
  else:
    mcp.run()


if __name__ == "__main__":
  main()
