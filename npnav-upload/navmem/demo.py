"""Live demo, no LLM: build the static graph, then show recall hints for every planted bug.

Usage: python -m navmem.demo
"""
import yaml

from navmem.recall import recall
from navmem.static_graph import build
from navmem.store import Store

BUGS = "bench/bugs.yaml"
SYSTEM = "bench/fake_system"


def main():
    store = Store()
    counts = build(SYSTEM, store)
    types = dict(store.db.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall())
    print("=" * 72)
    print("NeuroPlastic Navigation: static layer demo (no LLM calls)")
    print("=" * 72)
    print(f"Graph built from {SYSTEM}: {counts['nodes']} node writes, {counts['edges']} edges")
    print("Nodes by type: " + ", ".join(f"{k}={v}" for k, v in sorted(types.items())))

    for bug in yaml.safe_load(open(BUGS)):
        print("\n" + "-" * 72)
        print(f"BUG      {bug['id']}")
        print(f"SYMPTOM  {bug['symptom']}")
        print(f"ANSWER   {bug['root_cause']}")
        hints = recall(store, bug["symptom"])
        if not hints:
            print("HINTS    (none: no matching entry point, agent explores normally)")
            continue
        root = bug["root_cause"].split("#")[-1]
        for i, h in enumerate(hints, 1):
            mark = "  <== root cause" if root in h.pointer else ""
            print(f"  {i}. {h.score:.3f}  {h.pointer}{mark}")
            print(f"           because {h.path[-1]}")
        if not any(root in h.pointer for h in hints):
            print("  -> root cause not reached by static links; learned links (M3) close this gap")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
