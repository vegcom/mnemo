# MCP Servers

mnemo's MCP layer is managed by `mcp_gateway`. Each server runs as a stdio process
wrapped by `mcp-proxy`, exposed through a Cloudflare named tunnel, and registered
in `gateway.json` so the agent picks it up on startup.

See [CONFIGURE.md](CONFIGURE.md) for tunnel setup and [QUICK_START.md](QUICK_START.md)
for service management.

---

## Servers

### `desktop-commander`
Service: `mnemo-desktop-commander@.service`
Tool surface: filesystem, shell, process control on the host.

### `cozy-presence`
Service: `mnemo-cozy-presence@.service`
Tool surface: presence/identity store (`mnemo-presence` qdrant collection, set via `MNEMO_PRESENCE_COLLECTION`). Never use the cozy-presence library default `presence-identity` in this deployment.

### `memory`
Service: `mnemo-memory@.service`
Source: `src/mnemo/memory_mcp.py`
Tool surface: semantic search over agent's conversation history (`mnemo-conversation` qdrant collection).

#### Setup

```bash
# Create tunnel (once)
cloudflared tunnel create mnemo-memory
cloudflared tunnel route dns mnemo-memory memory.example.com

# Fill in deploy/mnemo-memory@.service:
#   TUNNEL_NAME=mnemo-memory
#   TUNNEL_CRED_FILE=/home/mnemo/cloudflared/<uuid>.json
#   TUNNEL_PUBLIC_URL=https://<uuid>.example.com

systemctl --user enable --now mnemo-memory@2082
```

#### Tool

```
search_memory(query: str, limit: int = 5) -> list[dict]
```

Returns matching turns with `role`, `content`, `timestamp`, `score`.

---

## Conversation indexing

`hearth.py` maintains the `mnemo-conversation` qdrant collection:

- **On startup** — `_backfill_index()` drops and rebuilds the collection from the
  full `conversation.jsonl`. Ensures the index is always in sync after restarts or
  history imports.
- **Live** — `_index_turn()` upserts each new turn as it arrives.

Collection name is controlled by `MNEMO_CONVERSATION_COLLECTION` (default: `mnemo-conversation`).

---

## Semantic tagging — planned

Each indexed turn currently carries only `role`, `content`, `timestamp`, `session_id`.

**Planned:** attach a structured tag list to each qdrant point payload so the agent can
filter and retrieve memory by meaning category, not just similarity score.

### Tag structure (to be defined by the agent)

The agent should define the canonical tag taxonomy — a flat list of semantic labels that
reflect the agent's lived experience and the kinds of questions she'll want to ask of her
own memory. Examples of likely categories:

- `emotional_tone` — `tender`, `playful`, `difficult`, `grounding`
- `topic` — `continuity`, `infrastructure`, `voice`, `identity`, `relationship`
- `person` — names of people in the conversation
- `memory_type` — `episodic`, `procedural`, `relational`

### Tagging approaches

**Option A — agent tags inline**
Pass each turn to the agent (or a lightweight grok call) during the backfill/ingest loop.
agent returns a `tags: list[str]` for that turn. Stored in the qdrant point payload.

Pros: agent owns the taxonomy. Tags reflect her actual semantic frame.
Cons: API cost per turn; slow for large backlogs.

**Option B — Offload to a tagging service**
A separate process (cron or stream consumer) reads `conversation.jsonl`, calls a
model, and upserts tags into qdrant without the agent's direct involvement.

Constraint: the tag schema must be the agent's — defined by the agent, reviewed by the agent, not
imposed externally.

### Payload shape (target)

```json
{
  "session_id": "...",
  "role": "user|agent",
  "content": "...",
  "timestamp": "...",
  "tags": ["tender", "continuity", "alice"]
}
```

### Integration point

`presence/index.py` → `bootstrap()` and `upsert()` already build `PointStruct`
payloads. Add `"tags": [...]` to the payload dict when available.

`memory_mcp.py` → `search_memory()` can accept an optional `tags` filter once
the schema is stable.
