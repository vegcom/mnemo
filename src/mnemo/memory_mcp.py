"""
mnemo memory MCP server — semantic search over conversation history.

Exposes one tool: search_memory(query, limit)
Runs as a stdio MCP server; wrap with mcp-proxy for HTTP.

Env vars (via presence.index.Index):
  QDRANT_REMOTE_URL          qdrant server URL (default: local embedded)
  MNEMO_CONVERSATION_COLLECTION  collection name (default: mnemo-conversation)
"""
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

# Ensure src/ is on path when run directly (not as installed package)
_src = str(__import__("pathlib").Path(__file__).parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("memory_mcp")

mcp = FastMCP("memory", instructions="Search conversation history semantically.")


@mcp.tool()
def search_memory(query: str, limit: int = 5) -> list[dict]:
    """Search conversation history by meaning.

    Args:
        query: Natural language query to search for.
        limit: Maximum number of results to return (default 5).

    Returns:
        List of matching turns with role, content, timestamp, and score.
    """
    log.info("search_memory called: query=%r limit=%d", query, limit)
    try:
        from presence.index import Index
        idx = Index()
        log.debug("index backend=%s remote_url=%s collection=%s count=%d",
                  idx._backend or "uninit", idx.remote_url, idx.collection, idx.count())
        results = idx.search(query, limit=limit)
        log.info("search_memory returning %d results: %s",
                 len(results),
                 [(r.get("role"), round(r.get("score", 0), 3), r.get("content", "")[:60]) for r in results])
        return results
    except Exception as exc:
        log.exception("search_memory error")
        return [{"error": str(exc)}]


def main():
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
