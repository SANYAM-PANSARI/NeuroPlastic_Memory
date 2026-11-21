"""Embedding match for the entry step: a new error -> the stored err nodes it means.

Word overlap misses paraphrases ("connection pool exhausted" vs "no free DB connections").
Embeddings compare meaning instead of words.

Switch back to word overlap any time:  $env:NAVMEM_ENTRY = "overlap"
"""
from __future__ import annotations

import os

MODEL_NAME = os.environ.get("NAVMEM_EMBED_MODEL", "all-MiniLM-L6-v2")  # ~80 MB, CPU is fine
THRESHOLD = 0.55   # starting guess for cosine similarity; tune on real symptoms

_model = None
_cache: dict[str, list[float]] = {}   # text -> unit vector, so each err node is embedded once


def enabled() -> bool:
    if os.environ.get("NAVMEM_ENTRY", "embed").lower() == "overlap":
        return False
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False   # not installed: recall falls back to word overlap
    return True


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def vectors(texts: list[str]) -> list[list[float]]:
    missing = [t for t in dict.fromkeys(texts) if t not in _cache]
    if missing:
        embs = _get_model().encode(missing, normalize_embeddings=True)
        for t, v in zip(missing, embs):
            _cache[t] = [float(x) for x in v]
    return [_cache[t] for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))   # vectors are already unit length


def best_matches(symptom: str, candidates: dict[str, str], threshold: float = THRESHOLD) -> dict[str, float]:
    """candidates: node_id -> text. Returns node_id -> similarity for those at or above threshold."""
    if not candidates:
        return {}
    ids = list(candidates)
    vecs = vectors([symptom] + [candidates[i] for i in ids])
    sym, rest = vecs[0], vecs[1:]
    out = {}
    for nid, v in zip(ids, rest):
        s = cosine(sym, v)
        if s >= threshold:
            out[nid] = round(s, 4)
    return out
