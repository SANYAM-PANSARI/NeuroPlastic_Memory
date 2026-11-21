"""Prepare a broken copy of the fake system as a workspace for a real agent harness
(Antigravity, Claude Code, Cursor...), wired to the navmem MCP server.

It creates <out>/<bug>/ with:
  - the system with the bug planted (DB built, logs written by a failing test run)
  - .agents/mcp_config.json   (Antigravity's workspace MCP config)
  - .mcp.json                 (same server, for Claude Code / other MCP clients)
  - TASK.md                   (the prompt to paste: symptom + "use the navmem tools")

Usage:
  python -m navmem.prepare_harness auth-pool-too-small                      one bug, memory on
  python -m navmem.prepare_harness --all --condition none --run-label r1    every bug, control run
Then open <out>/<condition>/<run-label>/<bug> as the workspace in Antigravity and paste TASK.md.
All runs log to bench/antigravity_log.jsonl; analyse with: python -m navmem.analyze_harness
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from bench.setup_bug import load_bugs, setup

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bug", nargs="?", default="auth-pool-too-small")
    ap.add_argument("--all", action="store_true", help="prepare every bug in bugs.yaml")
    ap.add_argument("--condition", default="memory", choices=["memory", "none"])
    ap.add_argument("--run-label", default="r1", help="e.g. r1, r2 (round 2 benefits from round 1)")
    ap.add_argument("--out", default=str(ROOT.parent / "harness"))
    ap.add_argument("--memory", default=str(ROOT / "bench" / "antigravity_memory.db"),
                    help="shared memory file (keep the same one across tasks so learning carries over)")
    ap.add_argument("--log", default=str(ROOT / "bench" / "antigravity_log.jsonl"))
    a = ap.parse_args()
    bugs = load_bugs()
    for bug_id in (list(bugs) if a.all else [a.bug]):
        prepare(bugs[bug_id], a)
    print(f"\nEvery tool call is logged to {a.log}")
    print("When you have run them, analyse with:  python -m navmem.analyze_harness")


def prepare(bug, a):
    wd = setup(bug["id"], Path(a.out) / a.condition / a.run_label / bug["id"])
    subprocess.run([sys.executable, "make_db.py"], cwd=wd, check=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=wd, capture_output=True)  # writes logs

    server = {"command": sys.executable,
              "args": [str(ROOT / "navmem" / "mcp_server.py"), "--root", str(wd), "--memory", a.memory,
                       "--setup-cmd", f'"{sys.executable}" make_db.py',
                       "--test-cmd", f'"{sys.executable}" -m pytest -q tests',
                       "--log", a.log, "--condition", a.condition, "--bug", bug["id"],
                       "--root-cause", bug["root_cause"], "--run-label", a.run_label]}
    cfg = {"mcpServers": {"navmem": server}}
    (wd / ".agents").mkdir(exist_ok=True)
    (wd / ".agents" / "mcp_config.json").write_text(json.dumps(cfg, indent=2))
    (wd / ".mcp.json").write_text(json.dumps(cfg, indent=2))
    (wd / "TASK.md").write_text(
        f"Bug report: {bug['symptom']}\n\n"
        "Rules for this task:\n"
        "1. First call the navmem tool start_task with the bug report above, and read its hints.\n"
        "2. Investigate and fix ONLY with navmem's tools: read_file, grep, read_logs, query_db, "
        "edit_file, run_tests. Do not use your own file or terminal tools, so the path can be learned.\n"
        "3. When run_tests passes, call finish_task with a one-line summary of the root cause.\n",
        encoding="utf-8")
    print(f"Ready [{a.condition}/{a.run_label}]: {wd}")


if __name__ == "__main__":
    main()
