"""
mcp_gateway — entry point (python -m mcp_gateway  or  mcp-gateway CLI).

Boot sequence:
  1. Load .env from repo root (if present)
  2. Optionally start mcp-proxy subprocess  (MCP_MANAGE_PROXY=1)
  3. Start Cloudflare tunnel  (or DNS via MCP_TUNNEL_BACKEND=dns)
  4. Load mcp.conf, substitute tunnel URL for any localhost:{port} entries
  5. Write ~/.config/mnemo/gateway.json  {"servers": [{...}, ...]}
  6. Block until SIGTERM / SIGINT

Env vars:
  MCP_LOCAL_PORT        local port mcp-proxy listens on (default: 8080)
  MCP_MANAGE_PROXY      set to "1" to let the gateway spawn mcp-proxy itself
  MCP_PROXY_CMD         stdio command mcp-proxy wraps  (default: desktop-commander)
  MCP_PROXY_TRANSPORT   mcp-proxy transport: "streamablehttp" (default) or "sse"
  MCP_TUNNEL_BACKEND    "cloudflare" (default) or "dns"
  MCP_LOG_PATH          file to append logs to (default: "" = disabled)
  MCP_CONFIG_PATH       path to mcp.conf (default: <package>/mcp.conf)
  MCP_SERVER_LABEL      label written to gateway.json when no mcp.conf is found (default: "gateway")
  MNEMO_GATEWAY_JSON      path to write gateway.json (default: ~/.config/mnemo/gateway.json)
  MCP_AUTH_TOKEN        Bearer token — when set, an auth proxy guards the public port (default: off)
  MCP_PROXY_PORT        internal port for mcp-proxy when auth is active (default: MCP_LOCAL_PORT + 1)
"""

import json
import logging
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("mcp_gateway")

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
_GATEWAY_JSON_DEFAULT = Path.home() / ".config" / "mnemo" / "gateway.json"


def _gateway_json_path() -> Path:
    env = os.environ.get("MNEMO_GATEWAY_JSON", "")
    return Path(env) if env else _GATEWAY_JSON_DEFAULT


def _load_env():
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def _substitute_local(url: str, local_port: int, tunnel_base: str) -> str:
    """Replace localhost:{local_port} origin with tunnel_base, keeping the path."""
    parsed = urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1") and parsed.port == local_port:
        tunnel = urlparse(tunnel_base)
        return urlunparse(parsed._replace(scheme=tunnel.scheme, netloc=tunnel.netloc))
    return url


def _write_gateway(servers: list[dict]):
    """Upsert servers into gateway.json keyed by label.

    Safe for multiple gateway instances — each writes its own label without
    clobbering other services' entries.
    """
    path = _gateway_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
            for s in data.get("servers", []):
                if s.get("label"):
                    existing[s["label"]] = s
        except (json.JSONDecodeError, KeyError):
            pass

    for s in servers:
        existing[s["label"]] = s

    path.write_text(json.dumps({"servers": list(existing.values())}, indent=2))
    log.info("Wrote %s  (%d server(s) total)", path, len(existing))


def _setup_file_logging():
    log_path = os.getenv("MCP_LOG_PATH", "")
    if not log_path:
        return
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(name)s  %(message)s"))
    logging.getLogger().addHandler(fh)
    log.info("Logging to %s", log_path)


def main():
    _load_env()
    _setup_file_logging()

    local_port = int(os.getenv("MCP_LOCAL_PORT", "8080"))
    auth_token = os.getenv("MCP_AUTH_TOKEN", "")

    transport = os.getenv("MCP_PROXY_TRANSPORT", "streamablehttp")
    mcp_path = "/mcp"  # mcp-proxy always serves streamablehttp at /mcp regardless of MCP_PROXY_TRANSPORT

    # Optionally manage mcp-proxy ourselves (skip when systemd handles it)
    proxy = None
    auth_proxy = None
    if os.getenv("MCP_MANAGE_PROXY", "0") == "1":
        from mcp_gateway.transports.proxy import ProxyTransport

        cmd = os.getenv("MCP_PROXY_CMD", "desktop-commander").split()
        # When auth is active, mcp-proxy binds to an internal port; auth proxy owns the public port.
        proxy_port = int(os.getenv("MCP_PROXY_PORT", str(local_port + 1 if auth_token else local_port)))
        proxy = ProxyTransport(port=proxy_port, command=cmd, transport=transport)
        proxy.start()
        log.info("mcp-proxy managing: %s on port %d (transport=%s)", cmd, proxy_port, transport)

        if auth_token:
            from mcp_gateway.transports.auth_proxy import AuthProxy
            auth_proxy = AuthProxy(public_port=local_port, backend_port=proxy_port, token=auth_token)
            auth_proxy.start()

    from mcp_gateway.transports.tunnel import make_tunnel
    from mcp_gateway.mcp import load_server_configs

    tunnel = make_tunnel(port=local_port)
    tunnel_base = tunnel.start()

    auth_headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    # Build servers list: substitute tunnel URL for any localhost:{port} entries
    raw = load_server_configs()
    servers = []
    for s in raw:
        resolved_url = _substitute_local(s["url"], local_port, tunnel_base)
        servers.append({"label": s["label"], "url": resolved_url, "headers": {**s["headers"], **auth_headers}})
        log.info("MCP server: %s → %s", s["label"], resolved_url)

    if not servers:
        # Fallback: no mcp.conf — expose the local proxy directly via tunnel
        fallback_url = tunnel_base + mcp_path
        label = os.getenv("MCP_SERVER_LABEL", "gateway")
        servers = [{"label": label, "url": fallback_url, "headers": auth_headers}]
        log.warning("No mcp.conf servers found — fallback URL: %s (label: %s)", fallback_url, label)

    _write_gateway(servers=servers)
    log.info("Gateway ready — %d server(s)", len(servers))

    def _shutdown(sig, _frame):
        log.info("Shutting down (signal %d)…", sig)
        tunnel.stop()
        if auth_proxy:
            auth_proxy.stop()
        if proxy:
            proxy.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    signal.pause()


if __name__ == "__main__":
    main()
