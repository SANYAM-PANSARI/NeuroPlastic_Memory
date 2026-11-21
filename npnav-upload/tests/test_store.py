import pytest

from navmem.store import DeadEdgeError, Node, Store


@pytest.fixture
def store():
    s = Store()
    s.upsert_node(Node("err:Payment TimeoutError after <N>s", "err", "logs/app.log"))
    s.upsert_node(Node("cfg:AUTH_POOL_SIZE", "cfg", "config.yaml#AUTH_POOL_SIZE"))
    return s


SRC, DST = "err:Payment TimeoutError after <N>s", "cfg:AUTH_POOL_SIZE"


def test_new_edge_starts_at_one(store):
    e = store.upsert_edge(SRC, DST, "causes", why="pool too small")
    assert e.strength == 1.0 and e.status == "live"


def test_strength_is_capped(store):
    store.upsert_edge(SRC, DST, "causes")
    for _ in range(30):
        e = store.upsert_edge(SRC, DST, "causes", delta=0.3)
    assert e.strength == 5.0


def test_dead_edge_cannot_be_relearned(store):
    e = store.upsert_edge(SRC, DST, "causes")
    store.kill_edge(e.id, "pool raised to 50, timeouts persisted")
    with pytest.raises(DeadEdgeError):
        store.upsert_edge(SRC, DST, "causes", delta=0.3)
    assert store.edges_from(SRC) == []  # dead edges are hidden from traversal


def test_trust_never_drops(store):
    store.upsert_edge(SRC, DST, "causes", trust="verified")
    e = store.upsert_edge(SRC, DST, "causes", delta=0.05, trust="provisional")
    assert e.trust == "verified"


def test_every_change_is_logged(store):
    e = store.upsert_edge(SRC, DST, "causes")
    store.upsert_edge(SRC, DST, "causes", delta=-0.1)
    store.kill_edge(e.id, "misled 3 times")
    actions = [ev["action"] for ev in store.events_for(e.id)]
    assert actions == ["add", "weaken", "kill"]
