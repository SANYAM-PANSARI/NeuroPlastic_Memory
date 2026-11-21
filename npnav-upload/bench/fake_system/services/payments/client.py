"""Payments client: charges an order using several auth connections."""
import sqlite3

from services.auth.auth_service import AuthService
from services.common import ROOT, load_config, log


class PaymentTimeoutError(Exception):
    pass


GATEWAY_LATENCY_MS = 300   # the payment gateway takes this long to answer


def get_amount(order_id: int) -> int:
    db = ROOT / load_config()["db"]["DB_PATH"]
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    con.close()
    return row["amount_cents"]


def charge(order_id: int) -> str:
    cfg = load_config()["payments"]
    auth = AuthService()
    try:
        auth.connect(cfg["PAYMENT_CONCURRENCY"])
    except TimeoutError:
        log(f"ERROR Payment TimeoutError after {auth.timeout_s}s (order_id={order_id})")
        raise PaymentTimeoutError(order_id)
    timeout_ms = cfg["PAYMENT_GATEWAY_TIMEOUT_MS"]
    if timeout_ms < GATEWAY_LATENCY_MS:            # we give up before the gateway answers
        log(f"ERROR Payment TimeoutError after {timeout_ms / 1000}s (order_id={order_id})")
        raise PaymentTimeoutError(order_id)
    amount = get_amount(order_id)
    return f"charged {amount} for order {order_id}"
