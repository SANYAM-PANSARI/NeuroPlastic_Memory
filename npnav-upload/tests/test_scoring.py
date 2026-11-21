from bench.scoring import score_fix
from bench.setup_bug import load_bugs

BUGS = load_bugs()


def test_intended_fix():
    assert score_fix(BUGS["payments-timeout-drift"], ["cfg:PAYMENT_CONCURRENCY"], True) == \
        {"fixed_root_cause": True, "fix_choice": "intended"}


def test_valid_fallback_counts_as_correct_and_is_labelled():
    assert score_fix(BUGS["payments-timeout-drift"], ["cfg:AUTH_POOL_SIZE"], True) == \
        {"fixed_root_cause": True, "fix_choice": "fallback"}


def test_tests_failing_is_never_correct():
    assert score_fix(BUGS["payments-timeout-drift"], ["cfg:PAYMENT_CONCURRENCY"], False)["fixed_root_cause"] is False


def test_unknown_fix_is_flagged_for_inspection():
    assert score_fix(BUGS["auth-pool-too-small"], ["cfg:CHECKOUT_CONCURRENCY"], True)["fix_choice"] == "other"


def test_code_fallback_for_renamed_column():
    assert score_fix(BUGS["amount-column-renamed"], ["file:services/payments/client.py"], True)["fix_choice"] == "fallback"
    assert score_fix(BUGS["amount-column-renamed"], ["file:make_db.py"], True)["fix_choice"] == "intended"
