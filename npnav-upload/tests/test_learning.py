"""End-to-end learning loop with a scripted agent (no LLM needed)."""
from bench.agent import ToolCall
from bench.run import run_one
from bench.setup_bug import BENCH, load_bugs
from navmem.forget import KILL_AFTER, feedback
from navmem.learn import ledto_pairs
from navmem.recall import recall
from navmem.static_graph import build
from navmem.store import Store

BUGS = load_bugs()


class ScriptedModel:
    def __init__(self, script):
        self.script = list(script)

    def step(self, messages, tools):
        return {"role": "assistant", "content": ""}, [self.script.pop(0)] if self.script else []


def fix_pool_script():
    """What a good debugger does for auth-pool-too-small."""
    return [
        ToolCall("read_logs", {}),
        ToolCall("read_file", {"path": "services/payments/client.py"}),
        ToolCall("read_file", {"path": "services/auth/auth_service.py"}),
        ToolCall("read_file", {"path": "config.yaml"}),
        ToolCall("edit_file", {"path": "config.yaml", "find": "AUTH_POOL_SIZE: 2", "replace": "AUTH_POOL_SIZE: 8"}),
        ToolCall("run_tests", {}),
        ToolCall("done", {"summary": "auth pool smaller than payment concurrency"}),
    ]


def memory():
    s = Store()
    build(BENCH / "fake_system", s)
    return s


def test_verified_fix_is_learned_and_recalled_first_next_time():
    store = memory()
    before = [h.pointer for h in recall(store, BUGS["auth-pool-too-small"]["symptom"])]
    assert "config.yaml#AUTH_POOL_SIZE" not in before            # static layer can't reach it

    row = run_one(ScriptedModel(fix_pool_script()), BUGS["auth-pool-too-small"], "learned",
                  store, 1, max_steps=10, time_limit=60)
    assert row["success"] and row["fixed_root_cause"] and row["links_learned"] >= 1

    after = recall(store, BUGS["auth-pool-too-small"]["symptom"])
    assert after[0].pointer == "config.yaml#AUTH_POOL_SIZE"      # learned shortcut now ranks first


def test_failed_run_teaches_nothing():
    store = memory()
    bad = [ToolCall("read_logs", {}), ToolCall("done", {"summary": "no idea"})]
    row = run_one(ScriptedModel(bad), BUGS["auth-pool-too-small"], "learned", store, 1, 10, 60)
    assert not row["success"] and row["links_learned"] == 0


def test_misleading_link_dies_after_three_misses_and_stays_dead():
    store = memory()
    run_one(ScriptedModel(fix_pool_script()), BUGS["auth-pool-too-small"], "learned", store, 1, 10, 60)
    drift = BUGS["payments-timeout-drift"]["symptom"]             # same symptom, different cause
    for _ in range(KILL_AFTER):
        hints = recall(store, drift)
        top = hints[0]
        assert top.pointer == "config.yaml#AUTH_POOL_SIZE"
        feedback(store, task_id="t", hints=[top], read_paths={"config.yaml"},
                 fixed_nodes=["cfg:PAYMENT_CONCURRENCY"], success=True)
    assert "config.yaml#AUTH_POOL_SIZE" not in [h.pointer for h in recall(store, drift)][:1]
    dead = store.db.execute("SELECT dead_reason FROM edges WHERE status='dead'").fetchall()
    assert dead and "misled 3 times" in dead[0][0]


def test_ledto_follows_a_term_seen_in_the_previous_read():
    calls = [
        {"tool": "read_file", "args": {"path": "services/payments/client.py"}, "terms": ["auth_service", "AuthService"]},
        {"tool": "grep", "args": {"pattern": "AuthService"}, "terms": []},
        {"tool": "read_file", "args": {"path": "services/auth/auth_service.py"}, "terms": ["AUTH_POOL_SIZE"]},
    ]
    pairs = ledto_pairs(calls)
    assert pairs and pairs[0][:2] == ("services/payments/client.py", "services/auth/auth_service.py")


def test_common_words_do_not_create_links():
    calls = [
        {"tool": "read_file", "args": {"path": "a.py"}, "terms": ["config", "error"]},
        {"tool": "grep", "args": {"pattern": "config"}, "terms": []},
        {"tool": "read_file", "args": {"path": "b.py"}, "terms": []},
    ]
    assert ledto_pairs(calls) == []


def test_side_hint_through_the_fix_does_not_punish_the_correct_link():
    """Regression from the Antigravity run: the learned link err -> AUTH_POOL_SIZE was killed because
    side hints whose path passed through it (read config.yaml, read AuthService) were 'followed'
    and were not themselves the fix, even though the fix WAS AUTH_POOL_SIZE."""
    store = memory()
    sym = BUGS["auth-pool-too-small"]["symptom"]
    run_one(ScriptedModel(fix_pool_script()), BUGS["auth-pool-too-small"], "learned", store, 1, 10, 60)
    for _ in range(4):                                    # more than KILL_AFTER rounds
        hints = recall(store, sym)
        side = [h for h in hints if h.node_id != "cfg:AUTH_POOL_SIZE"
                and "cfg:AUTH_POOL_SIZE" in path_nodes(store, h)]
        assert side, "expected side hints that pass through the learned fix"
        feedback(store, task_id="t", hints=side, read_paths={h.pointer.split('#')[0] for h in side},
                 fixed_nodes=["cfg:AUTH_POOL_SIZE"], success=True)
    e = store.get_edge("err:Payment TimeoutError after <N>s (order_id=<N>)", "cfg:AUTH_POOL_SIZE", "causes")
    assert e.status == "live" and e.misled_count == 0


def path_nodes(store, hint):
    out = set()
    for eid in hint.edge_ids:
        e = store.get_edge_by_id(eid)
        out |= {e.src, e.dst}
    return out


def fix_gateway_script():
    return [
        ToolCall("read_logs", {}),
        ToolCall("read_file", {"path": "config.yaml"}),
        ToolCall("read_file", {"path": "services/payments/client.py"}),
        ToolCall("edit_file", {"path": "config.yaml", "find": "PAYMENT_GATEWAY_TIMEOUT_MS: 100",
                               "replace": "PAYMENT_GATEWAY_TIMEOUT_MS: 1000"}),
        ToolCall("run_tests", {}),
        ToolCall("done", {"summary": "gateway timeout below gateway latency"}),
    ]


def test_gateway_drift_unlearns_the_pool_and_learns_the_gateway():
    """The declared forgetting test: the old pool shortcut misleads on the gateway bug until it dies,
    while the gateway fix is learned."""
    store = memory()
    run_one(ScriptedModel(fix_pool_script()), BUGS["auth-pool-too-small"], "learned", store, 1, 10, 60)
    gw = BUGS["payments-gateway-drift"]
    assert recall(store, gw["symptom"])[0].pointer == "config.yaml#AUTH_POOL_SIZE"   # old answer first
    for i in range(3):
        row = run_one(ScriptedModel(fix_gateway_script()), gw, "learned", store, i + 1, 10, 60)
        assert row["success"] and row["fix_choice"] == "intended"
    pool = store.get_edge("err:Payment TimeoutError after <N>s (order_id=<N>)", "cfg:AUTH_POOL_SIZE", "causes")
    assert pool.status == "dead"
    assert recall(store, gw["symptom"])[0].pointer == "config.yaml#PAYMENT_GATEWAY_TIMEOUT_MS"
