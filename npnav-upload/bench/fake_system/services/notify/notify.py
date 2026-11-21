"""Notify: sends receipt emails. Finds its auth backend by NAME from config (no import)."""
import importlib

from services.common import load_config, log


class ReceiptStuck(Exception):
    pass


def send_receipt(order_id: int) -> str:
    cfg = load_config()["notify"]
    backend = importlib.import_module(cfg["AUTH_BACKEND"])  # dynamic: parsers can't see this link
    try:
        backend.AuthService().connect(cfg["NOTIFY_CONCURRENCY"])
    except TimeoutError:
        log(f"WARN Receipt emails stuck in queue (order_id={order_id})")
        raise ReceiptStuck(order_id)
    return f"receipt sent for order {order_id}"
