# TODO.md

## Future

- [ ] Graceful missing-config messages — when optional env vars / files are absent (continuity.json,
  MNEMO_CONTINUITY_COLLECTION, gateway.json, etc.), emit a clear `log.info` / startup hint rather
  than silent skip. xAI sandbox can compute missing values on the agent side anyway.

- [ ] HearthClient daemon decouple — persistent client process; app connects to it instead of
  directly to hearth server; enables voice session lifetime across app restarts and multi-device
  audio capture. See `docs/DESIGN.md`.
- [ ] Presence daemon: ambient event inbox (audio sources, sensors, notifications) — user opts
  in/out of sources; conversation history persists across frontend re-attaches
- [ ] `mcp_gateway/` as separate repo/package when stable
- [x] Speaker identification — `person` field in turn schema, declared client-side via
  `MNEMO_CLIENT_PERSON`; old collection preserved for backward compat
- [ ] `mcp_bundle/` if we write our own MCP tools
- [ ] UPnP transport in `mcp_gateway/transports/upnp.py` (very low priority fallback)
- [ ] Assess desktop-commander `write_file` newline encoding — likely xAI JSON serialization of
  `\n` in tool call args before dc sees it; dc tests pass (test-edit-block-line-endings.js)

## Architecture decisions (locked)

- **Option D**: gateway is source of truth. `mcp.conf` defines MCP servers → gateway compiles →
  writes `/etc/mnemo/gateway.json` (manifest) → agent consumes URL only.
- **`/etc/mnemo/gateway.json`** schema: `{"servers": [{"label", "url", "headers"}]}` —
  runtime state, outside repo.
- **pycloudflared** default tunnel transport. `dns.py` (Cloudflare A-record) as opt-in for
  static-IP setups.
- **mcp-proxy** replaces supergateway. Keeps stdio process alive across SSE reconnections.
- **streamablehttp transport** is required. xAI's MCP client receives a relative path in the SSE
  endpoint event (`data: /messages/?session_id=...`) and cannot resolve it to the CF tunnel base
  URL — initialize never completes. `streamablehttp` uses a single `/mcp` endpoint with no
  session redirect and works correctly.
- **`mcp_gateway/transports/`** subfolder for pluggable transport backends — enables Tailscale,
  ngrok etc. later without touching agent.
- **hearth ↔ app IPC**: plain TCP socket on a fixed local port. No CF tunnel — CF is only
  needed for xAI's servers reaching in from the internet. LAN direct, remote via Tailscale.
- **memory_mcp**: built in-house. Covers the use-case better than upstream qdrant/mcp-server-qdrant.
