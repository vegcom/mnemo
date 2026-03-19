"""
UPnP tunnel manager — opens port forwards on UPnP-capable routers.

Alternative to Cloudflare DNS (dns.py) for networks where manual port
forwarding isn't possible but UPnP is available (e.g. home networks).

Env vars:
  TUNNEL_LOCAL_PORT   — local MCP port to expose (default: 8080)
  TUNNEL_EXTERNAL_PORT — external port to request (default: same as local)
"""

# TODO: implement using miniupnpc or upnpclient


class TunnelManager:
    """UPnP port forwarder. Stub — not yet implemented."""

    def __init__(self):
        raise NotImplementedError("UPnP tunnel not yet implemented")

    def start(self) -> str:
        """Open UPnP port forward. Returns public MCP URL."""
        ...

    def stop(self):
        """Remove UPnP port forward lease."""
        ...
