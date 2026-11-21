"""Day-1 static layer: parse a Python project into location nodes and edges. No LLM.

Nodes: file:, fn: (functions and classes), cfg: (config keys), table:, err: (log message templates)
Edges: imports, contains, calls, reads_config, queries, emits
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

from navmem.normalize import normalize_template
from navmem.store import Node, Store

SKIP = {"__pycache__", ".pytest_cache", "tests", "data", "logs"}


def _module_name(root: Path, f: Path) -> str:
    return ".".join(f.relative_to(root).with_suffix("").parts)


def _config_keys(root: Path) -> dict[str, str]:
    """Leaf keys of config.yaml -> pointer."""
    p = root / "config.yaml"
    if not p.exists():
        return {}
    keys = {}

    def walk(d):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v)
            else:
                keys[k] = f"config.yaml#{k}"
    walk(yaml.safe_load(p.read_text()) or {})
    return keys


def _fstring_template(node: ast.JoinedStr) -> str:
    parts = []
    for v in node.values:
        parts.append(v.value if isinstance(v, ast.Constant) else "{x}")
    return "".join(parts)


def build(root: str | Path, store: Store) -> dict:
    root = Path(root).resolve()
    files = [f for f in root.rglob("*.py") if not (SKIP & set(f.relative_to(root).parts))]
    cfg_keys = _config_keys(root)
    counts = {"nodes": 0, "edges": 0}

    def node(id_, type_, pointer, desc=""):
        store.upsert_node(Node(id_, type_, pointer, desc))
        counts["nodes"] += 1

    def edge(src, dst, type_, why):
        store.upsert_edge(src, dst, type_, why=why, trust="static", source="static")
        counts["edges"] += 1

    if (root / "config.yaml").exists():
        node("file:config.yaml", "file", "config.yaml", "configuration")
        for k, ptr in cfg_keys.items():
            node(f"cfg:{k}", "cfg", ptr, f"config key {k}")
            edge("file:config.yaml", f"cfg:{k}", "contains", f"{k} is set in config.yaml")

    modules = {_module_name(root, f): f for f in files}
    for f in files:
        rel = str(f.relative_to(root)).replace("\\", "/")
        mod = _module_name(root, f)
        fid = f"file:{rel}"
        node(fid, "file", rel, f"module {mod}")
        tree = ast.parse(f.read_text())

        # imported names -> fully qualified target
        imported: dict[str, str] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module in modules:
                edge(fid, f"file:{str(modules[n.module].relative_to(root)).replace(chr(92), '/')}",
                     "imports", f"{rel} imports {n.module}")
                for a in n.names:
                    imported[a.asname or a.name] = f"{n.module}.{a.name}"

        # SQL tables anywhere in this file
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                for t in re.findall(r"(?:FROM|TABLE|INTO)\s+(\w+)", n.value, re.I):
                    node(f"table:{t}", "table", f"data/orders.db#{t}", f"database table {t}")
                    edge(fid, f"table:{t}", "queries", f"{rel} uses table {t}")

        for top in tree.body:
            if not isinstance(top, (ast.FunctionDef, ast.ClassDef)):
                continue
            sid = f"fn:{mod}.{top.name}"
            node(sid, "fn", f"{rel}#{top.name}", f"{'class' if isinstance(top, ast.ClassDef) else 'function'} {top.name} in {rel}")
            edge(fid, sid, "contains", f"{top.name} is defined in {rel}")
            for n in ast.walk(top):
                # calls to imported names
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in imported:
                    target = f"fn:{imported[n.func.id]}"
                    if store.get_node(target) is None:
                        tmod, tname = imported[n.func.id].rsplit(".", 1)
                        if tmod in modules:
                            trel = str(modules[tmod].relative_to(root)).replace("\\", "/")
                            node(target, "fn", f"{trel}#{tname}", f"{tname} in {trel}")
                    if store.get_node(target):
                        edge(sid, target, "calls", f"{top.name} calls {n.func.id}")
                # config keys read as string subscripts: cfg["AUTH_POOL_SIZE"]
                if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                        and n.slice.value in cfg_keys:
                    edge(sid, f"cfg:{n.slice.value}", "reads_config",
                         f"{top.name} reads {n.slice.value}")
                # log message templates -> err nodes
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "log" \
                        and n.args and isinstance(n.args[0], ast.JoinedStr):
                    tmpl = normalize_template(_fstring_template(n.args[0]))
                    eid = f"err:{tmpl}"
                    node(eid, "err", f"{rel}#{top.name}", f"log message: {tmpl}")
                    edge(eid, sid, "emitted_by", f"'{tmpl}' is logged by {top.name}")
    return counts
