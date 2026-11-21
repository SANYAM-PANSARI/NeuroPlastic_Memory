"""Reset the Antigravity demo/benchmark to a clean start, even while Antigravity is open.

Windows will not delete a file another program has open (the navmem MCP server keeps the memory
database open). So instead of deleting, this empties things in place:
  - memory database: all rows removed, then the day-1 static map rebuilt (the server sees it at once)
  - MCP log: emptied
  - results CSV, harness work copies, current_run.json, Obsidian notes (*.md): removed
    (Obsidian's .obsidian settings, including graph colours, are kept)

Usage: python -m navmem.reset_demo [--keep-vault]
"""
import argparse
import shutil
import sqlite3
from pathlib import Path

from navmem.static_graph import build
from navmem.store import Store

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
HARNESS = ROOT.parent / "harness"
VAULT = ROOT.parent / "obsidian_vault"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-vault", action="store_true", help="leave the Obsidian notes alone")
    ap.add_argument("--memory", default=str(BENCH / "antigravity_memory.db"))
    ap.add_argument("--log", default=str(BENCH / "antigravity_log.jsonl"))
    a = ap.parse_args()
    problems = []

    mem = Path(a.memory)
    if mem.exists():
        try:
            db = sqlite3.connect(mem, timeout=10)
            for table in ("events", "trace", "tasks", "edges", "nodes"):
                db.execute(f"DELETE FROM {table}")
            db.commit()
            db.close()
            build(BENCH / "fake_system", Store(str(mem)))      # day-1 map, so recall works right away
            print(f"memory cleared and day-1 map rebuilt: {mem.name}")
        except sqlite3.Error as e:
            problems.append(f"memory: {e} (finish or close the running agent task, then retry)")
    else:
        print("memory: nothing to clear (the server creates it on first use)")

    log = Path(a.log)
    if log.exists():
        try:
            log.write_text("", encoding="utf-8")                # empty it; works while it is open
            print(f"log emptied: {log.name}")
        except OSError as e:
            problems.append(f"log: {e}")

    for f in (BENCH / "antigravity_results.csv", HARNESS / "current_run.json", HARNESS / "TASK.md"):
        try:
            f.unlink(missing_ok=True)
        except OSError as e:
            problems.append(f"{f.name}: {e}")

    # Old per-folder setup (prepare_harness) left project-level MCP configs in harness/. Antigravity
    # prefers those over the global bench-mode navmem, so they silently break the benchmark.
    for cfg in (HARNESS / ".agents" / "mcp_config.json", HARNESS / ".mcp.json"):
        if cfg.exists() and "--root" in cfg.read_text(encoding="utf-8"):
            try:
                cfg.unlink()
                print(f"removed old per-folder MCP config: {cfg.relative_to(HARNESS.parent)}")
            except OSError as e:
                problems.append(f"{cfg}: {e}")
    for old in (HARNESS / "memory", HARNESS / "none"):
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
            if old.exists():
                problems.append(f"old workspace folder still in use: {old}")
            else:
                print(f"removed old per-folder workspaces: {old.name}\\")

    work = HARNESS / "work"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
        if work.exists() and any(work.iterdir()):
            problems.append(f"some work copies are in use: {work} (close files open in Antigravity, retry)")
        else:
            print("harness work copies removed")

    if not a.keep_vault and VAULT.exists():
        removed = 0
        for note in VAULT.glob("*.md"):
            try:
                note.unlink()
                removed += 1
            except OSError as e:
                problems.append(f"{note.name}: {e}")
        print(f"Obsidian notes removed: {removed} (graph colour settings kept)")

    if problems:
        print("\nNot everything could be cleared:")
        for p in problems:
            print("  -", p)
    else:
        print("\nClean start. Next: python -m navmem.obsidian_live  (it redraws the day-1 map in Obsidian)")


if __name__ == "__main__":
    main()
