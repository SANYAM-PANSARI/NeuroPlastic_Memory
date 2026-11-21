"""M4: weaken hints that did not help, kill links that keep misleading, keep the reason."""
from __future__ import annotations

from navmem.recall import Hint
from navmem.store import Store

DELTA_HELPED = 0.1
DELTA_UNHELPFUL = -0.1
KILL_AFTER = 3


def feedback(store: Store, *, task_id: str, hints: list[Hint], read_paths: set[str],
             fixed_nodes: list[str], success: bool) -> dict:
    """Score each hint the agent actually followed (read its file).

    helped:   the run succeeded and the hint pointed at what the fix changed
    on path:  the hint was not the fix itself, but its path ran THROUGH the fix (e.g. "read
              config.yaml" reached via the learned link to AUTH_POOL_SIZE). It led toward the
              answer, so nothing on that path is punished.
    misled:   the agent followed it and neither the hint nor its path reached the fix
    Hints the agent ignored teach nothing."""
    report = {"helped": [], "on_path": [], "misled": [], "killed": []}
    for h in hints:
        path = h.pointer.split("#")[0]
        if path not in read_paths:
            continue
        nodes_on_path = set()
        for eid in h.edge_ids:
            e = store.get_edge_by_id(eid)
            if e:
                nodes_on_path |= {e.src, e.dst}
        if success and h.node_id not in fixed_nodes and nodes_on_path & set(fixed_nodes):
            report["on_path"].append(h.pointer)
            continue
        if success and h.node_id in fixed_nodes:
            for eid in h.edge_ids:
                e = store.get_edge_by_id(eid)
                if e and e.source == "learned":
                    store.upsert_edge(e.src, e.dst, e.type, delta=DELTA_HELPED, trust="verified",
                                      actor="feedback", task_id=task_id)
            report["helped"].append(h.pointer)
        elif h.node_id not in fixed_nodes:
            reason = f"hint {h.pointer} was followed but the fix was elsewhere ({', '.join(fixed_nodes) or 'no fix'})"
            for eid in h.edge_ids:
                if store.mislead(eid, reason, DELTA_UNHELPFUL, KILL_AFTER, task_id=task_id):
                    report["killed"].append(eid)
            report["misled"].append(h.pointer)
    return report
