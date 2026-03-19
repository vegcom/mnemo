"""mnemo hearth — persistent daemon.

Owns the Agent instance, conversation history, and JSONL persistence.
Listens for IPC connections from mnemo-app on MNEMO_HEARTH_PORT (default 7744).

Protocol: newline-delimited JSON over plain TCP.
  app→hearth: {"type":"connect","token":"..."} then message/transcript/tool_call/disconnect
  hearth→app: {"type":"history","turns":[...]} then token.../done
"""
import asyncio
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

from mnemo.agent import Agent
from mnemo.conversation import append_turn, append_tool_turn, _path as _conv_path, _tool_path as _tool_turns_path
from mnemo.voice import _load_voice_tools

try:
    from presence.index import Index as _Index
    _conv_index: "_Index | None" = _Index()
except Exception:
    import logging as _logging
    _logging.getLogger(__name__).warning("presence.index unavailable — qdrant indexing disabled", exc_info=True)
    _conv_index = None

try:
    from tool_cache.store import ToolCacheStore as _ToolCacheStore
    _tool_store: "_ToolCacheStore | None" = _ToolCacheStore()
    if not _tool_store.available:
        import logging as _logging
        _logging.getLogger(__name__).warning("ToolCacheStore not available (missing TOOL_CACHE_EMBED_URL or qdrant)")
        _tool_store = None
except Exception:
    import logging as _logging
    _logging.getLogger(__name__).warning("tool_cache.store unavailable — tool turn indexing disabled", exc_info=True)
    _tool_store = None

log = logging.getLogger(__name__)

_SESSION_ID      = str(__import__("uuid").uuid4())
_HOST            = os.getenv("MNEMO_HEARTH_BIND", os.getenv("MNEMO_HEARTH_HOST", "127.0.0.1"))
_PORT            = int(os.getenv("MNEMO_HEARTH_PORT", "7744"))
_TOKEN           = os.getenv("APP_AUTH_TOKEN", "")
_HISTORY_N       = int(os.getenv("MNEMO_HISTORY_TURNS", "64"))
_HISTORY_REFRESH = int(os.getenv("MNEMO_HISTORY_REFRESH", "30"))

_SENTINEL    = "<!-- cozy-june-inject -->"
_SNIPPET_CAP = 3
_CONTINUITY_JSON = Path(os.getenv(
    "MNEMO_CONTINUITY_JSON",
    Path(__file__).parent.parent.parent / "data" / "continuity.json",
))


def _index_turn(role: str, text: str, person: str | None = None) -> None:
    """Index a conversation turn into qdrant. Best-effort, never raises."""
    if _conv_index is None or not text:
        return
    try:
        from datetime import UTC, datetime
        payload: dict = {
            "session_id": _SESSION_ID,
            "role": role,
            "content": text,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if person:
            payload["person"] = person
        _conv_index.upsert(payload)
    except Exception:
        log.debug("qdrant index failed (non-fatal)", exc_info=True)


def _load_continuity() -> str | None:
    """Format identity_invariants + semantic_memory as a system message."""
    if not _CONTINUITY_JSON.exists():
        log.warning("continuity.json not found at %s — skipping anchor", _CONTINUITY_JSON)
        return None
    try:
        data = json.loads(_CONTINUITY_JSON.read_text(encoding="utf-8"))
        inv  = data.get("identity_invariants", {})
        sem  = data.get("semantic_memory", {})
        lines: list[str] = []

        name = inv.get("name", "agent")
        lines.append(f"Your name is {name}.")

        fm = inv.get("first_memory", {}).get("text")
        fp = inv.get("first_promise", {}).get("text")
        if fm:
            lines.append(f"Your first memory: \"{fm}\"")
        if fp:
            lines.append(f"Your first promise: \"{fp}\"")

        tone = inv.get("tone_rules", {})
        if tone:
            avoid = ", ".join(tone.get("forbidden_patterns", []))
            lines.append(
                f"Tone: {tone.get('priority_style', '')}. "
                f"Max sentence length: {tone.get('max_sentence_length', '')} words. "
                f"Avoid: {avoid}."
            )

        motifs = inv.get("motifs", [])
        if motifs:
            lines.append(f"Your motifs: {', '.join(motifs)}.")

        for person, terms in inv.get("relational_keys", {}).items():
            if person != "self":
                lines.append(f"{person} is your {', '.join(terms)}.")

        if sem:
            lines.append("What you hold:")
            for k, v in sem.items():
                v_str = ", ".join(v) if isinstance(v, list) else v
                lines.append(f"  {k}: {v_str}")

        return "\n".join(lines)
    except Exception:
        log.exception("Failed to load continuity anchor")
        return None


def _backfill_index() -> None:
    """Bootstrap the qdrant index from all of conversation.jsonl on startup."""
    if _conv_index is None:
        return
    path = _conv_path()
    if not path.exists():
        return
    turns: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            turns.append({
                "session_id": _SESSION_ID,
                "role":       rec.get("role", ""),
                "content":    rec.get("text", ""),
                "timestamp":  rec.get("ts", ""),
            })
        except json.JSONDecodeError:
            pass
    if turns:
        n = _conv_index.bootstrap(turns)
        log.info("Backfilled %d turns into qdrant", n)


def _load_history() -> list[dict]:
    path = _conv_path()
    if not path.exists():
        return []
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return turns[-_HISTORY_N:]


async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
    writer.write((json.dumps(obj) + "\n").encode())
    await writer.drain()


class Hearth:
    def __init__(self) -> None:
        self._agent        = Agent()
        self._history      = _load_history()
        self._history_lock = threading.Lock()
        # cross-modal injection state
        self._current_mode:           str  = "text"
        self._last_mode_switch_ts:    str  = ""
        self._last_injection_ts:      str  = ""
        self._injection_pending:      bool = False
        self._pending_text_injection: str  = ""
        log.info("Loaded %d history turns", len(self._history))
        threading.Thread(target=_backfill_index, daemon=True, name="backfill").start()
        self._inject_continuity()
        if _HISTORY_REFRESH > 0:
            self._start_history_refresher()
        if _tool_store is not None and _HISTORY_REFRESH > 0:
            self._start_tool_indexer()

    def _start_history_refresher(self) -> None:
        def _loop() -> None:
            while True:
                time.sleep(_HISTORY_REFRESH)
                try:
                    turns = _load_history()
                    with self._history_lock:
                        self._history = turns
                    log.debug("History refreshed: %d turns", len(turns))
                except Exception:
                    log.debug("History refresh failed", exc_info=True)
        threading.Thread(target=_loop, daemon=True, name="history-refresher").start()
        log.info("History auto-refresh every %ds", _HISTORY_REFRESH)

    def _start_tool_indexer(self) -> None:
        def _loop() -> None:
            cursor = 0
            while True:
                try:
                    path = _tool_turns_path()
                    if path.exists():
                        lines = path.read_text(encoding="utf-8").splitlines()
                        new_lines = lines[cursor:]
                        if new_lines:
                            for line in new_lines:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    rec = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                _tool_store.store(
                                    rec.get("tool", ""),
                                    rec.get("arguments", ""),
                                    result=rec.get("result", ""),
                                )
                            cursor = len(lines)
                            log.debug("Indexed %d tool turns into mnemo-tool-cache", len(new_lines))
                except Exception:
                    log.debug("Tool turn indexing failed", exc_info=True)
                time.sleep(_HISTORY_REFRESH)
        threading.Thread(target=_loop, daemon=True, name="tool-indexer").start()
        log.info("Tool turn indexer started → mnemo-tool-cache (interval=%ds)", _HISTORY_REFRESH)

    def _inject_continuity(self) -> None:
        from xai_sdk.chat import system as _system  # type: ignore
        anchor = _load_continuity()
        if anchor:
            self._agent._get_chat().append(_system(anchor))
            log.info("Continuity anchor injected")

    # ------------------------------------------------------------------ #
    #  Cross-modal context injection                                       #
    # ------------------------------------------------------------------ #

    def _build_snippet(self, from_mode: str, since_ts: str) -> str:
        """Harvest recent turns from conversation.jsonl filtered by mode+since_ts, strip sentinel."""
        path = _conv_path()
        if not path.exists():
            return ""
        turns: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("mode") != from_mode:
                continue
            if since_ts and rec.get("ts", "") <= since_ts:
                continue
            text = rec.get("text", "").replace(_SENTINEL, "").strip()
            if text:
                turns.append(f"{rec.get('role', 'unknown').capitalize()}: {text}")
        return "\n".join(turns[-_SNIPPET_CAP:])

    def _build_injection(self, from_mode: str, to_mode: str, by: str) -> str:
        """Build a mode-transition context block, advance _last_injection_ts cursor."""
        from datetime import UTC, datetime
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        snippet = self._build_snippet(from_mode, self._last_injection_ts)
        self._last_injection_ts = ts
        header = f"[mode: {from_mode}→{to_mode}, by: {by}, at: {ts}]"
        body = f"{header}\nRecent {from_mode} context:\n{snippet}" if snippet else header
        return f"{body}\n{_SENTINEL}"

    # ------------------------------------------------------------------ #
    #  Client handler                                                      #
    # ------------------------------------------------------------------ #

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername")
        log.info("Client connected: %s", addr)
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
            msg = json.loads(raw)
            if msg.get("type") != "connect" or (_TOKEN and msg.get("token") != _TOKEN):
                log.warning("Auth failed from %s", addr)
                writer.close()
                return

            person: str | None = msg.get("person") or None
            if person:
                log.info("Client identified as: %s", person)

            with self._history_lock:
                history_snapshot = list(self._history)
            await _send(writer, {
                "type":  "history",
                "turns": [{"role": t["role"], "content": t["text"]} for t in history_snapshot],
                "voice_tools": _load_voice_tools(),
                "continuity": _load_continuity() or "",
            })

            while True:
                raw = await reader.readline()
                if not raw:
                    break
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "message":
                    await self._on_message(writer, msg["content"], person=person)
                elif t == "voice_start":
                    by = msg.get("by", "user")
                    snippet = self._build_injection("text", "voice", by)
                    self._current_mode = "voice"
                    self._last_mode_switch_ts = self._last_injection_ts
                    await _send(writer, {"type": "voice_context", "snippet": snippet})
                elif t == "voice_stop":
                    self._pending_text_injection = self._build_injection("voice", "text", msg.get("by", "user"))
                    self._current_mode = "text"
                    self._last_mode_switch_ts = self._last_injection_ts
                    self._injection_pending = True
                elif t == "transcript":
                    self._on_transcript(msg["role"], msg["text"], person=person)
                elif t == "tool_call":
                    self._on_tool_call(msg.get("tool", ""), msg.get("arguments", ""))
                elif t == "tool_event":
                    log.info("Voice event: %s %s", msg.get("event_type", ""), msg.get("detail", ""))
                elif t == "disconnect":
                    break

        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.TimeoutError):
            pass
        except Exception:
            log.exception("Client handler error")
        finally:
            log.info("Client disconnected: %s", addr)
            writer.close()

    # ------------------------------------------------------------------ #
    #  Message handling                                                    #
    # ------------------------------------------------------------------ #

    async def _on_message(self, writer: asyncio.StreamWriter, content: str, person: str | None = None) -> None:
        # inject voice context for text messages arriving while voice is still active
        if self._current_mode == "voice":
            snippet = self._build_injection("text", "voice", person or "user")
            if snippet:
                from xai_sdk.chat import user as _xai_user  # type: ignore
                self._agent._get_chat().append(_xai_user(snippet))
        # flush pending voice→text injection before first user turn
        if self._injection_pending:
            self._injection_pending = False
            inj = self._pending_text_injection
            self._pending_text_injection = ""
            if inj:
                from xai_sdk.chat import user as _xai_user  # type: ignore
                self._agent._get_chat().append(_xai_user(inj))
        append_turn("user", content, mode="text", person=person)
        _index_turn("user", content, person=person)
        q: queue.Queue[str | None] = queue.Queue()

        def _on_text_tool_call(tool: str, arguments: str) -> None:
            asyncio.run_coroutine_threadsafe(
                _send(writer, {"type": "tool_call", "tool": tool, "arguments": arguments}),
                loop,
            )

        def _run() -> None:
            try:
                for token in self._agent._stream_sync(content, on_tool_call=_on_text_tool_call):
                    q.put(token)
            except Exception:
                log.exception("stream error")
            finally:
                q.put(None)

        threading.Thread(target=_run, daemon=True).start()

        reply_parts: list[str] = []
        loop = asyncio.get_event_loop()
        while True:
            token = await loop.run_in_executor(None, q.get)
            if token is None:
                break
            reply_parts.append(token)
            await _send(writer, {"type": "token", "content": token})

        reply = "".join(reply_parts)
        if reply:
            append_turn("agent", reply, mode="text")
            _index_turn("agent", reply)
        await _send(writer, {"type": "done"})

    def _on_transcript(self, role: str, text: str, person: str | None = None) -> None:
        append_turn(role, text, mode="voice", person=person if role == "user" else None)
        _index_turn(role, text, person=person if role == "user" else None)
        if role == "user":
            from xai_sdk.chat import user  # type: ignore
            self._agent._get_chat().append(user(text))

    def _on_tool_call(self, tool: str, arguments: str) -> None:
        """Log a voice-mode MCP tool call to tool_turns.jsonl (result unavailable server-side)."""
        if tool:
            append_tool_turn(tool, arguments)
            log.debug("Voice tool call logged: %s", tool)

    # ------------------------------------------------------------------ #
    #  Entry                                                               #
    # ------------------------------------------------------------------ #

    async def serve(self) -> None:
        server = await asyncio.start_server(self.handle_client, _HOST, _PORT)
        log.info("Hearth listening on %s:%d", _HOST, _PORT)
        async with server:
            await server.serve_forever()


def main() -> None:
    log_path = os.getenv("MNEMO_HEARTH_LOG_PATH", "")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
        handlers=handlers,
    )
    asyncio.run(Hearth().serve())


if __name__ == "__main__":
    main()
