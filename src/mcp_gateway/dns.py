"""
Cloudflare DNS manager — points TUNNEL_HOSTNAME to this machine's public IP.

Requires the host to be publicly reachable on port 80 (use supergateway or a
reverse proxy to expose the local MCP server over HTTP).

Env vars:
  CLOUDFLARE_API_TOKEN   — CF API token (DNS:Edit)
  CLOUDFLARE_ZONE_ID     — zone ID for the domain
  TUNNEL_HOSTNAME        — public hostname, e.g. mcp.example.com
  TUNNEL_LOCAL_PORT      — local port (default: 8080)
"""

import os
import urllib.request

from cloudflare import Cloudflare


def _public_ip() -> str:
    with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
        return r.read().decode().strip()


class DnsManager:
    def __init__(self):
        self._client   = Cloudflare()  # picks up CLOUDFLARE_API_TOKEN
        self._hostname = os.getenv("TUNNEL_HOSTNAME", "")
        self._zone_id  = os.getenv("CLOUDFLARE_ZONE_ID", "")

    def start(self) -> str:
        """Upsert A record → public IP. Returns public MCP URL."""
        ip = _public_ip()
        self._upsert_a(ip)
        return f"https://{self._hostname}/mcp"

    def stop(self):
        pass  # DNS record persists intentionally

    def _upsert_a(self, ip: str):
        records = self._client.dns.records.list(zone_id=self._zone_id)
        for r in records:
            if getattr(r, "name", "") == self._hostname and r.type == "A":
                if r.content != ip:
                    self._client.dns.records.update(
                        r.id,
                        zone_id=self._zone_id,
                        type="A",
                        name=self._hostname,
                        content=ip,
                        proxied=True,
                    )
                return
        self._client.dns.records.create(
            zone_id=self._zone_id,
            type="A",
            name=self._hostname,
            content=ip,
            proxied=True,
        )
