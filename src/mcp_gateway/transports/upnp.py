"""
transports/upnp.py — UPnP port-forwarding transport stub.

Planned fallback for networks where pycloudflared is unavailable and
no static public IP exists. Not yet implemented.
"""


class UPnPTunnel:
    """UPnP port-forwarding transport. Stub — not yet implemented."""

    def __init__(self, port: int):
        raise NotImplementedError("UPnP transport not yet implemented")

    def start(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def stop(self):  # pragma: no cover
        pass
