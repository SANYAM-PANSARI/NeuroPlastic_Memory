"""One scoring rule shared by the local benchmark, the MCP server and the log analysis."""
from __future__ import annotations


def matches(fix: str, node: str) -> bool:
    """'config.yaml#AUTH_POOL_SIZE' matches cfg:AUTH_POOL_SIZE; 'services/x.py' matches file:services/x.py;
    'make_db.py#orders.amount_cents' matches cfg/col ending in amount_cents or file:make_db.py."""
    path, _, key = fix.partition("#")
    key = key.split(".")[-1] if key else ""
    return (bool(key) and node.endswith(key)) or node == f"file:{path}"


def score_fix(bug: dict, fixed_nodes: list[str], tests_passed: bool) -> dict:
    accepted = bug.get("accepted_fixes") or [bug["root_cause"]]
    hit = next((f for f in accepted if any(matches(f, n) for n in fixed_nodes)), None)
    if not tests_passed:
        choice = "none"
    elif hit is None:
        choice = "other"                       # tests pass but not a known fix: inspect by hand
    else:
        choice = "intended" if hit == accepted[0] else "fallback"
    return {"fixed_root_cause": bool(tests_passed and hit), "fix_choice": choice}
