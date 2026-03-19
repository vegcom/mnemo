import json
import logging
import os
from pathlib import Path

from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import mcp as _mcp_tool, web_search, x_search, code_execution, collections_search

from mnemo.conversation import append_tool_turn as _append_tool_turn

log = logging.getLogger(__name__)

# load .env from repo root if present
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

_GATEWAY_JSON_DEFAULT  = Path.home() / ".config" / "mnemo" / "gateway.json"
_GATEWAY_JSON          = Path(os.environ["MNEMO_GATEWAY_JSON"]) if "MNEMO_GATEWAY_JSON" in os.environ else _GATEWAY_JSON_DEFAULT
_RESPONSE_ID_PATH      = Path(os.environ.get("MNEMO_RESPONSE_ID_PATH", Path.home() / ".config" / "mnemo" / "last_response_id"))


def _load_tools() -> list:
    """Read gateway.json written by mcp_gateway and return xAI Tool objects."""
    tools: list = [web_search(), x_search(), code_execution()]

    continuity_collection = os.environ.get("MNEMO_CONTINUITY_COLLECTION", "").strip()
    if continuity_collection:
        log.info("collections_search enabled — collection=%s", continuity_collection)
        tools.append(collections_search(collection_ids=[continuity_collection]))
    else:
        log.debug("MNEMO_CONTINUITY_COLLECTION not set — collections_search disabled")

    if not _GATEWAY_JSON.exists():
        log.warning("gateway.json not found — no MCP tools loaded")
        return tools
    data = json.loads(_GATEWAY_JSON.read_text())

    # New multi-server format: {"servers": [{"label", "url", "headers"}, ...]}
    if "servers" in data:
        for s in data["servers"]:
            url = s.get("url", "")
            if not url:
                continue
            headers = s.get("headers", {})
            label = s.get("label", "mcp")
            auth = headers.get("authorization", "") or headers.get("Authorization", "")
            # xAI SDK prepends "Bearer " automatically — pass raw token only.
            if auth.startswith("Bearer "):
                auth = auth[len("Bearer "):]
            log.info("Loading MCP tool: %s → %s", label, url)
            tools.append(_mcp_tool(
                server_url=url,
                server_label=label,
                **{"authorization": auth} if auth else {},
            ))
        if len(tools) == 3:
            log.warning("gateway.json servers list is empty — no MCP tools loaded")
        return tools

    log.warning("gateway.json has no 'servers' key — no MCP tools loaded")
    return tools


class Agent():

    def __init__(
        self,
        api_key: str = None,
        model_uri: str = "grok-4-1-fast-reasoning",
        **kwargs,
    ):
        self.api_key   = api_key or os.getenv("XAI_API_KEY")
        self.model_uri = model_uri
        self.client    = Client(api_key=self.api_key, timeout=3600)
        self._chat     = None

    def _load_response_id(self) -> str | None:
        if _RESPONSE_ID_PATH.exists():
            return _RESPONSE_ID_PATH.read_text().strip() or None
        return None

    def _save_response_id(self, response_id: str) -> None:
        _RESPONSE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RESPONSE_ID_PATH.write_text(response_id)

    def _get_chat(self):
        if self._chat is None:
            tools    = _load_tools()
            prev_id  = self._load_response_id()
            kwargs: dict = {
                "store_messages": True,
                "include": [
                    "verbose_streaming",
                    "mcp_call_output",
                    "web_search_call_output",
                    "x_search_call_output",
                    "code_execution_call_output",
                ],
            }
            if prev_id:
                kwargs["previous_response_id"] = prev_id
                log.info("Resuming from response_id=%s", prev_id)
            log.info("Creating chat — model=%s tools=%d", self.model_uri, len(tools))
            self._chat = self.client.chat.create(model=self.model_uri, tools=tools, **kwargs)
        return self._chat

    def _stream_sync(self, message: str, on_tool_call=None):
        """Sync generator for use in threads (Textual worker).

        on_tool_call: optional callable(tool_name: str, arguments: str) fired
                      for each tool call chunk — use to surface calls to the UI.
        """
        chat = self._get_chat()
        log.info("Starting xAI stream — model=%s", self.model_uri)
        chat.append(user(message))
        response = None
        for response, chunk in chat.stream():
            if chunk.content is not None:
                yield chunk.content
            if chunk.tool_calls:
                for tc in chunk.tool_calls:
                    log.info("Tool call: %s", tc.function.name)
                    if on_tool_call:
                        on_tool_call(tc.function.name, tc.function.arguments or "")
        if response is not None:
            for to in response.tool_outputs:
                msg = to.message
                name = msg.tool_calls[0].function.name if msg.tool_calls else ""
                args = msg.tool_calls[0].function.arguments if msg.tool_calls else ""
                _append_tool_turn(name, args, result=msg.content)
            chat.append(response)
            if hasattr(response, "id") and response.id:
                self._save_response_id(response.id)
        log.info("xAI stream complete")

    async def stream(self, message: str):
        """Yield response tokens — wire directly to TUI."""
        chat = self._get_chat()
        log.info("Starting xAI stream — model=%s", self.model_uri)
        chat.append(user(message))
        response = None
        for response, chunk in chat.stream():
            if chunk.content is not None:
                yield chunk.content
            if chunk.tool_calls:
                for tc in chunk.tool_calls:
                    log.info("Tool call: %s", tc.function.name)
        if response is not None:
            for to in response.tool_outputs:
                msg = to.message
                name = msg.tool_calls[0].function.name if msg.tool_calls else ""
                args = msg.tool_calls[0].function.arguments if msg.tool_calls else ""
                _append_tool_turn(name, args, result=msg.content)
            chat.append(response)
            if hasattr(response, "id") and response.id:
                self._save_response_id(response.id)
        log.info("xAI stream complete")
