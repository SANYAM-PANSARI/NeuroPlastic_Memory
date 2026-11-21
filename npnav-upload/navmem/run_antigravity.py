"""Run the Antigravity benchmark automatically with the Antigravity CLI (agy).

Needs the navmem server registered once (python -m navmem.install_mcp). For each bug and condition
it sets the next task (bench_next) and runs `agy -p "<prompt>"` in the harness folder; the always-on
server plants the bug when the agent calls start_task. Our MCP server logs every tool call to
bench/antigravity_log.jsonl, so we never need agy's own output (capturing it can hang on Windows).

Order: control (no memory) first, then memory round 1, then memory round 2 (uses what r1 learned).

Usage:
  python -m navmem.run_antigravity                       # 3 default bugs, prompts you for permissions
  python -m navmem.run_antigravity --model "<slug>"      # pin the model (same for every task!)
  python -m navmem.run_antigravity --auto-approve        # fully unattended; agent may run ANY command
  python -m navmem.run_antigravity --dry-run             # print what would run
Then: python -m navmem.analyze_harness
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUGS = ["auth-pool-too-small", "checkout-hangs-same-cause", "payments-timeout-drift", "payments-gateway-drift"]
PLAN = [("none", "r1", None), ("memory", "r1", None), ("memory", "r2", None),
        # drift phase: the cause has changed and stays changed; does the old shortcut lose its place?
        ("memory", "d1", ["payments-gateway-drift"]), ("memory", "d2", ["payments-gateway-drift"]),
        ("memory", "d3", ["payments-gateway-drift"])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bugs", nargs="*", default=DEFAULT_BUGS)
    ap.add_argument("--model", help="agy model slug; keep it the same for every task")
    ap.add_argument("--auto-approve", action="store_true",
                    help="pass --dangerously-skip-permissions: no prompts, but the agent may run any command")
    ap.add_argument("--time-limit", type=int, default=600, help="seconds per task before it is stopped")
    ap.add_argument("--fresh", action="store_true", help="delete the old benchmark memory and log first")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--agy", default="agy", help="path to the agy executable")
    a = ap.parse_args()

    agy = shutil.which(a.agy)
    if not agy and not a.dry_run:
        sys.exit("agy (Antigravity CLI) not found. Install it (PowerShell):\n"
                 "  irm https://antigravity.google/cli/install.ps1 | iex\n"
                 "then run `agy` once interactively to sign in.")
    from navmem.install_mcp import CONFIG
    if not a.dry_run and not (CONFIG.exists() and "navmem" in CONFIG.read_text(encoding="utf-8")):
        sys.exit("navmem is not registered yet. Run once:  python -m navmem.install_mcp")
    mem, log = ROOT / "bench" / "antigravity_memory.db", ROOT / "bench" / "antigravity_log.jsonl"
    if a.fresh and not a.dry_run:
        for f in (mem, log):
            f.unlink(missing_ok=True)

    total = sum(len(b or a.bugs) for _, _, b in PLAN)
    n = 0
    for cond, run, only in PLAN:
        for bug in (only or a.bugs):
            n += 1
            from navmem.bench_next import HARNESS, set_next
            prompt = set_next(bug, cond, run)
            wd = HARNESS
            cmd = [agy or a.agy, "-p", prompt]
            if a.model:
                cmd += ["--model", a.model]
            if a.auto_approve:
                cmd += ["--dangerously-skip-permissions"]
            print(f"\n=== [{n}/{total}] {cond}/{run}/{bug} ===", flush=True)
            if a.dry_run:
                print("would run in", wd, ":", " ".join(cmd[:2]), "<TASK.md>", " ".join(cmd[3:]))
                continue
            t0 = time.time()
            try:
                # no capture_output: agy prints to this terminal (redirecting it can hang on Windows)
                subprocess.run(cmd, cwd=wd, timeout=a.time_limit)
            except subprocess.TimeoutExpired:
                print(f"--- stopped after {a.time_limit}s (logged as unfinished if it never called finish_task)")
            print(f"--- done in {round(time.time() - t0)}s", flush=True)

    if not a.dry_run:
        print("\nAll tasks run. Results:")
        subprocess.run([sys.executable, "-m", "navmem.analyze_harness"], cwd=ROOT)


if __name__ == "__main__":
    main()
