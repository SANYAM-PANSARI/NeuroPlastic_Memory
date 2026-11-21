import yaml

from navmem.normalize import normalize_template
from navmem.recall import recall
from navmem.static_graph import build
from navmem.store import Store


def graph():
    s = Store()
    build("bench/fake_system", s)
    return s


def symptom(bug_id):
    return {b["id"]: b for b in yaml.safe_load(open("bench/bugs.yaml"))}[bug_id]["symptom"]


def test_normalize_strips_numbers_keeps_words():
    a = normalize_template("ERROR Payment TimeoutError after 30s (order_id=88213)")
    b = normalize_template("Payment TimeoutError after 45s (order_id=10457)")
    assert a == b == "Payment TimeoutError after <N>s (order_id=<N>)"


def test_static_graph_finds_config_reads_and_log_templates():
    s = graph()
    assert s.get_node("cfg:AUTH_POOL_SIZE") is not None
    assert s.get_edge("fn:services.auth.auth_service.AuthService", "cfg:AUTH_POOL_SIZE", "reads_config")
    assert s.get_node("err:Payment TimeoutError after <N>s (order_id=<N>)") is not None


def test_recall_starts_at_the_function_that_logs_the_error():
    hints = recall(graph(), symptom("auth-pool-too-small"))
    assert hints[0].pointer == "services/payments/client.py#charge"


def test_utility_hubs_do_not_crowd_out_hints():
    hints = recall(graph(), symptom("auth-pool-too-small"))
    assert "services/common.py#log" not in [h.pointer for h in hints]


def test_no_entry_means_no_hints():
    assert recall(graph(), "Payments crash with IndexError: No item with that key") == []
