"""Live demo with the REAL local model (Ollama): no script, the model makes its own moves.

Shows the hints before, runs the agent on one planted bug, checks the tests, then shows what
the memory learned (or that it learned nothing, if the fix did not pass).

Usage: python -m navmem.demo_live [--bug auth-pool-too-small] [--model qwen3:8b] [--vault ..\\obsidian_vault]
"""
import argparse
import uuid
from pathlib import Path

from bench.agent import OllamaModel
from bench.run import run_one
from bench.setup_bug import BENCH, load_bugs
from navmem.export_obsidian import export
from navmem.recall import format_hints, recall
from navmem.static_graph import build
from navmem.store import Store


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bug", default="auth-pool-too-small")
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--time-limit", type=int, default=150)
    ap.add_argument("--vault", help="Obsidian vault folder to update after the run")
    args = ap.parse_args()

    bug = load_bugs()[args.bug]
    store = Store()                                   # fresh in-memory map for the demo
    build(BENCH / "fake_system", store)

    banner(f"LIVE RUN with {args.model} (real model, its own decisions)")
    print(f"Bug:      {bug['id']}\nSymptom:  {bug['symptom']}\nAnswer:   {bug['root_cause']} (hidden from the agent)")
    banner("Hints the agent gets before it starts (day-1 map)")
    print(format_hints(recall(store, bug["symptom"])[:5]) or "(no hints)")

    banner("The agent works (each step is a real tool call by the model)")
    row = run_one(OllamaModel(args.model), bug, "learned", store, 1, max_steps=15, time_limit=args.time_limit)

    banner("RESULT")
    print(f"Tests pass after the agent's fix:  {'YES' if row['success'] else 'NO'}")
    print(f"Fixed the planted root cause:       {'YES' if row['fixed_root_cause'] else 'NO'}")
    print(f"What it changed:                    {row['fixed'] or 'nothing'}")
    print(f"Tool calls / seconds:               {row['total_calls']} / {row['seconds']}")
    print(f"Links learned / hints that misled:  {row['links_learned']} / {row['hints_followed_misled']}")

    banner("Hints for this symptom NOW")
    if row["success"]:
        print(format_hints(recall(store, bug["symptom"])[:5]))
        print("\n-> A verified fix taught the memory. The next agent starts from this.")
    else:
        print(format_hints(recall(store, bug["symptom"])[:5]) or "(no hints)")
        print("\n-> The fix did not pass the tests, so the memory learned NOTHING from it.")
        print("   This is the safety rule: unverified guesses never reach the shared memory.")

    if args.vault:
        export(store, Path(args.vault))
        print(f"\n[Obsidian vault updated: {args.vault}]")


if __name__ == "__main__":
    main()
