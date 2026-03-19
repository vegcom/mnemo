"""Append-only JSONL log of conversation turns and tool calls.

Schemas (one JSON object per line):

  conversation.jsonl:
    {"role": "user"|"agent", "text": "...", "ts": "...", "mode": "text"|"voice", "person": "Alice"} (person optional)

  tool_turns.jsonl:
    {"ts": "...", "tool": "...", "arguments": "...", "result": "...", "response_id": "..."|null}

Paths:
  MNEMO_CONVERSATION_JSONL → /etc/mnemo/conversation.jsonl
  MNEMO_TOOL_TURNS_JSONL   → /etc/mnemo/tool_turns.jsonl
"""
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_PATH      = Path.home() / ".config" / "mnemo" / "conversation.jsonl"
_DEFAULT_TOOL_PATH = Path.home() / ".config" / "mnemo" / "tool_turns.jsonl"
_lock      = threading.Lock()
_tool_lock = threading.Lock()


def _path() -> Path:
    env = os.environ.get("MNEMO_CONVERSATION_JSONL", "")
    return Path(env) if env else _DEFAULT_PATH


def _tool_path() -> Path:
    env = os.environ.get("MNEMO_TOOL_TURNS_JSONL", "")
    return Path(env) if env else _DEFAULT_TOOL_PATH


def append_turn(role: str, text: str, mode: str = "text", person: str | None = None) -> None:
    """Append a single turn to conversation.jsonl. Thread-safe, best-effort."""
    if not text:
        return
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rec: dict = {
        "role": role,
        "text": text,
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "mode": mode,
    }
    if person:
        rec["person"] = person
    line = json.dumps(rec)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def append_tool_turn(tool: str, arguments: str, result: str = "", response_id: str | None = None) -> None:
    """Append a tool call to tool_turns.jsonl. Thread-safe, best-effort."""
    path = _tool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "ts":          datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "tool":        tool,
        "arguments":   arguments,
        "result":      result,
        "response_id": response_id,
    })
    with _tool_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
