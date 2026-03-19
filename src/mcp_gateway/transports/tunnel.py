"""
transports/tunnel.py — Cloudflare tunnel transport (default).

Uses pycloudflared to punch a public HTTPS tunnel to a local port.
No public IP, no firewall rules, no DNS config required.

Opt-in to named tunnel mode (stable URL, no rate limit) via env vars:
  MCP_TUNNEL_BACKEND=named  — use NamedTunnel instead of trycloudflare
  TUNNEL_NAME               — tunnel name (from `cloudflared tunnel create`)
  TUNNEL_CRED_FILE          — path to tunnel credentials JSON
  TUNNEL_PUBLIC_URL         — override public URL (default: https://<uuid>.cfargotunnel.com)

Opt-in to DNS mode (static-IP setups) via env var:
  MCP_TUNNEL_BACKEND=dns   — use DnsManager (mcp_gateway/dns.py) instead
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_READY_RE = re.compile(r"Registered tunnel connection|Connection registered|Started piping")


class CloudflareTunnel:
    """
    pycloudflared-backed tunnel. Wraps a local port with a public trycloudflare URL.

    Usage::

        tunnel = CloudflareTunnel(port=8080)
        url = tunnel.start()   # "https://xxxx.trycloudflare.com"
        ...
        tunnel.stop()
    """

    def __init__(self, port: int):
        self.port = port
        self._try_cloudflare = None

    def start(self) -> str:
        """Start tunnel. Returns the public HTTPS URL."""
        from pycloudflared import try_cloudflare as _tc  # deferred — not required at import time

        self._try_cloudflare = _tc
        log.info("Starting pycloudflared tunnel → localhost:%d", self.port)
        result = _tc(port=self.port)
        url = result.tunnel.rstrip("/")
        log.info("Tunnel active: %s", url)
        return url

    def stop(self):
        if self._try_cloudflare is not None:
            try:
                self._try_cloudflare.terminate(self.port)
            except Exception:
                pass
            self._try_cloudflare = None


class NamedTunnel:
    """
    Named Cloudflare tunnel — stable URL, no trycloudflare rate limits.

    Requires a tunnel created with `cloudflared tunnel create <name>` and
    the resulting credentials JSON. Public URL is derived from the tunnel
    UUID (https://<uuid>.cfargotunnel.com) unless TUNNEL_PUBLIC_URL is set
    (e.g. after adding a DNS route with `cloudflared tunnel route dns`).

    Env vars (set in systemd unit):
      TUNNEL_NAME       — tunnel name
      TUNNEL_CRED_FILE  — path to credentials JSON
      TUNNEL_PUBLIC_URL — override public URL (optional)
    """

    def __init__(self, port: int):
        self.port = port
        self._proc: subprocess.Popen | None = None
        self._config_path: Path | None = None

    def start(self) -> str:
        from pycloudflared.util import get_info

        tunnel_name = os.environ["TUNNEL_NAME"]
        cred_file = Path(os.environ["TUNNEL_CRED_FILE"])

        tunnel_id = json.loads(cred_file.read_text())["TunnelID"]
        public_url = os.getenv("TUNNEL_PUBLIC_URL", f"https://{tunnel_id}.cfargotunnel.com")

        # Write a minimal cloudflared config to a known path so the process
        # can be inspected with `cloudflared tunnel info` if needed.
        self._config_path = Path(__import__("tempfile").gettempdir()) / f"mnemo-tunnel-{self.port}.yml"
        self._config_path.write_text(
            f"tunnel: {tunnel_id}\n"
            f"credentials-file: {cred_file}\n"
            f"ingress:\n"
            f"  - service: http://127.0.0.1:{self.port}\n"
        )

        exe = get_info().executable
        args = [exe, "tunnel", "--config", str(self._config_path), "run", tunnel_name]

        log.info("Starting named tunnel %r → localhost:%d", tunnel_name, self.port)
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )

        # Read stderr until tunnel reports ready (up to 100 lines)
        for _ in range(100):
            line = self._proc.stderr.readline()
            if not line:
                break
            log.info("cloudflared: %s", line.rstrip())
            if _READY_RE.search(line):
                break

        if self._proc.poll() is not None:
            log.error("cloudflared exited early (rc=%d) — tunnel not established", self._proc.returncode)
            raise RuntimeError(f"cloudflared exited with rc={self._proc.returncode}")

        log.info("Named tunnel active: %s", public_url)
        return public_url

    def stop(self):
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None
        if self._config_path and self._config_path.exists():
            self._config_path.unlink(missing_ok=True)
            self._config_path = None


def make_tunnel(port: int) -> CloudflareTunnel | NamedTunnel:
    """
    Return the appropriate tunnel transport.

    Defaults to CloudflareTunnel (trycloudflare, ephemeral URL).
    Set MCP_TUNNEL_BACKEND=named for a named tunnel (stable URL, no rate limit).
    Set MCP_TUNNEL_BACKEND=dns to use DnsManager (requires static IP + CF API token).
    """
    backend = os.getenv("MCP_TUNNEL_BACKEND", "cloudflare").lower()
    if backend == "dns":
        from mcp_gateway.dns import DnsManager

        log.info("Using DNS tunnel backend (DnsManager)")
        return DnsManager()  # type: ignore[return-value]
    if backend == "named":
        log.info("Using named tunnel backend (NamedTunnel)")
        return NamedTunnel(port=port)
    return CloudflareTunnel(port=port)
