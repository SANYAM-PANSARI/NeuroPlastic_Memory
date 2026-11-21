"""Recall: symptom -> ranked list of "read X, because Y". No LLM; database lookups and arithmetic only."""
from __future__ import annotations

from dataclasses import dataclass

from navmem import embed
from navmem.normalize import normalize_template, tokens
from navmem.store import Store

TRUST_W = {"verified": 1.0, "jev": 0.7, "static": 0.6, "provisional": 0.3}
HOP_DISCOUNT = 0.5
MAX_HOPS = 3
MIN_SCORE = 0.01   # starting guess; tuned on the benchmark
HUB_DEGREE = 2    # nodes called by more functions than this get discounted
TARGET_TYPES = {"cfg", "fn", "table", "file"}


@dataclass
class Hint:
    pointer: str
    why: str
    score: float
    path: list[str]
    edge_ids: list[int]
    node_id: str = ""


def edge_factor(strength: float, trust: str) -> float:
    """Strength 1 -> 0.6x trust, strength 5 -> 1.0x trust."""
    return TRUST_W.get(trust, 0.3) * (0.5 + 0.1 * strength)


def entry_nodes(store: Store, symptom: str, suspects: list[str] | None = None) -> dict[str, float]:
    """Find where to start the walk. Default: embedding similarity (navmem/embed.py).
    Falls back to word overlap if NAVMEM_ENTRY=overlap or sentence-transformers is missing."""
    rows = list(store.db.execute("SELECT id, type, description FROM nodes"))
    out: dict[str, float] = {}
    if embed.enabled():
        errs = {r["id"]: normalize_template(r["id"][4:]) for r in rows if r["type"] == "err"}
        out.update(embed.best_matches(normalize_template(symptom), errs))
    else:
        sym = tokens(symptom)
        for r in rows:
            if r["type"] == "err":
                t = tokens(r["id"][4:])
                if t:
                    overlap = len(t & sym) / len(t)
                    if overlap >= 0.6:
                        out[r["id"]] = overlap
    for r in rows:
        for s in suspects or []:
            if s.lower() in r["id"].lower():
                out[r["id"]] = max(out.get(r["id"], 0), 0.8)
    return out


def degrees(store: Store) -> dict[str, int]:
    deg: dict[str, int] = {}
    # number of distinct callers: utilities like log() are called from everywhere
    for r in store.db.execute("SELECT dst FROM edges WHERE status = 'live' AND type = 'calls'"):
        deg[r["dst"]] = deg.get(r["dst"], 0) + 1
    return deg


def hub_penalty(deg: int) -> float:
    """Nodes linked to almost everything (log, load_config) say little about any one bug."""
    return min(1.0, HUB_DEGREE / deg) if deg else 1.0


def recall(store: Store, symptom: str, suspects: list[str] | None = None, k: int = 5) -> list[Hint]:
    entries = entry_nodes(store, symptom, suspects)
    deg = degrees(store)
    best: dict[str, tuple[float, list[str], list[int]]] = {}
    # frontier: (node, score, hops, path of human-readable reasons)
    frontier = [(n, s, 0, [], []) for n, s in entries.items()]
    seen = set(entries)
    for _ in range(MAX_HOPS):
        nxt = []
        for node_id, score, hops, path, eids in frontier:
            for e, other in store.neighbors(node_id):
                if other in seen:
                    continue
                s = score * edge_factor(e.strength, e.trust) * (HOP_DISCOUNT if hops else 1.0) * hub_penalty(deg.get(other, 0))
                p = path + [e.why or f"{e.type} {other}"]
                ids = eids + [e.id]
                nxt.append((other, s, hops + 1, p, ids))
                if s > best.get(other, (0, [], []))[0]:
                    best[other] = (s, p, ids)
        seen |= {n for n, *_ in nxt}
        frontier = nxt
    hints = []
    for node_id, (s, p, ids) in sorted(best.items(), key=lambda x: -x[1][0]):
        n = store.get_node(node_id)
        if n and n.type in TARGET_TYPES and s >= MIN_SCORE:
            hints.append(Hint(n.pointer, "; ".join(p), round(s, 4), p, ids, node_id))
        if len(hints) == k:
            break
    return hints


def readable(pointer: str) -> str:
    """'services/common.py#load_config' -> 'read services/common.py (look at load_config)'.
    The raw '#' form made a model invent paths like services/common/load_config.py."""
    path, _, part = pointer.partition("#")
    return f"read {path} (look at {part})" if part else f"read {path}"


def format_hints(hints: list[Hint]) -> str:
    if not hints:
        return ""
    lines = [f"- {readable(h.pointer)}: {h.path[-1]}" for h in hints]
    return "Hints from past navigation (may be wrong, verify by reading):\n" + "\n".join(lines)
