"""Store: the only module that touches SQLite.

Nodes are locations (pointers), edges are connections, events log every change.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, pointer TEXT NOT NULL,
  description TEXT, embedding BLOB, content_hash TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY, src TEXT NOT NULL REFERENCES nodes(id),
  dst TEXT NOT NULL REFERENCES nodes(id), type TEXT NOT NULL, why TEXT,
  strength REAL NOT NULL DEFAULT 1.0, trust TEXT NOT NULL, source TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'live', dead_reason TEXT,
  misled_count INTEGER NOT NULL DEFAULT 0, last_used TEXT, last_verified TEXT,
  UNIQUE (src, dst, type));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, edge_id INTEGER REFERENCES edges(id),
  action TEXT NOT NULL, delta REAL, actor TEXT, task_id TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, text TEXT NOT NULL, started_at TEXT NOT NULL,
  ended_at TEXT, outcome TEXT, verifier TEXT);
CREATE TABLE IF NOT EXISTS trace (
  task_id TEXT NOT NULL REFERENCES tasks(id), step INTEGER NOT NULL,
  tool TEXT NOT NULL, args TEXT NOT NULL, node_ids TEXT, terms TEXT,
  ts TEXT NOT NULL, PRIMARY KEY (task_id, step));
"""

STRENGTH_CAP = 5.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Node:
    id: str
    type: str
    pointer: str
    description: str = ""
    content_hash: str | None = None


@dataclass
class Edge:
    id: int
    src: str
    dst: str
    type: str
    why: str | None
    strength: float
    trust: str
    source: str
    status: str
    dead_reason: str | None
    misled_count: int


class DeadEdgeError(Exception):
    """Raised when someone tries to re-learn a link that was killed."""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)  # MCP SDKs call tools from worker threads
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- nodes ----
    def upsert_node(self, node: Node) -> None:
        t = now()
        self.db.execute(
            """INSERT INTO nodes (id, type, pointer, description, content_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET pointer=excluded.pointer,
                 description=excluded.description, content_hash=excluded.content_hash,
                 updated_at=excluded.updated_at""",
            (node.id, node.type, node.pointer, node.description, node.content_hash, t, t))
        self.db.commit()

    def get_node(self, node_id: str) -> Node | None:
        r = self.db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if r is None:
            return None
        return Node(r["id"], r["type"], r["pointer"], r["description"] or "", r["content_hash"])

    # ---- edges ----
    def _edge(self, r) -> Edge:
        return Edge(r["id"], r["src"], r["dst"], r["type"], r["why"], r["strength"],
                    r["trust"], r["source"], r["status"], r["dead_reason"], r["misled_count"])

    def get_edge(self, src: str, dst: str, type: str) -> Edge | None:
        r = self.db.execute("SELECT * FROM edges WHERE src=? AND dst=? AND type=?",
                            (src, dst, type)).fetchone()
        return self._edge(r) if r else None

    def is_dead(self, src: str, dst: str, type: str) -> bool:
        e = self.get_edge(src, dst, type)
        return e is not None and e.status == "dead"

    def upsert_edge(self, src: str, dst: str, type: str, *, delta: float = 0.0,
                    why: str | None = None, trust: str = "provisional", source: str = "learned",
                    actor: str = "system", task_id: str | None = None) -> Edge:
        """Create an edge at strength 1.0, or add `delta` to an existing one (capped)."""
        if self.is_dead(src, dst, type):
            raise DeadEdgeError(f"{src} -> {dst} ({type}) was killed")
        existing = self.get_edge(src, dst, type)
        if existing is None:
            cur = self.db.execute(
                """INSERT INTO edges (src, dst, type, why, strength, trust, source, last_verified)
                   VALUES (?, ?, ?, ?, 1.0, ?, ?, ?)""",
                (src, dst, type, why, trust, source, now()))
            self.log_event(cur.lastrowid, "add", 1.0, actor, task_id, why)
        else:
            new_strength = max(0.0, min(STRENGTH_CAP, existing.strength + delta))
            self.db.execute(
                "UPDATE edges SET strength=?, why=COALESCE(?, why), trust=?, last_verified=? WHERE id=?",
                (new_strength, why, _better_trust(existing.trust, trust), now(), existing.id))
            self.log_event(existing.id, "strengthen" if delta >= 0 else "weaken",
                           delta, actor, task_id, why)
        self.db.commit()
        return self.get_edge(src, dst, type)

    def edges_from(self, node_id: str, live_only: bool = True) -> list[Edge]:
        q = "SELECT * FROM edges WHERE src = ?" + (" AND status = 'live'" if live_only else "")
        return [self._edge(r) for r in self.db.execute(q, (node_id,))]

    def neighbors(self, node_id: str) -> list[tuple[Edge, str]]:
        """Live edges to walk from node_id. Static edges go both ways (code structure is
        symmetric for navigation); learned edges only forward (they record what led where)."""
        out = [(e, e.dst) for e in self.edges_from(node_id)]
        for r in self.db.execute(
                "SELECT * FROM edges WHERE dst = ? AND status = 'live' AND source = 'static'", (node_id,)):
            e = self._edge(r)
            out.append((e, e.src))
        return out

    def get_edge_by_id(self, edge_id: int) -> Edge | None:
        r = self.db.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
        return self._edge(r) if r else None

    def mislead(self, edge_id: int, reason: str, delta: float, kill_after: int,
                task_id: str | None = None) -> bool:
        """A hint through this edge did not help. Weaken it; kill it after `kill_after` misleads.
        Returns True if the edge died."""
        e = self.get_edge_by_id(edge_id)
        if e is None or e.status == "dead" or e.source == "static":
            return False   # static edges reflect code structure; they are rebuilt, not killed
        count = e.misled_count + 1
        self.db.execute("UPDATE edges SET misled_count=?, strength=MAX(0, strength+?) WHERE id=?",
                        (count, delta, edge_id))
        self.log_event(edge_id, "weaken", delta, "system", task_id, reason)
        self.db.commit()
        if count >= kill_after:
            self.kill_edge(edge_id, f"misled {count} times; last: {reason}", task_id=task_id)
            return True
        return False

    def kill_edge(self, edge_id: int, reason: str, actor: str = "system",
                  task_id: str | None = None) -> None:
        self.db.execute("UPDATE edges SET status='dead', dead_reason=? WHERE id=?", (reason, edge_id))
        self.log_event(edge_id, "kill", None, actor, task_id, reason)
        self.db.commit()

    # ---- events ----
    def log_event(self, edge_id, action, delta, actor, task_id, reason) -> None:
        self.db.execute(
            "INSERT INTO events (ts, edge_id, action, delta, actor, task_id, reason) VALUES (?,?,?,?,?,?,?)",
            (now(), edge_id, action, delta, actor, task_id, reason))

    def events_for(self, edge_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events WHERE edge_id = ? ORDER BY id", (edge_id,))]


TRUST_RANK = {"provisional": 0, "static": 1, "jev": 2, "verified": 3}


def _better_trust(a: str, b: str) -> str:
    """Trust only goes up through learning; it never silently drops."""
    return a if TRUST_RANK.get(a, 0) >= TRUST_RANK.get(b, 0) else b
