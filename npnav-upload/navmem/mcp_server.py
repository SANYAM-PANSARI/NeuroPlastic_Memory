"""NeuroPlastic Navigation as an MCP server, so real agent harnesses (Antigravity, Claude Code,
Cursor, ...) can use the memory.

The agent gets: start_task -> hints, instrumented read/search/edit/test tools, finish_task.
Every call is recorded (in memory and in an append-only JSONL log). On finish_task the server
runs the tests itself; only a passing run teaches the memory, and followed hints are scored.

Run (stdio, which is what harnesses launch):
  python navmem/mcp_server.py --root <project folder> [--memory <file.db>]
         [--setup-cmd "python make_db.py"] [--test-cmd "python -m pytest -q tests"]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # run as a plain script too

from bench.tools import Toolbox                     # noqa: E402  (same sandboxed tools as the benchmark)
from navmem.forget import feedback                  # noqa: E402
from navmem.learn import fixed_locations, learn     # noqa: E402
from navmem.recall import format_hints, recall      # noqa: E402
from navmem.static_graph import build               # noqa: E402
from navmem.store import Store                      # noqa: E402
from bench.scoring import score_fix              # noqa: E402
from bench.setup_bug import BENCH, load_bugs, setup  # noqa: E402

INSTRUCTIONS = (
    "NeuroPlastic Navigation: shared memory of where to look. Call start_task(symptom) first and "
    "read the hints. Then use ONLY this server's tools (read_file, grep, read_logs, query_db, "
    "edit_file, run_tests) to investigate and fix, so the path can be learned. "
    "When done, call finish_task(task_id, summary). Only fixes that pass the tests are learned."
)


class ProjectToolbox(Toolbox):
    """Toolbox for any project: the test command is configurable instead of the fake system's."""

    def __init__(self, root: Path, setup_cmd: str | None, test_cmd: str):
        super().__init__(root)
        self.setup_cmd, self.test_cmd = setup_cmd, test_cmd

    def run_tests(self) -> str:
        """Run the project's tests. Use it after a fix to check it worked."""
        ok, out = run_project_tests(self.root, self.setup_cmd, self.test_cmd)
        return ("PASSED: " if ok else "FAILED: ") + out


def run_project_tests(root: Path, setup_cmd: str | None, test_cmd: str) -> tuple[bool, str]:
    if setup_cmd:
        subprocess.run(setup_cmd, shell=True, cwd=root, capture_output=True)
    # shell=True: Windows paths with quotes and backslashes are passed to the system shell as typed
    r = subprocess.run(test_cmd, shell=True, cwd=root, capture_output=True, text=True)
    return r.returncode == 0, "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])


class NavServer:
    """All the logic, independent of the MCP library (so it is easy to test)."""

    def __init__(self, root: str | None, memory: str, setup_cmd: str | None, test_cmd: str, log: str | None = None,
                 condition: str = "memory", bug: str = "", root_cause: str = "", run_label: str = "",
                 bench_dir: str | None = None):
        # bench mode: one server for the whole benchmark; each start_task reads harness/current_run.json,
        # plants that bug in a fresh copy and works there (no folder or reconnect per bug)
        self.bench_dir = Path(bench_dir).resolve() if bench_dir else None
        self.root = Path(root).resolve() if root else None
        self.condition, self.bug, self.root_cause, self.run_label = condition, bug, root_cause, run_label
        self.setup_cmd, self.test_cmd = setup_cmd, test_cmd
        new = not Path(memory).exists() or memory == ":memory:"
        self.store = Store(memory)
        if new:
            build(self.root or BENCH / "fake_system", self.store)   # day-1 map from the project's code
        self.log_path = Path(log) if log else None
        self.tasks: dict[str, dict] = {}
        self.current: str | None = None
        self.lock = threading.Lock()          # one tool at a time touches the memory

    def _log(self, event: dict) -> None:
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "condition": self.condition, "bug": self.bug,
                                "run": self.run_label, **event}, default=str) + "\n")

    def _task(self, task_id: str | None) -> dict:
        tid = task_id or self.current
        if not tid or tid not in self.tasks:
            raise ValueError("no active task: call start_task(symptom) first")
        return self.tasks[tid]

    def _next_bench_run(self) -> None:
        """Read harness/current_run.json (written by `python -m navmem.bench_next`) and plant that bug."""
        spec = json.loads((self.bench_dir / "current_run.json").read_text(encoding="utf-8"))
        bug = load_bugs()[spec["bug"]]
        self.condition, self.bug, self.run_label = spec["condition"], bug["id"], spec["run"]
        self.root_cause = bug["root_cause"]
        wd = setup(bug["id"], self.bench_dir / "work" / f"{spec['condition']}_{spec['run']}_{bug['id']}")
        subprocess.run([sys.executable, "make_db.py"], cwd=wd, capture_output=True)
        subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=wd, capture_output=True)  # logs
        self.root = wd

    # ---- the MCP tools ----
    def start_task(self, symptom: str) -> str:
        if self.bench_dir:
            self._next_bench_run()
        tid = str(uuid.uuid4())[:8]
        cfg = self.root / "config.yaml"
        hints = recall(self.store, symptom) if self.condition == "memory" else []
        self.tasks[tid] = {"started": time.time(), "symptom": symptom, "hints": hints,
                           "box": ProjectToolbox(self.root, self.setup_cmd, self.test_cmd),
                           "config_before": cfg.read_text() if cfg.exists() else None}
        self.current = tid
        self._log({"event": "start_task", "task_id": tid, "symptom": symptom,
                   "hints": [h.pointer for h in hints]})
        if self.condition != "memory":
            return f"task_id: {tid}\n\nNo hints in this run: explore normally."
        return f"task_id: {tid}\n\n" + (format_hints(hints) or "No hints yet: explore normally.")

    def recall(self, query: str, suspects: list[str] | None = None) -> str:
        if self.condition != "memory":
            return "Memory is off in this run: explore normally."
        hints = recall(self.store, query, suspects)
        return format_hints(hints) or "No confident hints."

    def tool(self, name: str, args: dict, task_id: str | None = None) -> str:
        t = self._task(task_id)
        out = t["box"].call(name, args)
        self._log({"event": "tool", "task_id": task_id or self.current, "tool": name, "args": args,
                   "result_head": str(out)[:200]})
        return out

    def finish_task(self, summary: str, task_id: str | None = None) -> str:
        tid = task_id or self.current
        t = self._task(tid)
        box: Toolbox = t["box"]
        ok, _ = run_project_tests(self.root, self.setup_cmd, self.test_cmd)   # we check, not the agent
        cfg = self.root / "config.yaml"
        after = cfg.read_text() if cfg.exists() else None
        probe = Store()
        build(self.root, probe)
        fixed = fixed_locations(probe, box.edits, t["config_before"], after)
        reads = {str(c["args"].get("path", "")) for c in box.calls if c["tool"] == "read_file"}
        if self.condition == "memory":
            fb = feedback(self.store, task_id=tid, hints=t["hints"], read_paths=reads, fixed_nodes=fixed, success=ok)
            rep = learn(self.store, task_id=tid, symptom=t["symptom"], calls=box.calls, edits=box.edits,
                        config_before=t["config_before"], config_after=after, success=ok)
        else:
            fb, rep = {"helped": [], "misled": [], "killed": []}, {"causes": [], "led_to": []}
        rfile, _, rkey = self.root_cause.partition("#")
        first = next((i for i, c in enumerate(box.calls) if c["tool"] == "read_file"
                      and rfile and str(c["args"].get("path", "")).replace("\\", "/").endswith(rfile)), None)
        bug_spec = load_bugs().get(self.bug) or {"root_cause": self.root_cause}
        score = {"reached_root_file": first is not None, "nav_calls_to_root": first if first is not None else -1,
                 **score_fix(bug_spec, fixed, ok),
                 "seconds": round(time.time() - t["started"], 1), "hints_given": len(t["hints"])}
        result = {"tests_passed": ok, "fixed": fixed, "links_learned": len(rep["causes"]) + len(rep["led_to"]),
                  "hints_helped": fb["helped"], "hints_misled": fb["misled"], "links_killed": fb["killed"],
                  "tool_calls": len(box.calls), **score}
        self._log({"event": "finish_task", "task_id": tid, "summary": summary, **result})
        del self.tasks[tid]
        self.current = None
        return json.dumps(result, indent=2)


def make_mcp(nav: NavServer):
    try:                                             # mcp >= 2
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:                              # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server
    mcp = Server("navmem", instructions=INSTRUCTIONS)

    @mcp.tool()
    def start_task(symptom: str) -> str:
        """Start a debugging task. Give the symptom or error message; returns a task_id and hints
        on where to look, learned from earlier verified fixes."""
        with nav.lock:
            return nav.start_task(symptom)

    @mcp.tool()
    def recall(query: str, suspects: list[str] | None = None) -> str:
        """Ask the shared memory where to look. `suspects`: optional component names you suspect."""
        with nav.lock:
            return nav.recall(query, suspects)

    @mcp.tool()
    def read_file(path: str, task_id: str | None = None) -> str:
        """Read a text file in the project (path relative to the project root)."""
        with nav.lock:
            return nav.tool("read_file", {"path": path}, task_id)

    @mcp.tool()
    def grep(pattern: str, task_id: str | None = None) -> str:
        """Search all project files for a regex. Returns file:line: text."""
        with nav.lock:
            return nav.tool("grep", {"pattern": pattern}, task_id)

    @mcp.tool()
    def read_logs(task_id: str | None = None) -> str:
        """Read the application log (logs/app.log)."""
        with nav.lock:
            return nav.tool("read_logs", {}, task_id)

    @mcp.tool()
    def query_db(sql: str, task_id: str | None = None) -> str:
        """Run a read-only SELECT on data/orders.db."""
        with nav.lock:
            return nav.tool("query_db", {"sql": sql}, task_id)

    @mcp.tool()
    def edit_file(path: str, find: str, replace: str, task_id: str | None = None) -> str:
        """Fix a file by replacing the exact text `find` with `replace` (first match only)."""
        with nav.lock:
            return nav.tool("edit_file", {"path": path, "find": find, "replace": replace}, task_id)

    @mcp.tool()
    def run_tests(task_id: str | None = None) -> str:
        """Run the project's tests to check a fix."""
        with nav.lock:
            return nav.tool("run_tests", {}, task_id)

    @mcp.tool()
    def finish_task(summary: str, task_id: str | None = None) -> str:
        """Finish the task. The server re-runs the tests; if they pass, the path is learned for
        every agent. Returns what was learned and which hints helped or misled."""
        with nav.lock:
            return nav.finish_task(summary, task_id)

    return mcp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="project folder the agent works on (not needed with --bench-dir)")
    ap.add_argument("--bench-dir", help="benchmark mode: harness folder holding current_run.json")
    ap.add_argument("--memory", default=str(Path(__file__).resolve().parent.parent / "bench" / "mcp_memory.db"))
    ap.add_argument("--setup-cmd", default=f'"{sys.executable}" make_db.py')
    ap.add_argument("--test-cmd", default=f'"{sys.executable}" -m pytest -q tests')
    ap.add_argument("--log", default=str(Path(__file__).resolve().parent.parent / "bench" / "mcp_log.jsonl"))
    ap.add_argument("--condition", default="memory", choices=["memory", "none"],
                    help="none = control run: no hints, nothing learned (still logged and scored)")
    ap.add_argument("--bug", default="", help="bug id, for the log")
    ap.add_argument("--root-cause", default="", help="known answer, e.g. config.yaml#AUTH_POOL_SIZE, for scoring")
    ap.add_argument("--run-label", default="", help="free label for this run, e.g. round1")
    a = ap.parse_args()
    if not a.root and not a.bench_dir:
        ap.error("give --root <project> or --bench-dir <harness folder>")
    make_mcp(NavServer(a.root, a.memory, a.setup_cmd or None, a.test_cmd, a.log,
                       a.condition, a.bug, a.root_cause, a.run_label, a.bench_dir)).run()


if __name__ == "__main__":
    main()
