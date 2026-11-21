"""Copy fake_system into a work folder, apply one bug, check its tests now fail.

Usage: python bench/setup_bug.py <bug_id> [workdir]
"""
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

BENCH = Path(__file__).resolve().parent


def load_bugs() -> dict:
    return {b["id"]: b for b in yaml.safe_load((BENCH / "bugs.yaml").read_text())}


def run_tests(workdir: Path) -> bool:
    subprocess.run([sys.executable, "make_db.py"], cwd=workdir, check=True)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=workdir,
                       capture_output=True, text=True)
    return r.returncode == 0


def setup(bug_id: str, workdir: Path) -> Path:
    bug = load_bugs()[bug_id]
    if workdir.exists():
        shutil.rmtree(workdir)
    shutil.copytree(BENCH / "fake_system", workdir,
                    ignore=shutil.ignore_patterns("data", "logs", "__pycache__", ".pytest_cache"))
    target = workdir / bug["patch"]["file"]
    text = target.read_text()
    if bug["patch"]["find"] not in text:
        raise ValueError(f"patch text not found in {target}")
    target.write_text(text.replace(bug["patch"]["find"], bug["patch"]["replace"], 1))
    return workdir


if __name__ == "__main__":
    bug_id = sys.argv[1]
    wd = Path(sys.argv[2]) if len(sys.argv) > 2 else BENCH / "work" / bug_id
    setup(bug_id, wd)
    print(f"{bug_id}: tests pass = {run_tests(wd)} (expected False)")
