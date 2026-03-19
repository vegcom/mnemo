# CONFIGURE.md

Edit `~/.config/environment.d/mcp-secrets.conf` (symlinked from `deploy/mcp-secrets.conf`).

---

## Core

| key | notes |
| --- | ----- |
| `XAI_API_KEY` | xAI API key |
| `APP_AUTH_TOKEN` | Bearer token for hearth IPC (`openssl rand -hex 32`) |
| `MCP_AUTH_TOKEN` | Bearer token guarding the public tunnel endpoints (`openssl rand -hex 32`) |

---

## Agent

| key | default | notes |
| --- | ------- | ----- |
| `MNEMO_HEARTH_PORT` | `7744` | TCP port hearth listens on |
| `MNEMO_HEARTH_BIND` | `127.0.0.1` | Set to `0.0.0.0` for LAN access |
| `MNEMO_HISTORY_TURNS` | `64` | Turns reloaded from JSONL on hearth startup |
| `MNEMO_GATEWAY_JSON` | `~/.config/mnemo/gateway.json` | Runtime MCP manifest path |
| `MNEMO_CONTINUITY_JSON` | `data/continuity.json` | Identity anchor injected as system message |

---

## App client

| key | default | notes |
| --- | ------- | ----- |
| `MNEMO_HEARTH_HOST` | `127.0.0.1` | Hearth daemon host (set to the host's IP for remote access) |
| `MNEMO_CLIENT_PERSON` | — | Speaker identity tag written to turn JSONL (e.g. `Alice`). Optional — omit for anonymous. Set per-client, not on the server. |

---

## Conversation store

| key | default | notes |
| --- | ------- | ----- |
| `MNEMO_CONVERSATION_JSONL` | `~/.config/mnemo/conversation.jsonl` | Append-only turn log (source of truth) |
| `MNEMO_TOOL_TURNS_JSONL` | `~/.config/mnemo/tool_turns.jsonl` | Append-only tool turn log |
| `MNEMO_RESPONSE_ID_PATH` | — | Path to persist last xAI response ID (server-side state) |

---

## Qdrant

| key | default | notes |
| --- | ------- | ----- |
| `QDRANT_REMOTE_URL` | — | e.g. `http://qdrant-host:6333`; falls back to local embedded if unset |
| `MNEMO_CONVERSATION_COLLECTION` | `mnemo-conversation` | Qdrant collection for conversation turns |
| `MNEMO_TOOL_TURNS_COLLECTION` | `mnemo-tool-turns` | Qdrant collection for tool turn history |
| `MNEMO_PRESENCE_COLLECTION` | `mnemo-presence` | Qdrant collection for relational identity (cozy-presence MCP) |
| `PRESENCE_INDEX_PATH` | `~/.config/mnemo/presence_qdrant` | Local embedded qdrant path for presence index |
| `PRESENCE_EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model for presence index |

When plugging in `qdrant/mcp-server-qdrant` per collection, map its vars using the `MNEMO_${PREFIX}` convention:

| mcp-server-qdrant var | mnemo convention |
| --- | --- |
| `QDRANT_URL` | `MNEMO_CONVERSATION_QDRANT_URL` / `MNEMO_TOOL_TURNS_QDRANT_URL` / `MNEMO_PRESENCE_QDRANT_URL` |
| `QDRANT_API_KEY` | `MNEMO_CONVERSATION_QDRANT_API_KEY` etc. |
| `QDRANT_LOCAL_PATH` | `MNEMO_CONVERSATION_QDRANT_LOCAL_PATH` etc. |
| `COLLECTION_NAME` | `MNEMO_CONVERSATION_COLLECTION` / `MNEMO_TOOL_TURNS_COLLECTION` / `MNEMO_PRESENCE_COLLECTION` |
| `EMBEDDING_PROVIDER` | `MNEMO_CONVERSATION_EMBEDDING_PROVIDER` etc. |
| `EMBEDDING_MODEL` | `MNEMO_CONVERSATION_EMBEDDING_MODEL` etc. |
| `TOOL_STORE_DESCRIPTION` | `MNEMO_CONVERSATION_QDRANT_TOOL_STORE_DESCRIPTION` etc. |
| `TOOL_FIND_DESCRIPTION` | `MNEMO_CONVERSATION_TOOL_FIND_DESCRIPTION` etc. |

---

## Tunnel

| key | default | notes |
| --- | ------- | ----- |
| `MCP_TUNNEL_BACKEND` | `cloudflare` | `cloudflare` (trycloudflare) or `named` (named tunnel) or `dns` |
| `TUNNEL_NAME` | — | Named tunnel only: tunnel name |
| `TUNNEL_CRED_FILE` | — | Named tunnel only: path to credential JSON |
| `TUNNEL_PUBLIC_URL` | — | Named tunnel only: public HTTPS URL |
| `CLOUDFLARE_API_TOKEN` | — | DNS backend only |
| `CLOUDFLARE_ACCOUNT_ID` | — | DNS backend only |
| `CLOUDFLARE_ZONE_ID` | — | DNS backend only |

---

## Presence (cozy-presence MCP service)

| key | default | notes |
| --- | ------- | ----- |
| `PRESENCE_STORE_PATH` | `~/.config/mnemo/presence.jsonl` | Cozy-presence JSONL store (source of truth) |

---

## FastMCP (qdrant/mcp-server-qdrant)

| key | notes |
| --- | ----- |
| `FASTMCP_DEBUG` | set to `true` to enable verbose FastMCP logging — useful while wiring up qdrant MCP instances |

See also: [FastMCP environment variables](https://github.com/qdrant/mcp-server-qdrant?tab=readme-ov-file#fastmcp-environment-variables) for the full list.

---

## Gateway / proxy (advanced)

| key | default | notes |
| --- | ------- | ----- |
| `MCP_LOCAL_PORT` | `8080` | Port mcp-proxy listens on |
| `MCP_MANAGE_PROXY` | `0` | Set to `1` to have the gateway spawn mcp-proxy itself |
| `MCP_PROXY_CMD` | `desktop-commander` | stdio command mcp-proxy wraps — **must be quoted in systemd `Environment=`** |
| `MCP_PROXY_TRANSPORT` | `sse` | `sse` (stdio wrap via mcp-proxy, default) or `streamablehttp` (command is a native HTTP server) |
| `MCP_PROXY_PORT` | `MCP_LOCAL_PORT + 1` | Internal mcp-proxy port when auth is active |
| `MCP_CONFIG_PATH` | `<package>/mcp.conf` | Override mcp.conf path |
| `MCP_SERVER_LABEL` | `gateway` | Label written to gateway.json when no mcp.conf found |
| `MCP_LOG_PATH` | `/tmp/mcp_gateway.log` | Set to `""` to disable file logging |
