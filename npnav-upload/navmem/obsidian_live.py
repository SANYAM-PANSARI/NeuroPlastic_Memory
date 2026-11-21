"""Keep an Obsidian vault in sync with the memory while agents work (for demos and the video).

Every time the memory database or the MCP log changes, the vault is rewritten: one note per
location, live links as [[links]] (dead ones disappear from the graph, reason kept in the note),
plus `_Live agent.md` (current task: hints and steps) and `_Audit log.md` (every learn/forget).
Graph colours are set once in .obsidian/graph.json (learned = blue, dead = red, by type otherwise).

Usage: python -m navmem.obsidian_live [--vault ..\\obsidian_vault]
Open the vault in Obsidian, open Graph view (Ctrl+G), and leave this running.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from navmem.dashboard import read_state
from navmem.export_obsidian import export, md
from navmem.store import Store

ROOT = Path(__file__).resolve().parent.parent

# Obsidian colour groups: first match wins, so status (dead, learned) comes before type
COLOR_GROUPS = [
    ("tag:#dead", 0xE05A5A), ("tag:#learned", 0x5B8CF0), ("tag:#err", 0xE0A03A),
    ("tag:#cfg", 0x3FBF7F), ("tag:#table", 0x3FBF7F), ("tag:#fn", 0xB18CF0), ("tag:#file", 0x8A93AD),
]


def set_colors(vault: Path) -> None:
    cfg_dir = vault / ".obsidian"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "graph.json"
    graph = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    graph["colorGroups"] = [{"query": q, "color": {"a": 1, "rgb": rgb}} for q, rgb in COLOR_GROUPS]
    graph.setdefault("showArrow", True)
    path.write_text(json.dumps(graph, indent=2), encoding="utf-8")


def write_live_notes(vault: Path, state: dict) -> None:
    L = state["live"]
    if L:
        lines = [f"# Live agent: {md(L['bug'])}", "", f"Condition **{L['condition']}**, run **{L['run']}**", "",
                 f"## Hints given ({len(L['hints'])})"] + [f"{i}. {md(h)}" for i, h in enumerate(L["hints"], 1)]
        lines += ["", f"## Steps ({len(L['steps'])})"]
        lines += [f"{i}. `{s['tool']}` {json.dumps(s['args'])[:80]}" for i, s in enumerate(L["steps"], 1)]
    else:
        lines = ["# Live agent", "", "_Waiting for an agent to call start_task..._"]
    if state["tasks"]:
        t = state["tasks"][-1]
        lines += ["", "## Last finished task",
                  f"{t['bug']} [{t['condition']}/{t['run']}]: tests {'passed' if t['tests_passed'] else 'FAILED'}, "
                  f"fixed {', '.join(t.get('fixed') or []) or 'nothing'}, {t.get('tool_calls')} calls, "
                  f"{t.get('links_learned')} links learned"]
    (vault / "_Live agent.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    ev = ["# Audit log", "", "Newest first. Every change to a learned link, with its reason.", ""]
    for e in state["events"]:
        ev.append(f"- **{e['action'].upper()}** {md(e['src'].split(':', 1)[-1])} → {md(e['dst'].split(':', 1)[-1])}"
                  + (f": {md(e['reason'])}" if e.get("reason") else ""))
    (vault / "_Audit log.md").write_text("\n".join(ev) + "\n", encoding="utf-8")


def sync(vault: Path, memory: Path, log: Path) -> int:
    n = export(Store(str(memory)), vault) if memory.exists() else 0
    write_live_notes(vault, read_state(memory, log))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(ROOT.parent / "obsidian_vault"))
    ap.add_argument("--memory", default=str(ROOT / "bench" / "antigravity_memory.db"))
    ap.add_argument("--log", default=str(ROOT / "bench" / "antigravity_log.jsonl"))
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args()
    vault, memory, log = Path(a.vault), Path(a.memory), Path(a.log)
    vault.mkdir(parents=True, exist_ok=True)
    set_colors(vault)
    print(f"Syncing {memory.name} + {log.name} -> {vault} every {a.interval}s (Ctrl+C to stop)")
    print("In Obsidian: open this vault, then Graph view (Ctrl+G). Keep '_Live agent' open beside it.")
    last = None
    while True:
        stamp = tuple(p.stat().st_mtime if p.exists() else 0 for p in (memory, log))
        if stamp != last:
            n = sync(vault, memory, log)
            print(f"  {time.strftime('%H:%M:%S')} updated vault ({n} locations)", flush=True)
            last = stamp
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
