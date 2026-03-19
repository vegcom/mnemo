# RESOURCES.md

References to external deps documentation

## Systemd

|Specifier|Expands|
|-|-|
|%n|Full unit name (`myservice@alpha.service`)|
|%p|Prefix before `@` (`myservice`)|
|%i|Instance name after `@` (`alpha`)|
|%f|Unescaped instance name|
|%u|Username for user services|
|%H|Hostname|
|%E|`$XDG_CONFIG_HOME` (user: `~/.config`)|

- <https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html>

## xAI

### Collections API

- <https://docs.x.ai/developers/rest-api-reference/collections> — overview
- <https://docs.x.ai/developers/rest-api-reference/collections/collection> — collection CRUD (management API key required)
- <https://docs.x.ai/developers/rest-api-reference/collections/search> — `POST /v1/documents/search` (standard API key)
- Upload limit: ~40 MB per file; 90-day retention on newer exports (older exports are supersets)

### xAI conversation export format

Exported from the xAI web UI. One file per conversation, JSON:

```json
{
  "conversation": {
    "id": "<uuid>",
    "title": "...",
    "create_time": "<ISO8601>",
    "modify_time": "<ISO8601>",
    "media_types": ["audio"]
  },
  "responses": [
    {
      "response": {
        "_id": "<uuid>",
        "conversation_id": "<uuid>",
        "message": "<turn text>",
        "sender": "human | assistant",
        "create_time": {
          "$date": { "$numberLong": "<epoch ms as string>" }
        },
        "xai_user_id": "<uuid>",
        "media_types": ["audio"],
        "metadata": {},
        "model": "",
        "share_link": null
      }
    }
  ]
}
```

**Key fields for upload pipeline:** `_id` (dedupe key), `conversation_id` (session grouping),
`message` (content), `sender` (human→user / assistant→agent), `create_time.$date.$numberLong` (sort key).
Strip all other fields before chunking. See [CONTINUITY_UPLOAD.md](./CONTINUITY_UPLOAD.md).

### REST API

- <https://docs.x.ai/developers/rest-api-reference/files>
- <https://docs.x.ai/developers/rest-api-reference/inference/chat>
- <https://docs.x.ai/developers/rest-api-reference/inference/voice>
- <https://docs.x.ai/developers/rest-api-reference/management/audit>
- <https://docs.x.ai/developers/tools/advanced-usage#multi-turn-conversations-with-preservation-of-agentic-state>
- <https://docs.x.ai/developers/tools/code-execution>
- <https://docs.x.ai/developers/tools/function-calling>
- <https://docs.x.ai/developers/tools/overview>
- <https://docs.x.ai/developers/tools/tool-usage-details>
- <https://docs.x.ai/developers/tools/web-search>
- <https://docs.x.ai/developers/tools/streaming-and-sync#accessing-tool-outputs> — built-in tool output opt-in via `include` (`web_search_call_output`, `x_search_call_output`, `code_execution_call_output`); MCP tool results are not exposed this way — SDK handles MCP call→result internally
- <https://docs.x.ai/developers/model-capabilities/audio/voice-agent.md>

## python modules

- <https://github.com/sparfenyuk/mcp-proxy>
- <https://github.com/Bing-su/pycloudflared>
- <https://github.com/spatialaudio/python-sounddevice>
  - <https://python-sounddevice.readthedocs.io/en/latest/>

## CF

- <https://developers.cloudflare.com/fundamentals/reference/network-ports/>
- <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-managed-tunnel/> — named tunnel setup (avoids trycloudflare rate limits; requires CF account + `cloudflared tunnel create`)
- <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/> — create named tunnel via API

## Qdrant

- <https://github.com/qdrant/mcp-server-qdrant> — official qdrant MCP server; `qdrant-store` + `qdrant-find` tools; vector semantic search + payload filtering; `QDRANT_URL` / `QDRANT_LOCAL_PATH` / `COLLECTION_NAME` env vars; supports `stdio` / `sse` / `streamable-http` transports; run via `uvx mcp-server-qdrant [--transport streamable-http]`; candidate replacement for custom `memory_mcp.py`
- <https://python-client.qdrant.tech/> — Python client docs (qdrant-client)

### Embeddings

- <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF> — conversation embedding (1024-dim); served via llama-server on papaya (k3s NodePort 30800); `PRESENCE_EMBED_URL=http://papaya:30800`
- <https://huggingface.co/sentence-transformers/msmarco-MiniLM-L12-v3> — previous conversation embedding (384-dim); replaced by Qwen3
- <https://huggingface.co/redis/langcache-embed-v3-small> — tool/cache embedding (384-dim); fine-tuned from all-MiniLM-L6-v2 for semantic deduplication; no GGUF available — needs sentence-transformers or convert-to-GGUF serving

## Desktop Commander

- <https://github.com/wonderwhy-er/DesktopCommanderMCP>
