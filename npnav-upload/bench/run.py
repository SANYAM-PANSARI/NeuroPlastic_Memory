"""Run the benchmark and append rows to bench/results.csv.

Conditions:
  no_memory  the agent explores from scratch
  static     hints from the static graph only (rebuilt each bug)
  learned    static graph + links learned from earlier verified runs; memory persists in
             bench/memory.db across bugs and across runs (use --fresh to start over)

Usage: python -m bench.run --model qwen3:8b --condition learned --rounds 2
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import uuid
from pathlib import Path

from bench.agent import OllamaModel, run_agent
from bench.scoring import score_fix
from bench.setup_bug import BENCH, load_bugs, setup
from bench.tools import Toolbox
from navmem.forget import feedback
from navmem.learn import learn
from navmem.recall import format_hints, recall
from navmem.static_graph import build
from navmem.store import Store

FIELDS = ["condition", "model", "round", "bug", "phase", "success", "fixed_root_cause", "fix_choice",
          "reached_root_file", "nav_calls_to_root", "total_calls", "seconds", "hints_given",
          "hints_followed_helped", "hints_followed_misled", "links_learned", "links_killed", "fixed"]


def tests_pass(wd: Path) -> bool:
    subprocess.run([sys.executable, "make_db.py"], cwd=wd, capture_output=True)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=wd,
                          capture_output=True).returncode == 0


def root_parts(bug: dict) -> tuple[str, str | None]:
    f, _, key = bug["root_cause"].partition("#")
    return f, (key.split(".")[-1] if key else None)


def run_one(model, bug: dict, condition: str, store: Store | None, rnd: int,
            max_steps: int, time_limit: int) -> dict:
    wd = setup(bug["id"], BENCH / "work" / bug["id"])
    subprocess.run([sys.executable, "make_db.py"], cwd=wd, check=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=wd, capture_output=True)  # writes logs
    config_before = (wd / "config.yaml").read_text()

    hints = []
    if condition == "static":
        store = Store()
        build(wd, store)
    if condition in ("static", "learned"):
        hints = recall(store, bug["symptom"])
    task = bug["symptom"] + (f"\n\n{format_hints(hints)}" if hints else "")

    box = Toolbox(wd)
    print(f"--> {bug['id']} ({condition}, round {rnd})" + (f", {len(hints)} hints" if hints else ""), flush=True)
    result = run_agent(model, box, task, max_steps=max_steps, time_limit=time_limit)
    success = tests_pass(wd)

    # what did the fix change?
    from navmem.learn import fixed_locations
    probe = Store()
    build(wd, probe)
    fixed = fixed_locations(probe, box.edits, config_before, (wd / "config.yaml").read_text())

    rfile, rkey = root_parts(bug)
    reads = [str(c["args"].get("path", "")) for c in box.calls if c["tool"] == "read_file"]
    first = next((i for i, c in enumerate(box.calls)
                  if c["tool"] == "read_file" and str(c["args"].get("path", "")).endswith(rfile)), None)
    row = {"condition": condition, "round": rnd, "bug": bug["id"], "phase": bug["phase"],
           "success": success,
           **score_fix(bug, fixed, success),
           "reached_root_file": first is not None,
           "nav_calls_to_root": first if first is not None else -1,
           "total_calls": len(box.calls), "seconds": result["seconds"], "hints_given": len(hints),
           "hints_followed_helped": 0, "hints_followed_misled": 0, "links_learned": 0, "links_killed": 0,
           "fixed": ";".join(fixed)}

    if condition == "learned":
        task_id = str(uuid.uuid4())[:8]
        fb = feedback(store, task_id=task_id, hints=hints, read_paths=set(reads),
                      fixed_nodes=fixed, success=success)
        rep = learn(store, task_id=task_id, symptom=bug["symptom"], calls=box.calls, edits=box.edits,
                    config_before=config_before, config_after=(wd / "config.yaml").read_text(),
                    success=success)
        row.update(hints_followed_helped=len(fb["helped"]), hints_followed_misled=len(fb["misled"]),
                   links_learned=len(rep["causes"]) + len(rep["led_to"]), links_killed=len(fb["killed"]))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--condition", default="no_memory", choices=["no_memory", "static", "learned"])
    ap.add_argument("--rounds", type=int, default=1, help="passes over the bug list (learning carries over)")
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--time-limit", type=int, default=240, help="seconds per bug")
    ap.add_argument("--only", nargs="*", help="bug ids to run")
    ap.add_argument("--think", action="store_true", help="let the model reason before each step (slower)")
    ap.add_argument("--fresh", action="store_true", help="learned: delete bench/memory.db first")
    args = ap.parse_args()

    model = OllamaModel(args.model, think=args.think)
    store = None
    if args.condition == "learned":
        mem = BENCH / "memory.db"
        if args.fresh and mem.exists():
            mem.unlink()
        new = not mem.exists()
        store = Store(str(mem))
        if new:
            build(BENCH / "fake_system", store)   # day-1 static layer from the clean system

    bugs = [b for b in load_bugs().values() if not args.only or b["id"] in args.only]
    out = BENCH / "results.csv"
    for rnd in range(1, args.rounds + 1):
        for bug in bugs:
            row = run_one(model, bug, args.condition, store, rnd, args.max_steps, args.time_limit)
            row["model"] = args.model
            if args.think:
                row["condition"] += "+think"
            print("   ", {k: row[k] for k in ("success", "fixed_root_cause", "nav_calls_to_root",
                                               "total_calls", "fixed", "links_learned")}, flush=True)
            new = not out.exists() or out.read_text().splitlines()[:1] != [",".join(FIELDS)]
            if new and out.exists():
                out.replace(out.with_name("results_old.csv"))   # old column layout: keep it aside
            with open(out, "a", newline="") as f:      # saved immediately, so Ctrl+C loses nothing
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)


if __name__ == "__main__":
    main()
