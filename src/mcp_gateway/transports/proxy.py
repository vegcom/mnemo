"""
transports/proxy.py — MCP subprocess wrapper with auto-restart.

Two modes depending on MCP_PROXY_TRANSPORT / transport arg:

  sse (default)
    Spawns mcp-proxy wrapping a stdio command, exposes SSE at /sse.
    cmd: mcp-proxy --port PORT --host HOST -- COMMAND

  streamablehttp
    Spawns the command directly as a native streamable-HTTP server.
    mcp-proxy is NOT used — the command must bind to PORT itself.
    FastMCP servers do this when transport="streamable-http" is set.
    cmd: COMMAND  (with FASTMCP_PORT + FASTMCP_HOST injected into env)

Env vars (all optional):
  MCP_PROXY_HOST  — bind host (default: 127.0.0.1)
"""

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"


def _find_mcp_proxy() -> str:
    """Resolve mcp-proxy co-located with the running Python interpreter (venv/conda safe)."""
    candidate = Path(sys.executable).parent / "mcp-proxy"
    return str(candidate) if candidate.exists() else "mcp-proxy"


class ProxyTransport:
    """
    Wraps an mcp-proxy subprocess. Restarts automatically on unexpected exit.

    Usage::

        proxy = ProxyTransport(port=8080, command=["desktop-commander"])
        proxy.start()
        ...
        proxy.stop()
    """

    def __init__(
        self,
        port: int,
        command: list[str],
        host: str = _DEFAULT_HOST,
        transport: str = "sse",
    ):
        self.port = port
        self.command = command
        self.host = host
        self.transport = transport
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        """Start mcp-proxy and the restart-watchdog thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mcp-proxy-watchdog")
        self._thread.start()

    def stop(self):
        """Signal the watchdog to stop and terminate the subprocess."""
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ------------------------------------------------------------------
    def _spawn(self) -> subprocess.Popen:
        if self.transport == "streamablehttp":
            # Command IS the HTTP server — inject port/host via FastMCP env vars.
            env = os.environ.copy()
            env["FASTMCP_PORT"] = str(self.port)
            env["FASTMCP_HOST"] = self.host
            log.info("Spawning HTTP server: %s (port=%d)", " ".join(self.command), self.port)
            return subprocess.Popen(self.command, env=env)
        # sse/stdio mode: wrap stdio command with mcp-proxy serving streamablehttp
        cmd = [_find_mcp_proxy(), "--port", str(self.port), "--host", self.host,
               "--transport", "streamablehttp", "--", *self.command]
        log.info("Spawning mcp-proxy (stdio→streamablehttp): %s", " ".join(cmd))
        return subprocess.Popen(cmd, env=os.environ.copy())

    def _run(self):
        while not self._stop.is_set():
            self._proc = self._spawn()
            ret = self._proc.wait()
            if self._stop.is_set():
                break
            log.warning("mcp-proxy exited (code %d) — restarting in 2 s…", ret)
            time.sleep(2)
