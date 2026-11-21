"""Embedding entry: paraphrased errors should find the stored err node; overlap switch still works."""
import pytest

from navmem import embed
from navmem.recall import entry_nodes
from navmem.store import Node, Store

needs_model = pytest.mark.skipif(not embed.enabled(), reason="sentence-transformers not installed")


def make_store(tmp_path):
    s = Store(str(tmp_path / "m.db"))
    s.upsert_node(Node("err:auth pool exhausted, waited <N>s", "err", "symptom", "pool"))
    s.upsert_node(Node("err:receipt template missing", "err", "symptom", "receipt"))
    return s


@needs_model
def test_paraphrase_matches(tmp_path):
    s = make_store(tmp_path)
    got = entry_nodes(s, "no free database connections in the auth pool after 5s")
    assert "err:auth pool exhausted, waited <N>s" in got
    assert "err:receipt template missing" not in got


@needs_model
def test_unrelated_symptom_matches_nothing(tmp_path):
    s = make_store(tmp_path)
    assert not [n for n in entry_nodes(s, "disk quota exceeded on upload") if n.startswith("err:")]


def test_overlap_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVMEM_ENTRY", "overlap")
    s = make_store(tmp_path)
    assert "err:auth pool exhausted, waited <N>s" in entry_nodes(s, "ERROR auth pool exhausted, waited 30s")
    assert entry_nodes(s, "no free database connections in the auth pool") == {}
