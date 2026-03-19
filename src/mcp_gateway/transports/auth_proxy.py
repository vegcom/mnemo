"""
transports/auth_proxy.py — Bearer-token auth guard in front of mcp-proxy.

Binds on the public port (MCP_LOCAL_PORT), checks Authorization: Bearer {token},
and reverse-proxies valid requests to mcp-proxy's internal port.

Used when MCP_AUTH_TOKEN is set.  Backend port defaults to MCP_LOCAL_PORT + 1.
"""

import logging
import threading
from contextlib import asynccontextmanager

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

log = logging.getLogger(__name__)

_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
})


class AuthProxy:
    """Thin ASGI reverse proxy that enforces Bearer token auth.

    Usage::

        proxy = AuthProxy(public_port=2086, backend_port=2087, token="secret")
        proxy.start()
        ...
        proxy.stop()
    """

    def __init__(
        self,
        public_port: int,
        backend_port: int,
        token: str,
        host: str = "127.0.0.1",
    ):
        self.public_port = public_port
        self.backend_port = backend_port
        self.token = token
        self.host = host
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def _make_app(self) -> Starlette:
        token = self.token
        backend_url = f"http://127.0.0.1:{self.backend_port}"

        @asynccontextmanager
        async def lifespan(app: Starlette):
            async with httpx.AsyncClient(base_url=backend_url, timeout=None) as client:
                app.state.http = client
                yield

        async def handle(request: Request) -> Response:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {token}":
                log.warning("AuthProxy: rejected %s %s%s from %s — bad/missing token",
                            request.method,
                            request.headers.get("host", "?"),
                            request.url.path,
                            request.client.host if request.client else "unknown")
                return Response("Unauthorized", status_code=401, media_type="text/plain")

            path = request.url.path
            if request.url.query:
                path += "?" + request.url.query

            fwd_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in _HOP_BY_HOP | {"authorization"}
            }
            body = await request.body()

            req = request.app.state.http.build_request(
                method=request.method,
                url=path,
                headers=fwd_headers,
                content=body,
            )
            resp = await request.app.state.http.send(req, stream=True)

            out_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in _HOP_BY_HOP
            }

            async def _stream():
                try:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                finally:
                    await resp.aclose()

            return StreamingResponse(
                _stream(),
                status_code=resp.status_code,
                headers=out_headers,
                media_type=resp.headers.get("content-type"),
            )

        routes = [
            Route("/", handle, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]),
            Route("/{path:path}", handle, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]),
        ]
        return Starlette(lifespan=lifespan, routes=routes)

    def start(self):
        app = self._make_app()
        config = uvicorn.Config(app, host=self.host, port=self.public_port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="auth-proxy")
        self._thread.start()
        log.info("AuthProxy on :%d → backend :%d", self.public_port, self.backend_port)

    def stop(self):
        if self._server:
            self._server.should_exit = True
