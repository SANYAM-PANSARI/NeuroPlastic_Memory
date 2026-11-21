"""M3: turn a verified run into links.

Only a run whose tests pass teaches the graph. It learns two kinds of edges:
- causes:  symptom (err node) -> each location the agent's fix changed
- led_to:  file A -> file B when something the agent saw in A sent it to B
"""
from __future__ import annotations

import yaml

from navmem.normalize import normalize_template
from navmem.recall import entry_nodes
from navmem.store import DeadEdgeError, Node, Store

DELTA_VERIFIED = 0.3
DELTA_LEDTO = 0.15
LEDTO_WINDOW = 3
STOP_TERMS = {"config", "error", "user", "data", "self", "return", "import", "from", "class",
              "def", "order", "orders", "true", "false", "none", "test", "tests", "services"}


def symptom_nodes(store: Store, symptom: str) -> list[str]:
    """The err nodes this symptom maps to; creates one if this symptom is new."""
    found = list(entry_nodes(store, symptom))
    found = [n for n in found if n.startswith("err:")]
    if found:
        return found
    nid = f"err:{normalize_template(symptom)}"
    store.upsert_node(Node(nid, "err", "symptom", f"reported symptom: {normalize_template(symptom)}"))
    return [nid]


def file_node(store: Store, path: str) -> str:
    path = path.replace("\\", "/").lstrip("./")
    nid = f"file:{path}"
    if store.get_node(nid) is None:
        store.upsert_node(Node(nid, "file", path, f"file {path}"))
    return nid


def fixed_locations(store: Store, edits: list[dict], config_before: str | None,
                    config_after: str | None = None) -> list[str]:
    """Nodes the fix changed: config keys whose value changed, else the edited file."""
    out = []
    for e in edits:
        if e["path"].endswith("config.yaml") and config_before is not None:
            before = _leaves(yaml.safe_load(config_before) or {})
            after = _leaves(yaml.safe_load(config_after) or {}) if config_after else None
            changed = [k for k in before if after is not None and before[k] != after.get(k)]
            if not changed:  # fall back to keys named in the edit text
                changed = [k for k in before if k in e["find"] or k in e["replace"]]
            for k in changed:
                nid = f"cfg:{k}"
                if store.get_node(nid) is None:
                    store.upsert_node(Node(nid, "cfg", f"config.yaml#{k}", f"config key {k}"))
                out.append(nid)
        else:
            out.append(file_node(store, e["path"]))
    return list(dict.fromkeys(out))


def _leaves(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        out.update(_leaves(v) if isinstance(v, dict) else {k: v})
    return out


def ledto_pairs(calls: list[dict]) -> list[tuple[str, str, str]]:
    """(from_path, to_path, why) when a read showed a specific term that the next step followed.

    Two patterns: read A, then grep a term seen in A, then read B; or read A, then read B whose
    file name appeared in A. Only specific terms count (identifiers, file names, config keys)."""
    pairs, recent = [], []          # recent = [(path, terms)] of the last few reads
    pending_term = None             # a grep term that came from a recent read
    for c in calls:
        if c["tool"] == "read_file":
            path = str(c["args"].get("path", ""))
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            for src, terms in reversed(recent[-LEDTO_WINDOW:]):
                if src == path:
                    continue
                if pending_term and pending_term[0] == src:
                    pairs.append((src, path, f"'{pending_term[1]}' in {src} led to {path}"))
                    break
                if len(stem) >= 4 and stem.lower() not in STOP_TERMS and any(stem in t for t in terms):
                    pairs.append((src, path, f"{src} mentions {stem}, which led to {path}"))
                    break
            recent.append((path, set(c.get("terms", []))))
            pending_term = None
        elif c["tool"] == "grep":
            pat = str(c["args"].get("pattern", ""))
            for src, terms in reversed(recent[-LEDTO_WINDOW:]):
                hit = next((t for t in terms if len(t) >= 4 and t.lower() not in STOP_TERMS and t in pat), None)
                if hit:
                    pending_term = (src, hit)
                    break
    return pairs


def learn(store: Store, *, task_id: str, symptom: str, calls: list[dict], edits: list[dict],
          config_before: str | None, config_after: str | None = None, success: bool) -> dict:
    """Write what a run taught. Returns a small report for the log."""
    report = {"causes": [], "led_to": [], "skipped_dead": 0, "fixed": []}
    if not success:
        return report
    fixed = fixed_locations(store, edits, config_before, config_after)
    report["fixed"] = fixed
    for err in symptom_nodes(store, symptom):
        for loc in fixed:
            try:
                store.upsert_edge(err, loc, "causes", delta=DELTA_VERIFIED, trust="verified",
                                  why=f"changing {loc.split(':', 1)[1]} fixed this before (tests passed)",
                                  actor="learn", task_id=task_id)
                report["causes"].append((err, loc))
            except DeadEdgeError:
                report["skipped_dead"] += 1
    for a, b, why in ledto_pairs(calls):
        try:
            store.upsert_edge(file_node(store, a), file_node(store, b), "led_to", delta=DELTA_LEDTO,
                              trust="verified", why=why, actor="learn", task_id=task_id)
            report["led_to"].append((a, b))
        except DeadEdgeError:
            report["skipped_dead"] += 1
    return report
