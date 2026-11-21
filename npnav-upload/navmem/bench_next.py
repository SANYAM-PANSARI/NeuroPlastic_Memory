"""Choose the next benchmark task for the always-on navmem MCP server, and print the prompt.

Usage: python -m navmem.bench_next auth-pool-too-small --condition none --run r1
Then paste the printed prompt into the Antigravity agent (same open folder every time).
When the agent calls start_task, the server plants this bug in a fresh copy and works there.
"""
import argparse
import json
from pathlib import Path

from bench.setup_bug import load_bugs

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT.parent / "harness"


def prompt_for(bug: dict) -> str:
    return (f"Bug report: {bug['symptom']}\n\n"
            "Rules for this task:\n"
            "1. First call the navmem tool start_task with the bug report above, and read its hints.\n"
            "2. Investigate and fix ONLY with navmem's tools: read_file, grep, read_logs, query_db, "
            "edit_file, run_tests. Do not use your own file or terminal tools, so the path can be learned.\n"
            "3. When run_tests passes, call finish_task with a one-line summary of the root cause.\n")


def stale_configs(harness: Path = HARNESS) -> list[Path]:
    """Project-level MCP configs from the old per-folder setup override the global navmem."""
    return [c for c in (harness / ".agents" / "mcp_config.json", harness / ".mcp.json")
            if c.exists() and "--root" in c.read_text(encoding="utf-8")]


def set_next(bug_id: str, condition: str, run: str, harness: Path = HARNESS) -> str:
    bug = load_bugs()[bug_id]
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "current_run.json").write_text(json.dumps({"bug": bug_id, "condition": condition, "run": run}))
    text = prompt_for(bug)
    (harness / "TASK.md").write_text(text, encoding="utf-8")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bug", choices=list(load_bugs()))
    ap.add_argument("--condition", default="memory", choices=["memory", "none"])
    ap.add_argument("--run", default="r1")
    a = ap.parse_args()
    stale = stale_configs()
    if stale:
        print("WARNING: old per-folder MCP config found; Antigravity will use it instead of the")
        print("benchmark navmem and ignore this command. Fix: python -m navmem.reset_demo, then")
        print("refresh MCP Servers in Antigravity.  Found:", ", ".join(str(s) for s in stale), "\n")
    text = set_next(a.bug, a.condition, a.run)
    print(f"Next task set: {a.bug} [{a.condition}/{a.run}]  (also saved to {HARNESS / 'TASK.md'})")
    print("Paste this into the Antigravity agent:\n")
    print(text)


if __name__ == "__main__":
    main()
