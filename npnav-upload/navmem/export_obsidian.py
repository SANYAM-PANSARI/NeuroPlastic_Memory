"""Export the memory to an Obsidian vault: one note per node, [[links]] for live edges.

Live edges become [[links]], so Obsidian's graph view draws them. Dead edges are written as
plain text (no brackets), so the line disappears from the graph while the reason stays readable.
Nodes get tags (#cfg, #fn, #err, #file, #table, plus #learned and #dead) for colouring.

Usage:
  python -m navmem.export_obsidian [vault_dir]                  static graph of the fake system
  python -m navmem.export_obsidian [vault_dir] bench/memory.db  the learned memory from a benchmark run
"""
import re
import sys
from pathlib import Path

from navmem.static_graph import build
from navmem.store import Store


def md(text) -> str:
    """Obsidian treats <N> as an HTML tag and hides it; escape angle brackets."""
    return str(text or "").replace("<", "&lt;").replace(">", "&gt;")


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "_", name)[:120]


def export(store: Store, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):          # only our own notes; Obsidian's .obsidian settings stay
        old.unlink()
    learned_nodes = {r[0] for r in store.db.execute(
        "SELECT src FROM edges WHERE source='learned' AND status='live' UNION "
        "SELECT dst FROM edges WHERE source='learned' AND status='live'")}
    dead_nodes = {r[0] for r in store.db.execute("SELECT dst FROM edges WHERE status='dead'")}
    nodes = store.db.execute("SELECT id, type, pointer, description FROM nodes").fetchall()
    for n in nodes:
        # red only when nothing learned and live still points here
        tags = [n["type"]] + (["learned"] if n["id"] in learned_nodes else []) \
            + (["dead"] if n["id"] in dead_nodes and n["id"] not in learned_nodes else [])
        lines = ["---", f"type: {n['type']}", f"pointer: \"{n['pointer']}\"",
                 f"tags: [{', '.join(tags)}]", "---", f"# {md(n['id'])}", "", md(n["description"]), "",
                 "## Links"]
        for e in store.db.execute("SELECT * FROM edges WHERE src = ? ORDER BY status, type", (n["id"],)):
            meta = f"(strength {e['strength']:.1f}, {e['trust']}, {e['source']})"
            if e["status"] == "live":
                lines.append(f"- {e['type']} [[{safe(e['dst'])}]] {meta}: {md(e['why'])}")
            else:
                lines.append(f"- ~~{e['type']} {md(e['dst'])}~~ DEAD: {md(e['dead_reason'])}")
        (out / f"{safe(n['id'])}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(nodes)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "obsidian_vault")
    if len(sys.argv) > 2:
        s = Store(sys.argv[2])
    else:
        s = Store()
        build("bench/fake_system", s)
    print(f"exported {export(s, out)} notes to {out}/ (open this folder as a vault in Obsidian)")
