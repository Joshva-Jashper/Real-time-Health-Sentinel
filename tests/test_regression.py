from testsentry.regression_detector import label_test, get_regression_summary
from testsentry.collector import store_result, init_db


def test_new_test_label():
    """First time seeing a test — should be NEW_TEST."""
    result = {
        "test_name": "tests/test_new_unique_xyz.py::test_brand_new",
        "status": "PASSED",
        "error_msg": None,
        "duration": 0.001
    }
    label = label_test(result, "run_test_001")
    assert label == "NEW_TEST"


def test_first_seen_failure_is_new_test():
    result = {
        "test_name": "tests/test_new_unique_xyz.py::test_first_failure",
        "status": "FAILED",
        "error_msg": "AssertionError",
        "duration": 0.001,
    }
    assert label_test(result, "run_first_failure") == "NEW_TEST"


def test_newly_failing_label():
    """Was passing, now failing — should be NEWLY_FAILING."""
    
    prev_result = {
        "test_name": "tests/test_reg.py::test_checkout",
        "status": "PASSED",
        "error_msg": None,
        "duration": 0.001
    }
    store_result(prev_result, "run_prev_001", "STABLE")

    
    curr_result = {
        "test_name": "tests/test_reg.py::test_checkout",
        "status": "FAILED",
        "error_msg": "AssertionError",
        "duration": 0.002
    }
    label = label_test(curr_result, "run_curr_001")
    assert label == "NEWLY_FAILING"


def test_fixed_label():
    """Was failing, now passing — should be FIXED."""
   
    prev_result = {
        "test_name": "tests/test_reg.py::test_payment",
        "status": "FAILED",
        "error_msg": "AssertionError",
        "duration": 0.001
    }
    store_result(prev_result, "run_prev_002", "STILL_FAILING")

    curr_result = {
        "test_name": "tests/test_reg.py::test_payment",
        "status": "PASSED",
        "error_msg": None,
        "duration": 0.001
    }
    label = label_test(curr_result, "run_curr_002")
    assert label == "FIXED"


def test_stable_label():
    """Was passing, still passing — should be STABLE."""
    prev_result = {
        "test_name": "tests/test_reg.py::test_login",
        "status": "PASSED",
        "error_msg": None,
        "duration": 0.001
    }
    store_result(prev_result, "run_prev_003", "STABLE")

    curr_result = {
        "test_name": "tests/test_reg.py::test_login",
        "status": "PASSED",
        "error_msg": None,
        "duration": 0.001
    }
    label = label_test(curr_result, "run_curr_003")
    assert label == "STABLE"


def test_summary_accumulates_mixed_new_passed_and_failed_tests():
    """A first run with 11 passes and 11 failures has 22 new tests."""
    run_id = "run_mixed_new_022"
    for index in range(11):
        store_result({
            "test_name": f"tests/test_new.py::test_pass_{index}",
            "status": "PASSED",
            "error_msg": None,
            "duration": 0.001,
        }, run_id, "NEW_TEST")
    for index in range(11):
        store_result({
            "test_name": f"tests/test_new.py::test_fail_{index}",
            "status": "FAILED",
            "error_msg": "AssertionError",
            "duration": 0.001,
        }, run_id, "NEW_TEST")

    summary = get_regression_summary(run_id)

    assert summary["NEW_TEST"] == 22
    assert summary["NEWLY_FAILING"] == 11
