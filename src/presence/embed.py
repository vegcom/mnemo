"""Embeddings — local sentence-transformers or remote OpenAI-compatible server.

Env vars:
  PRESENCE_EMBED_MODEL   model name (default: sentence-transformers/msmarco-MiniLM-L12-v3)
  PRESENCE_EMBED_URL     remote embedding server base URL (OpenAI-compatible /v1/embeddings)
                         tried first; local sentence-transformers used as fallback if unset
  PRESENCE_EMBED_DIM     explicit vector dimension override (required when using remote
                         without also installing sentence-transformers locally)
"""

import os

_model = None
_model_name = None
_remote_dim: int | None = None


def _get_model_name() -> str:
    return os.environ.get(
        "PRESENCE_EMBED_MODEL",
        "sentence-transformers/msmarco-MiniLM-L12-v3",
    )


def _embed_remote(text: str) -> list[float] | None:
    url = os.environ.get("PRESENCE_EMBED_URL")
    if not url:
        return None
    import json
    import urllib.request

    payload = json.dumps({"model": _get_model_name(), "input": [text]}).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data["data"][0]["embedding"]
    except Exception:
        return None


def _get_model():
    global _model, _model_name
    target = _get_model_name()
    if _model is not None and _model_name == target:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(target)
        _model_name = target
        return _model
    except ImportError:
        return None


def available() -> bool:
    if os.environ.get("PRESENCE_EMBED_URL"):
        return True
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def embed_text(text: str) -> list[float] | None:
    vec = _embed_remote(text)
    if vec is not None:
        return vec
    model = _get_model()
    if model is None:
        return None
    return model.encode(text, convert_to_numpy=True).tolist()


def dimension() -> int:
    global _remote_dim
    if explicit := os.environ.get("PRESENCE_EMBED_DIM"):
        return int(explicit)
    if not os.environ.get("PRESENCE_EMBED_URL"):
        model = _get_model()
        if model is not None:
            return model.get_sentence_embedding_dimension()
    # Remote path: probe with a short string and cache the result.
    if _remote_dim is None:
        vec = _embed_remote("probe")
        _remote_dim = len(vec) if vec else 384
    return _remote_dim
