"""
mnemo — chat + voice TUI. Connects to hearth daemon for agent/history.

Usage:
    python app.py            # text mode
    python app.py --voice    # start with voice active
"""
import argparse
import json
import logging
import os
import socket
import threading

from rich.markup import escape as _escape
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, TextArea, RichLog, Label
from textual.containers import Horizontal, Vertical
from textual import work
from textual.binding import Binding

from mnemo.voice import VoiceSession

_log_path = os.getenv("MNEMO_LOG_PATH", "")
if _log_path:
    _fh = logging.FileHandler(_log_path, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(name)s  %(message)s"))
    logging.getLogger().addHandler(_fh)
    logging.getLogger().setLevel(logging.INFO)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  StatusBlob — minimal presence indicator, future sprite anchor      #
# ------------------------------------------------------------------ #

_BLOB_STATES: dict[str, tuple[str, str]] = {
    "disconnected": ("○", "dim"),
    "idle":         ("◉", "cyan dim"),
    "listening":    ("◎", "bold green"),
    "thinking":     ("◌", "bold yellow"),
    "speaking":     ("●", "bold cyan"),
}

# xAI voice event type → blob state
_VOICE_EVENT_STATE: dict[str, str] = {
    "unknown:input_audio_buffer.speech_started": "listening",
    "unknown:input_audio_buffer.speech_stopped": "thinking",
    "response.created":                          "thinking",
    "unknown:response.output_audio.done":        "listening",  # audio stream ended — more accurate than response.done
}


def _blob_markup(state: str, frame: int) -> str:
    glyph, color = _BLOB_STATES.get(state, ("○", "dim"))
    if state in ("idle", "thinking") and frame:
        color = "dim"
    return f"[{color}]{glyph}[/]"


# ------------------------------------------------------------------ #
#  Hearth IPC client                                                  #
# ------------------------------------------------------------------ #

class HearthClient:
    """Synchronous IPC client for hearth daemon."""

    def __init__(self) -> None:
        host  = os.getenv("MNEMO_HEARTH_HOST", "127.0.0.1")
        port  = int(os.getenv("MNEMO_HEARTH_PORT", "7744"))
        token  = os.getenv("APP_AUTH_TOKEN", "")
        person = os.getenv("MNEMO_CLIENT_PERSON", "").strip() or None
        self._sock = socket.create_connection((host, port), timeout=300)
        self._sock.settimeout(300)
        self._file = self._sock.makefile("r", encoding="utf-8")
        self._lock = threading.Lock()
        connect_msg: dict = {"type": "connect", "token": token}
        if person:
            connect_msg["person"] = person
        self._send(connect_msg)
        msg = self._recv()
        self.history: list[dict] = msg.get("turns", []) if msg else []
        self.voice_tools: list[dict] = msg.get("voice_tools", []) if msg else []
        self.continuity: str = msg.get("continuity", "") if msg else ""

    def _send(self, obj: dict) -> None:
        self._sock.sendall((json.dumps(obj) + "\n").encode())

    def _recv(self) -> dict | None:
        line = self._file.readline()
        return json.loads(line) if line else None

    def stream_message(self, content: str):
        """Send a text message and yield response tokens."""
        with self._lock:
            self._send({"type": "message", "content": content})
            while True:
                msg = self._recv()
                if msg is None or msg["type"] == "done":
                    break
                if msg["type"] == "token":
                    yield msg["content"]

    def send_transcript(self, role: str, text: str) -> None:
        self._send({"type": "transcript", "role": role, "text": text})

    def send_tool_call(self, tool: str, arguments: str) -> None:
        self._send({"type": "tool_call", "tool": tool, "arguments": arguments})

    def send_tool_event(self, event_type: str, detail: str) -> None:
        self._send({"type": "tool_event", "event_type": event_type, "detail": detail})

    def request_voice_start(self, by: str = "user") -> str:
        """Signal voice start; returns injection snippet from hearth."""
        with self._lock:
            self._send({"type": "voice_start", "by": by})
            msg = self._recv()
            return (msg or {}).get("snippet", "")

    def send_voice_stop(self, by: str = "user") -> None:
        """Signal voice stop to hearth (fire-and-forget)."""
        self._send({"type": "voice_stop", "by": by})

    def close(self) -> None:
        try:
            self._send({"type": "disconnect"})
        except Exception:
            pass
        self._sock.close()


# ------------------------------------------------------------------ #
#  Layout widgets                                                     #
# ------------------------------------------------------------------ #

class ChatPanel(RichLog):
    DEFAULT_CSS = "ChatPanel { border: solid $primary; height: 100%; width: 2fr; }"


class ToolPanel(RichLog):
    DEFAULT_CSS = "ToolPanel { border: solid $secondary; height: 1fr; }"


class EventLog(RichLog):
    DEFAULT_CSS = "EventLog { border: solid $warning; height: 1fr; }"


# ------------------------------------------------------------------ #
#  App                                                                #
# ------------------------------------------------------------------ #

class MnemoApp(App):
    """mnemo chat TUI."""

    BINDINGS = [
        Binding("ctrl+s", "submit_message", "Send", show=True, priority=True),
        Binding("v", "toggle_voice", "Voice", show=True, priority=True),
        Binding("t", "toggle_tools", "Tools", show=True, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=True),
    ]

    CSS = """
    Screen { layout: vertical; }
    #body  { height: 1fr; }
    #right { width: 1fr; }
    #blob { width: 3; }
    #voice_status { width: 1fr; text-align: right; color: $secondary; }
    #status_row { height: 1; }
    TextArea { dock: bottom; height: 4; }
    """

    def __init__(self, voice: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.client = HearthClient()
        self._voice_active = False
        self._voice_session: VoiceSession | None = None
        self._voice_thread: threading.Thread | None = None
        self._start_voice = voice
        self._blob_state = "disconnected"
        self._blob_frame = 0
        self._blob_queue: list[str] = []
        self._blob_tick_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="status_row"):
            yield Label("○", id="blob")
            yield Label("", id="voice_status")
        with Horizontal(id="body"):
            yield ChatPanel(highlight=True, markup=True, id="chat")
            with Vertical(id="right"):
                yield ToolPanel(highlight=True, markup=True, id="tools")
                yield EventLog(highlight=True, markup=True, id="events")
        yield TextArea(id="input_area")
        yield Footer()

    def on_mount(self) -> None:
        chat = self.query_one("#chat", ChatPanel)
        for turn in self.client.history:
            color = "cyan" if turn["role"] == "agent" else "green"
            name  = "agent" if turn["role"] == "agent" else "you"
            chat.write(f"[bold {color}]{name}[/] {_escape(turn['content'])}")
        chat.write("[bold cyan]agent[/] is online. Say hi 💜")
        self.query_one("#tools", ToolPanel).write("[dim]MCP tool calls[/]")
        self.query_one("#events", EventLog).write("[dim]voice events[/]")
        self.set_interval(0.15, self._blob_tick)
        self._set_blob_state("idle")
        self.query_one(TextArea).focus()
        if self._start_voice:
            self.action_toggle_voice()

    async def on_unmount(self) -> None:
        self.client.close()

    async def action_submit_message(self) -> None:
        area = self.query_one("#input_area", TextArea)
        msg = area.text.strip()
        if not msg:
            return
        area.clear()
        self.query_one("#chat", ChatPanel).write(f"[bold green]you[/] {_escape(msg)}")
        self.query_one("#tools", ToolPanel).write(f"[dim]← {_escape(msg[:40])}[/]")
        self._reply(msg)

    @work(thread=True)
    def _reply(self, msg: str) -> None:
        log.info("_reply start: %r", msg[:80])
        self.call_from_thread(self._set_blob_state, "thinking")
        reply = ""
        try:
            for token in self.client.stream_message(msg):
                reply += token
        except Exception:
            log.exception("_reply error")
            self.call_from_thread(self._set_blob_state, "idle")
            return
        log.info("_reply done (%d chars)", len(reply))
        self.call_from_thread(self._set_blob_state, "speaking")
        self.call_from_thread(
            self.query_one("#chat", ChatPanel).write,
            f"[bold cyan]agent[/] {_escape(reply)}",
        )
        self.call_from_thread(self._set_blob_state, "idle")

    # ------------------------------------------------------------------ #
    #  Voice                                                               #
    # ------------------------------------------------------------------ #

    def _blob_tick(self) -> None:
        self._blob_tick_count += 1
        # pop one queued state per tick (~150ms visibility per state)
        if self._blob_queue:
            self._blob_state = self._blob_queue.pop(0)
        # pulse every 4 ticks ≈ 600ms
        if self._blob_tick_count % 4 == 0:
            self._blob_frame ^= 1
        self.query_one("#blob", Label).update(_blob_markup(self._blob_state, self._blob_frame))

    def _set_blob_state(self, state: str) -> None:
        log.info("blob state → %s", state)
        # deduplicate: skip if same as last queued or current state
        last = self._blob_queue[-1] if self._blob_queue else self._blob_state
        if state != last:
            self._blob_queue.append(state)

    def action_toggle_tools(self) -> None:
        col = self.query_one("#right")
        col.display = not col.display

    def action_toggle_voice(self) -> None:
        if self._voice_active:
            self._stop_voice()
        else:
            self._start_voice_session()

    def _voice_run(self) -> None:
        try:
            self._voice_session.start()
        except Exception:
            log.exception("voice session error")
            self.call_from_thread(self._stop_voice)

    def _start_voice_session(self) -> None:
        snippet = self.client.request_voice_start()
        self._voice_session = VoiceSession(
            voice_tools=self.client.voice_tools or None,
            continuity=self.client.continuity or None,
            injection_snippet=snippet or None,
            on_transcript=self._on_voice_transcript,
            on_tool_event=self._on_voice_tool,
            on_tool_call=self._on_voice_tool_call,
        )
        self._voice_thread = threading.Thread(
            target=self._voice_run, daemon=True
        )
        self._voice_thread.start()
        self._voice_active = True
        self._set_voice_label(True)
        self._set_blob_state("listening")

    def _stop_voice(self) -> None:
        if self._voice_session:
            self._voice_session.stop()
        self.client.send_voice_stop()
        self._voice_session = None
        self._voice_active = False
        self._set_voice_label(False)
        self._set_blob_state("idle")

    def _set_voice_label(self, active: bool) -> None:
        label = self.query_one("#voice_status", Label)
        label.update("[bold red]● voice[/]" if active else "")

    def _on_voice_transcript(self, role: str, text: str) -> None:
        self.client.send_transcript(role, text)
        color = "cyan" if role == "agent" else "green"
        # agent transcript = agent just spoke; user transcript = back to listening
        if role == "agent":
            self.call_from_thread(self._set_blob_state, "speaking")
        self.call_from_thread(
            self.query_one("#chat", ChatPanel).write,
            f"[bold {color}]{role}[/] {_escape(text)}",
        )

    def _on_voice_tool(self, event_type: str, detail: str) -> None:
        self.client.send_tool_event(event_type, detail)
        # drive blob state from xAI voice events
        if new_state := _VOICE_EVENT_STATE.get(event_type):
            self.call_from_thread(self._set_blob_state, new_state)
        self.call_from_thread(
            self.query_one("#events", EventLog).write,
            f"[yellow]♪[/] [dim]{_escape(event_type)}[/]",
        )

    def _on_voice_tool_call(self, tool: str, arguments: str) -> None:
        self.client.send_tool_call(tool, arguments)
        self.call_from_thread(
            self.query_one("#tools", ToolPanel).write,
            f"[yellow]→[/] [bold]{_escape(tool)}[/] [dim]{_escape(arguments[:60])}[/]",
        )


def main():
    parser = argparse.ArgumentParser(description="mnemo chat + voice agent")
    parser.add_argument("--voice", action="store_true", help="Start with voice active")
    parser.add_argument("message", nargs="?", help="Send a one-shot message and print the reply")
    args = parser.parse_args()
    if args.message:
        client = HearthClient()
        try:
            for token in client.stream_message(args.message):
                print(token, end="", flush=True)
            print()
        finally:
            client.close()
        return
    MnemoApp(voice=args.voice).run()


if __name__ == "__main__":
    main()
