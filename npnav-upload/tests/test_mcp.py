"""MCP server logic: a full task through the server's tools, learning only on a verified fix."""
import json
import subprocess
import sys

from bench.setup_bug import load_bugs, setup
from navmem.mcp_server import NavServer

PY = sys.executable


def server(tmp_path, bug="auth-pool-too-small"):
    wd = setup(bug, tmp_path / "w")
    subprocess.run([PY, "make_db.py"], cwd=wd, check=True)
    subprocess.run([PY, "-m", "pytest", "-q", "tests"], cwd=wd, capture_output=True)   # writes logs
    return NavServer(str(wd), ":memory:", f"{PY} make_db.py", f"{PY} -m pytest -q tests",
                     str(tmp_path / "log.jsonl")), load_bugs()[bug]["symptom"]


def test_verified_fix_through_the_server_is_learned(tmp_path):
    nav, symptom = server(tmp_path)
    assert "task_id" in nav.start_task(symptom)
    nav.tool("read_logs", {})
    nav.tool("read_file", {"path": "config.yaml"})
    nav.tool("edit_file", {"path": "config.yaml", "find": "AUTH_POOL_SIZE: 2", "replace": "AUTH_POOL_SIZE: 8"})
    assert nav.tool("run_tests", {}).startswith("PASSED")
    res = json.loads(nav.finish_task("pool too small"))
    assert res["tests_passed"] and "cfg:AUTH_POOL_SIZE" in res["fixed"] and res["links_learned"] >= 1
    assert "AUTH_POOL_SIZE" in nav.recall(symptom).splitlines()[1]          # now hint #1
    events = [json.loads(l)["event"] for l in open(tmp_path / "log.jsonl")]
    assert events[0] == "start_task" and events[-1] == "finish_task"         # everything was logged


def test_unverified_finish_learns_nothing(tmp_path):
    nav, symptom = server(tmp_path)
    nav.start_task(symptom)
    nav.tool("read_logs", {})
    res = json.loads(nav.finish_task("just a guess"))
    assert not res["tests_passed"] and res["links_learned"] == 0


def test_tools_need_a_task(tmp_path):
    nav, _ = server(tmp_path)
    try:
        nav.tool("read_logs", {})
        assert False
    except ValueError as e:
        assert "start_task" in str(e)


def test_benchmark_log_and_analysis(tmp_path):
    """Control run gets no hints and learns nothing; memory run learns; analysis reads both."""
    from navmem.analyze_harness import load
    log, mem = tmp_path / "ag.jsonl", str(tmp_path / "mem.db")
    for cond in ("none", "memory"):
        wd = setup("auth-pool-too-small", tmp_path / cond)
        subprocess.run([PY, "make_db.py"], cwd=wd, check=True)
        nav = NavServer(str(wd), mem if cond == "memory" else ":memory:", f"{PY} make_db.py",
                        f"{PY} -m pytest -q tests", str(log), cond, "auth-pool-too-small",
                        "config.yaml#AUTH_POOL_SIZE", "r1")
        out = nav.start_task("Payments are failing: Payment TimeoutError after 2s (order_id=1)")
        assert ("No hints in this run" in out) == (cond == "none")
        nav.tool("read_file", {"path": "services/payments/client.py"})
        nav.tool("read_file", {"path": "config.yaml"})
        nav.tool("edit_file", {"path": "config.yaml", "find": "AUTH_POOL_SIZE: 2", "replace": "AUTH_POOL_SIZE: 8"})
        res = json.loads(nav.finish_task("pool"))
        assert res["tests_passed"] and res["fixed_root_cause"] and res["nav_calls_to_root"] == 1
        assert (res["links_learned"] > 0) == (cond == "memory")
    rows = load(log)
    assert [r["condition"] for r in rows] == ["none", "memory"]
    assert all(r["outside_tools"] is False for r in rows)


def test_bench_mode_one_server_many_bugs(tmp_path):
    """One server: each start_task plants the bug named in current_run.json."""
    from navmem.bench_next import set_next
    nav = NavServer(None, ":memory:", f"{PY} make_db.py", f"{PY} -m pytest -q tests",
                    str(tmp_path / "log.jsonl"), bench_dir=str(tmp_path))
    set_next("auth-pool-too-small", "memory", "r1", tmp_path)
    nav.start_task("Payments are failing: Payment TimeoutError after 2s (order_id=1)")
    nav.tool("edit_file", {"path": "config.yaml", "find": "AUTH_POOL_SIZE: 2", "replace": "AUTH_POOL_SIZE: 8"})
    r1 = json.loads(nav.finish_task("pool"))
    assert r1["tests_passed"] and r1["links_learned"] >= 1
    set_next("payments-timeout-drift", "none", "r1", tmp_path)              # switch bug, no reconnect
    out = nav.start_task("Payments are failing: Payment TimeoutError after 2s (order_id=1)")
    assert "No hints in this run" in out and nav.bug == "payments-timeout-drift"
    assert "drift" in str(nav.root)


def test_install_mcp_merges_and_backs_up(tmp_path, monkeypatch):
    import navmem.install_mcp as im
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    monkeypatch.setattr(sys, "argv", ["x", "--config", str(cfg)])
    monkeypatch.setattr(im, "HARNESS", tmp_path / "harness")
    im.main()
    data = json.loads(cfg.read_text())
    assert set(data["mcpServers"]) == {"other", "navmem"} and (tmp_path / "mcp_config.json.bak").exists()
