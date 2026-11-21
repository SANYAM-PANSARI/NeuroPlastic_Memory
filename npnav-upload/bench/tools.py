"""The agent's tools, sandboxed to one work folder.

Every call is recorded (tool, args, and the terms seen in its output) so the runner can
measure navigation and navmem can learn led_to chains from the trail.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

SKIP = {"__pycache__", ".pytest_cache"}
TERM = re.compile(r"[A-Za-z_][A-Za-z0-9_./]{3,}")


class Toolbox:
    def __init__(self, workdir: Path):
        self.root = workdir.resolve()
        self.calls: list[dict] = []
        self.claim: dict | None = None
        self.edits: list[dict] = []

    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("path outside the project")
        return p

    def _files(self):
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and not (SKIP & set(p.parts)) and p.suffix not in {".db", ".pyc"}:
                yield p

    # ---- tools the model can call ----
    def list_dir(self, path: str = ".") -> str:
        """List files and folders under a path in the project."""
        p = self._safe(path)
        return "\n".join(str(c.relative_to(self.root)) + ("/" if c.is_dir() else "")
                         for c in sorted(p.iterdir()) if c.name not in SKIP)

    def read_file(self, path: str) -> str:
        """Read a text file in the project, e.g. services/payments/client.py or config.yaml."""
        p = self._safe(path)
        if p.suffix == ".db":
            return "error: this is a database; use query_db"
        return p.read_text()[:4000]

    def grep(self, pattern: str) -> str:
        """Search all project files for a regex. Returns file:line: text."""
        rx = re.compile(pattern)
        hits = []
        for f in self._files():
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(self.root)}:{i}: {line.strip()}")
        return "\n".join(hits[:40]) or "no matches"

    def query_db(self, sql: str) -> str:
        """Run a read-only SELECT on data/orders.db."""
        if not sql.strip().lower().startswith("select"):
            return "error: only SELECT is allowed"
        con = sqlite3.connect(self.root / "data" / "orders.db")
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            return "\n".join([", ".join(cols)] + [", ".join(map(str, r)) for r in cur.fetchmany(20)])
        except sqlite3.Error as e:
            return f"error: {e}"
        finally:
            con.close()

    def read_logs(self) -> str:
        """Read the application log (logs/app.log)."""
        p = self.root / "logs" / "app.log"
        return p.read_text()[-4000:] if p.exists() else "no logs"

    def edit_file(self, path: str, find: str, replace: str) -> str:
        """Fix a file by replacing the exact text `find` with `replace` (first match only)."""
        p = self._safe(path)
        text = p.read_text()
        if find not in text:
            return "error: text not found; read the file and copy the exact text"
        p.write_text(text.replace(find, replace, 1))
        self.edits.append({"path": path, "find": find, "replace": replace})
        return "edited"

    def run_tests(self) -> str:
        """Run the project's tests. Use it after a fix to check it worked."""
        subprocess.run([sys.executable, "make_db.py"], cwd=self.root, capture_output=True)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "tests"], cwd=self.root,
                           capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        return ("PASSED: " if r.returncode == 0 else "FAILED: ") + "\n".join(out[-12:])

    def done(self, summary: str) -> str:
        """Call once when the tests pass (or you cannot fix it). Summarize the root cause."""
        self.claim = {"summary": summary}
        return "recorded"

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if name.startswith("_") or name in {"call", "specs"} or not callable(fn):
            out = f"error: unknown tool {name}"
        else:
            try:
                out = fn(**args)
            except TypeError as e:
                out = f"error: bad arguments ({e})"
            except Exception as e:  # report tool errors back to the model
                out = f"error: {e}"
        self.calls.append({"tool": name, "args": args, "terms": sorted(set(TERM.findall(str(out))))[:300]})
        return out

    def specs(self) -> list:
        """Python functions; the ollama client turns docstrings + type hints into tool schemas."""
        return [self.list_dir, self.read_file, self.grep, self.query_db, self.read_logs,
                self.edit_file, self.run_tests, self.done]
