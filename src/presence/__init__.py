"""
mnemo conversation history — JSONL chat log + qdrant semantic index.

Mirrors cozy-presence pattern: JSONL is source of truth, qdrant is a
read-optimised view that can be rebuilt from it.

Usage:
    from presence import PresenceStore
    store = PresenceStore()
    store.append("user", "what's the weather like?")
    store.append("assistant", "I'll check that for you.")
    hits = store.search("weather")
"""

from .store import PresenceStore

__all__ = ["PresenceStore"]
