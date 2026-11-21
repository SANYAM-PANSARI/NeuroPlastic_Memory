from services.checkout.checkout import place_order
from services.notify.notify import send_receipt
from services.payments.client import charge


def test_payment_charges():
    assert charge(1) == "charged 1999 for order 1"


def test_checkout_places_order():
    assert place_order(2) == "charged 4500 for order 2"


def test_receipt_sent():
    assert send_receipt(3) == "receipt sent for order 3"
