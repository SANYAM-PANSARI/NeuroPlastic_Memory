"""Checkout: reserves auth connections, then charges payment."""
from services.auth.auth_service import AuthService
from services.common import load_config, log
from services.payments.client import charge


class CheckoutHang(Exception):
    pass


def place_order(order_id: int) -> str:
    cfg = load_config()["checkout"]
    try:
        AuthService().connect(cfg["CHECKOUT_CONCURRENCY"])
    except TimeoutError:
        log(f"WARN Checkout hangs waiting for auth (order_id={order_id})")
        raise CheckoutHang(order_id)
    return charge(order_id)
