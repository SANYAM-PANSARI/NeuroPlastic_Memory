"""Live demo of learning and forgetting, no LLM: a scripted agent fixes a bug, the memory learns
the shortcut, then a drift bug makes the shortcut mislead until it dies with its reason.

Usage: python -m navmem.demo_learning [--vault ../obsidian_vault] [--pause]
  --vault  rewrites the Obsidian vault at each stage, so the graph view changes as you talk
  --pause  waits for Enter between stages (you control the pace on stage)
"""
import argparse
from pathlib import Path

from bench.agent import ToolCall
from bench.run import run_one
from bench.setup_bug import BENCH, load_bugs
from navmem.export_obsidian import export
from navmem.forget import KILL_AFTER, feedback
from navmem.recall import format_hints, recall
from navmem.static_graph import build
from navmem.store import Store


class ScriptedAgent:
    """Plays a fixed, sensible debugging session (stands in for the LLM in this demo)."""
    def __init__(self, script):
        self.script = list(script)

    def step(self, messages, tools):
        return {"role": "assistant", "content": ""}, [self.script.pop(0)] if self.script else []


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", help="Obsidian vault folder to rewrite at each stage")
    ap.add_argument("--pause", action="store_true", help="wait for Enter between stages")
    args = ap.parse_args()

    def stage(label):
        if args.vault:
            export(store, Path(args.vault))
            print(f"\n  [Obsidian vault updated: {label}]")
        if args.pause:
            input("  press Enter to continue...")

    bugs = load_bugs()
    store = Store()
    build(BENCH / "fake_system", store)
    sym = bugs["auth-pool-too-small"]["symptom"]

    banner("DAY 1: static graph only. The true cause (AUTH_POOL_SIZE) is not in the hints")
    print(f"Symptom: {sym}\n" + format_hints(recall(store, sym)[:3]))
    stage("day 1, static graph")

    banner("An agent fixes the bug; tests pass; the memory learns from the verified run")
    run_one(ScriptedAgent([
        ToolCall("read_logs", {}),
        ToolCall("read_file", {"path": "services/payments/client.py"}),
        ToolCall("read_file", {"path": "services/auth/auth_service.py"}),
        ToolCall("read_file", {"path": "config.yaml"}),
        ToolCall("edit_file", {"path": "config.yaml", "find": "AUTH_POOL_SIZE: 2", "replace": "AUTH_POOL_SIZE: 8"}),
        ToolCall("run_tests", {}),
        ToolCall("done", {"summary": "auth pool smaller than payment concurrency"}),
    ]), bugs["auth-pool-too-small"], "learned", store, 1, 10, 60)

    banner("NEXT TIME: the learned shortcut is the first hint (one lookup)")
    print(format_hints(recall(store, sym)[:3]))
    stage("learned shortcut added")

    banner(f"DRIFT: same symptom, new cause. The shortcut misleads {KILL_AFTER} times and dies")
    drift = bugs["payments-timeout-drift"]["symptom"]
    for i in range(KILL_AFTER):
        top = recall(store, drift)[0]
        print(f"  try {i + 1}: agent follows '{top.pointer}', but the fix was PAYMENT_CONCURRENCY")
        feedback(store, task_id=f"drift{i}", hints=[top], read_paths={"config.yaml"},
                 fixed_nodes=["cfg:PAYMENT_CONCURRENCY"], success=True)
    print("\nHints now:\n" + format_hints(recall(store, drift)[:3]))
    stage("misleading shortcut killed")

    banner("AUDIT LOG of the learned link (nothing is erased)")
    for r in store.db.execute("""SELECT e.action, e.reason FROM events e JOIN edges g ON g.id = e.edge_id
                                 WHERE g.dst = 'cfg:AUTH_POOL_SIZE' AND g.type = 'causes' ORDER BY e.id"""):
        print(f"  {r[0]:<7} {r[1]}")


if __name__ == "__main__":
    main()
