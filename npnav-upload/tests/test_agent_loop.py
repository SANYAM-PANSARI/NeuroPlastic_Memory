"""Tools stay inside the sandbox and the new edit/test tools behave."""
import subprocess
import sys

from bench.setup_bug import load_bugs, setup
from bench.tools import Toolbox


def test_tools_stay_in_sandbox(tmp_path):
    box = Toolbox(tmp_path)
    assert box.call("read_file", {"path": "../../etc/passwd"}).startswith("error")
    assert box.call("query_db", {"sql": "DROP TABLE orders"}).startswith("error")


def test_edit_then_run_tests_reports_pass(tmp_path):
    wd = setup("auth-pool-too-small", tmp_path / "w")
    subprocess.run([sys.executable, "make_db.py"], cwd=wd, check=True)
    box = Toolbox(wd)
    assert box.call("run_tests", {}).startswith("FAILED")
    assert box.call("edit_file", {"path": "config.yaml", "find": "AUTH_POOL_SIZE: 2",
                                  "replace": "AUTH_POOL_SIZE: 8"}) == "edited"
    assert box.call("run_tests", {}).startswith("PASSED")
    assert box.call("read_file", {"path": "data/orders.db"}).startswith("error")
