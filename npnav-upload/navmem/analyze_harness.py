"""Turn the harness log (bench/antigravity_log.jsonl) into a results table.

Usage: python -m navmem.analyze_harness [log file]
Prints one row per task and a summary per condition and round, and writes
bench/antigravity_results.csv.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from bench.scoring import score_fix
from bench.setup_bug import load_bugs

ROOT = Path(__file__).resolve().parent.parent
COLS = ["condition", "run", "bug", "tests_passed", "fixed_root_cause", "fix_choice", "reached_root_file",
        "nav_calls_to_root", "tool_calls", "seconds", "hints_given", "links_learned",
        "hints_misled", "outside_tools"]


BUGS = load_bugs()


def load(path: Path) -> list[dict]:
    rows, tool_counts = [], defaultdict(int)
    started = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event"] == "start_task":
            started[e["task_id"]] = e
        elif e["event"] == "tool":
            tool_counts[e.get("task_id")] += 1
        elif e["event"] == "finish_task":
            r = {k: e.get(k) for k in COLS}
            # re-score from the raw log with the current rule (accepted fixes), so old runs
            # are judged the same way as new ones
            if e.get("bug") in BUGS:
                r.update(score_fix(BUGS[e["bug"]], e.get("fixed") or [], bool(e.get("tests_passed"))))
            r["hints_misled"] = len(e.get("hints_misled") or [])
            # tests pass but our tools saw no edit: the agent fixed it with its own tools
            r["outside_tools"] = bool(e.get("tests_passed") and not e.get("fixed"))
            rows.append(r)
            started.pop(e["task_id"], None)
    for tid, e in started.items():              # started but never finished
        rows.append({"condition": e["condition"], "run": e["run"], "bug": e["bug"], "tests_passed": None,
                     "tool_calls": tool_counts[tid], "outside_tools": "unfinished"})
    return rows


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float)) and x >= 0]
    return round(sum(xs) / len(xs), 1) if xs else "-"


def main():
    log = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "bench" / "antigravity_log.jsonl"
    if not log.exists():
        sys.exit(f"no log at {log}: run some tasks in the harness first")
    rows = load(log)
    print(f"{len(rows)} tasks in {log}\n")
    w = [10, 4, 34, 6, 6, 9, 6, 6, 6, 7, 6, 8]
    head = ["condition", "run", "bug", "pass", "root", "fix", "reach", "nav", "calls", "secs", "hints", "outside"]
    print("  ".join(h.ljust(x) for h, x in zip(head, w)))
    for r in rows:
        vals = [r.get("condition"), r.get("run"), r.get("bug"), r.get("tests_passed"), r.get("fixed_root_cause"),
                r.get("fix_choice"), r.get("reached_root_file"), r.get("nav_calls_to_root"), r.get("tool_calls"), r.get("seconds"),
                r.get("hints_given"), r.get("outside_tools")]
        print("  ".join(str(v).ljust(x) for v, x in zip(vals, w)))

    print("\nSUMMARY (per condition and round)")
    groups = defaultdict(list)
    for r in rows:
        groups[(r.get("condition"), r.get("run"))].append(r)
    for (cond, run), g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        done = [r for r in g if r.get("tests_passed") is not None]
        passed = sum(1 for r in done if r["tests_passed"])
        print(f"  {cond}/{run}: {passed}/{len(done)} fixed (tests pass) | "
              f"avg calls to root file {mean([r.get('nav_calls_to_root') for r in done])} | "
              f"avg tool calls {mean([r.get('tool_calls') for r in done])} | "
              f"avg seconds {mean([r.get('seconds') for r in done])} | "
              f"hints misled {sum(r.get('hints_misled') or 0 for r in done)} | "
              f"used own tools {sum(1 for r in g if r.get('outside_tools') is True)}")
    out = ROOT / "bench" / "antigravity_results.csv"
    with open(out, "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"\nwritten {out}")
    print("Reading it: 'nav' = tool calls before the agent first opened the root-cause file (lower is better).")
    print("'outside' = True means tests passed but our tools saw no edit: the agent used its own tools,")
    print("so that run says little about our memory.")


if __name__ == "__main__":
    main()
