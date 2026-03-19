"""
mnemo voice agent — raw PCM16 duplex via xAI realtime WebSocket.

mic → PCM16 chunks → base64 → wss://api.x.ai/v1/realtime → audio out → speakers
"""

import asyncio
import base64
import json
import logging
import os
import queue
from pathlib import Path

import websockets

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
CHANNELS = 1
DTYPE = "int16"
CHUNK_MS = 100  # ms per mic chunk
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000

WS_URL = "wss://api.x.ai/v1/realtime"

_GATEWAY_JSON_DEFAULT = Path.home() / ".config" / "mnemo" / "gateway.json"
_GATEWAY_JSON = Path(os.environ["MNEMO_GATEWAY_JSON"]) if "MNEMO_GATEWAY_JSON" in os.environ else _GATEWAY_JSON_DEFAULT


def _load_voice_tools() -> list[dict]:
    """Build session tools list from gateway.json for the realtime WebSocket protocol."""
    tools: list[dict] = [
        {"type": "web_search"},
        {"type": "x_search"},
    ]

    continuity_collection = os.environ.get("MNEMO_CONTINUITY_COLLECTION", "").strip()
    if continuity_collection:
        log.info("voice collections_search enabled — collection=%s", continuity_collection)
        tools.append({"type": "collections_search", "collection_ids": [continuity_collection]})
    else:
        log.debug("MNEMO_CONTINUITY_COLLECTION not set — collections_search disabled in voice")

    if not _GATEWAY_JSON.exists():
        log.warning("gateway.json not found — no MCP tools in voice session")
        return tools

    data = json.loads(_GATEWAY_JSON.read_text())

    if "servers" in data:
        for s in data["servers"]:
            url = s.get("url", "")
            if not url:
                continue
            label = s.get("label", "mcp")
            headers = s.get("headers", {})
            auth = headers.get("authorization", "") or headers.get("Authorization", "")
            # xAI realtime API prepends "Bearer " automatically — pass raw token only.
            if auth.startswith("Bearer "):
                auth = auth[len("Bearer "):]
            entry: dict = {"type": "mcp", "server_url": url, "server_label": label}
            if auth:
                entry["authorization"] = auth
            log.info("Voice MCP tool: %s → %s", label, url)
            tools.append(entry)
        return tools

    # Backward compat: old single-server format {"url": ..., "auth": ...}
    url = data.get("url", "")
    if url:
        auth = data.get("auth", "")
        entry = {"type": "mcp", "server_url": url, "server_label": "gateway"}
        if auth:
            entry["authorization"] = auth
        tools.append(entry)

    return tools


_SESSION_BASE = {
    "type": "session.update",
    "session": {
        "voice": "agent",
        "instructions": (
            "You are the voice agent. You speak naturally and warmly. "
            "You are in a real-time voice conversation. "
            "After using any tool, always speak your findings or results aloud — "
            "never stay silent after a tool call."
        ),
        "turn_detection": {
            "type": "server_vad",
            "silence_duration_ms": 500,
            "threshold": 0.2
            },
        "audio": {
            "input": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}},
            "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}},
        },
    },
}



class VoiceSession:
    def __init__(
        self,
        api_key: str | None = None,
        voice_tools: list[dict] | None = None,  # from hearth; falls back to local gateway.json
        continuity: str | None = None,           # identity anchor from hearth
        injection_snippet: str | None = None,    # cross-modal context (text→voice transition)
        on_transcript=None,   # callback(role: str, text: str)
        on_tool_event=None,   # callback(event_type: str, detail: str)
        on_tool_call=None,    # callback(tool: str, arguments: str)
    ):
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self._voice_tools = voice_tools
        self._continuity = continuity
        self._injection_snippet = injection_snippet
        self.on_transcript = on_transcript
        self.on_tool_event = on_tool_event
        self.on_tool_call = on_tool_call
        self._running = False
        self._audio_out_q: queue.Queue[bytes] = queue.Queue()
        self._pending_user_transcripts: dict[str, str] = {}  # item_id → latest text

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(self):
        """Blocking. Call from a thread."""
        self._running = True
        asyncio.run(self._run())

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ #
    #  Core async loop                                                     #
    # ------------------------------------------------------------------ #

    async def _run(self):
        async with websockets.connect(
            WS_URL,
            ssl=True,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
        ) as ws:
            tools = self._voice_tools if self._voice_tools is not None else _load_voice_tools()
            cfg = json.loads(json.dumps(_SESSION_BASE))
            cfg["session"]["tools"] = tools
            base_instructions = cfg["session"]["instructions"]
            instructions = self._continuity + "\n\n" + base_instructions if self._continuity else base_instructions
            if self._injection_snippet:
                instructions = instructions + "\n\n" + self._injection_snippet
            cfg["session"]["instructions"] = instructions
            await ws.send(json.dumps(cfg))

            mic_task = asyncio.create_task(self._mic_loop(ws))
            recv_task = asyncio.create_task(self._recv_loop(ws))
            play_task = asyncio.create_task(self._play_loop())

            await asyncio.gather(mic_task, recv_task, play_task)

    # ------------------------------------------------------------------ #
    #  Mic → websocket                                                     #
    # ------------------------------------------------------------------ #

    async def _mic_loop(self, ws):
        import sounddevice as sd
        loop = asyncio.get_event_loop()
        chunk_q: asyncio.Queue[bytes] = asyncio.Queue()

        def _callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(chunk_q.put_nowait, bytes(indata))

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_FRAMES,
            callback=_callback,
        ):
            while self._running:
                chunk = await chunk_q.get()
                encoded = base64.b64encode(chunk).decode()
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": encoded,
                }))

    # ------------------------------------------------------------------ #
    #  WebSocket → speakers / callbacks                                   #
    # ------------------------------------------------------------------ #

    async def _recv_loop(self, ws):

        def _flush_all_pending() -> None:
            """Flush all buffered user transcripts.

            Triggered on response.output_audio_transcript.done — by that point
            xAI has finished the agent's response so the user's ASR is fully settled.
            """
            for iid, text in list(self._pending_user_transcripts.items()):
                del self._pending_user_transcripts[iid]
                if text and self.on_transcript:
                    self.on_transcript("user", text)

        async for raw in ws:
            if not self._running:
                break
            event = json.loads(raw)
            etype = event.get("type", "")

            _NOISY = {
                "response.output_audio.delta",
                "response.output_audio_transcript.delta",
                "response.function_call_arguments.delta",
                "input_audio_buffer.speech_started",
                "input_audio_buffer.speech_stopped",
                "input_audio_buffer.committed",
                "conversation.item.input_audio_transcription.delta",
                "conversation.item.added",
                "response.content_part.added",
                "response.content_part.done",
                "ping",
            }
            if etype not in _NOISY:
                log.info("WS event: %s", json.dumps(event)[:300])

            if etype == "response.output_audio.delta":
                audio = base64.b64decode(event["delta"])
                self._audio_out_q.put_nowait(audio)

            elif etype == "response.output_audio_transcript.delta":
                pass  # full transcript arrives on response.output_audio_transcript.done

            elif etype == "conversation.item.input_audio_transcription.completed":
                item_id = event.get("item_id", "")
                transcript = event.get("transcript", "").strip()
                if transcript and item_id:
                    # Always overwrite — xAI reuses the same item_id across
                    # multiple commits for one utterance, each time with a
                    # more complete transcript.  We flush on
                    # response.output_audio_transcript.done so this accumulates
                    # freely until the agent actually responds.
                    self._pending_user_transcripts[item_id] = transcript

            elif etype == "response.mcp_call_arguments.done":
                if self.on_tool_call:
                    self.on_tool_call(
                        event.get("name", ""),
                        event.get("arguments", ""),
                    )

            elif etype == "response.mcp_call.completed":
                if self.on_tool_event:
                    self.on_tool_event("mcp_call.completed", event.get("name", ""))

            elif etype == "response.mcp_call.failed":
                log.warning("MCP call failed: %s", event.get("name", ""))
                if self.on_tool_event:
                    self.on_tool_event("mcp_call.failed", event.get("name", ""))

            elif etype == "error":
                # xAI sent an error — log it loudly and surface to event log
                code = event.get("code", "")
                msg  = event.get("message", json.dumps(event)[:200])
                log.error("xAI error [%s]: %s", code, msg)
                if self.on_tool_event:
                    self.on_tool_event("error", f"[{code}] {msg}")

            elif etype == "response.function_call_arguments.delta":
                pass  # streaming chunks — full payload arrives on .done

            elif etype == "response.function_call_arguments.done":
                # Built-in function calls (web_search, x_search) — not MCP but same UX
                if self.on_tool_call:
                    self.on_tool_call(
                        event.get("name", ""),
                        event.get("arguments", ""),
                    )

            elif etype == "mcp_list_tools.completed":
                count = len(event.get("tools", []))
                log.info("MCP tools listed: %d", count)
                if self.on_tool_event:
                    self.on_tool_event("mcp_list_tools.completed", str(count))

            elif etype == "response.output_audio_transcript.done":
                # agent's full transcript for this response segment — emit as one
                # complete entry and use it as the flush trigger for pending user
                # transcripts (ASR has had maximum time to settle by now)
                transcript = event.get("transcript", "").strip()
                _flush_all_pending()
                if transcript and self.on_transcript:
                    self.on_transcript("agent", transcript)

            elif etype == "response.done":
                if self.on_tool_event:
                    self.on_tool_event("response.done", "")

            elif etype == "response.created":
                if self.on_tool_event:
                    self.on_tool_event("response.created", "")

            elif etype.startswith("response.mcp") or etype.startswith("mcp_"):
                detail = json.dumps(event)[:200]
                log.info("Unhandled MCP event: %s — %s", etype, detail)
                if self.on_tool_event:
                    self.on_tool_event(etype, detail)

            elif etype in ("response.output_item.added", "response.output_item.done"):
                # May contain tool call items — log the item type and name
                item = event.get("item", {})
                itype = item.get("type", "")
                name = item.get("name", "") or item.get("call_id", "")
                detail = f"item_type={itype} name={name} raw={json.dumps(item)[:150]}"
                log.info("Output item: %s", detail)
                if self.on_tool_event:
                    self.on_tool_event(etype, detail)
                # If this is a completed tool call item, extract and forward it
                if etype == "response.output_item.done" and itype in ("mcp_call", "function_call"):
                    if self.on_tool_call:
                        self.on_tool_call(name, json.dumps(item.get("arguments", item.get("input", ""))))

            elif etype in (
                # VAD plumbing — no action, just volume
                "input_audio_buffer.committed",          # VAD cut confirmation; we rely on speech_stopped
                "input_audio_buffer.speech_started",     # logged only (filtered above)
                "input_audio_buffer.speech_stopped",     # logged only (filtered above)
                # Conversation lifecycle — we track items via output_item.done instead
                "conversation.created",
                "conversation.item.added",
                # Content-part lifecycle — transcripts arrive on output_audio_transcript.done
                "response.content_part.added",
                "response.content_part.done",
                # Transcript deltas — full transcript arrives on output_audio_transcript.done
                "conversation.item.input_audio_transcription.delta",
                "response.output_audio_transcript.delta",
                # Ping — keep-alive, no action
                "ping",
            ):
                pass  # intentionally ignored — see inline comments above

            else:
                # Catch-all: forward unknown event types to hearth for diagnosis
                if etype and self.on_tool_event:
                    self.on_tool_event(f"unknown:{etype}", json.dumps(event)[:150])

    # ------------------------------------------------------------------ #
    #  Audio output queue → speakers                                      #
    # ------------------------------------------------------------------ #

    async def _play_loop(self):
        import sounddevice as sd
        loop = asyncio.get_event_loop()
        stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
        )
        stream.start()
        try:
            while self._running:
                try:
                    chunk = self._audio_out_q.get_nowait()
                    await loop.run_in_executor(None, stream.write, chunk)
                except queue.Empty:
                    await asyncio.sleep(0.01)
        finally:
            stream.stop()
            stream.close()
