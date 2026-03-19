"""
MCP server config loader — reads mcp.conf, expands env vars.

load_server_configs() → list of plain dicts (gateway-internal, no xAI dep)
load_servers()        → list of xAI Tool objects (for direct agent use if needed)

Config path priority:
  1. MCP_CONFIG_PATH env var
  2. Path passed to the function
  3. <package-dir>/mcp.conf
"""

import configparser
import os
import re
from pathlib import Path

_CONF_PATH = Path(__file__).parent / "mcp.conf"


def _default_path() -> Path:
    env = os.environ.get("MCP_CONFIG_PATH", "")
    return Path(env) if env else _CONF_PATH


def _expand(value: str) -> str:
    """Expand ${VAR:-default} and $VAR patterns."""
    def _sub(m):
        var, _, default = m.group(1).partition(":-")
        return os.environ.get(var, default)
    value = re.sub(r'\$\{([^}]+)\}', _sub, value)
    return os.path.expandvars(value)


def load_server_configs(path: Path | None = None) -> list[dict]:
    """Return list of server config dicts for each enabled MCP server.

    Each dict: {"label": str, "url": str, "headers": dict[str, str]}
    """
    path = path or _default_path()
    if not path.exists():
        return []

    cfg = configparser.ConfigParser()
    cfg.read(path)

    servers = []
    for name in cfg.sections():
        section = cfg[name]
        if not section.getboolean("enabled", fallback=True):
            continue
        url = _expand(section.get("url", ""))
        if url and "://" not in url:
            url = f"https://{url}"
        if not url:
            continue
        extra = _expand(section.get("extra_headers", ""))
        headers = dict(h.split(":", 1) for h in extra.splitlines() if ":" in h)
        servers.append({"label": name, "url": url, "headers": headers})
    return servers


def load_servers(path: Path | None = None) -> list:
    """Return xAI Tool objects for each enabled MCP server."""
    from xai_sdk.tools import mcp as _mcp_tool

    servers = []
    for s in load_server_configs(path):
        servers.append(_mcp_tool(
            server_url=s["url"],
            server_label=s["label"],
            **{"extra_headers": s["headers"]} if s["headers"] else {},
        ))
    return servers
