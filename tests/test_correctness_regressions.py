from testsentry.collector import init_db, store_result
from testsentry.regression_detector import label_test

def test_reopened_label_after_fix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_db()
    name = "tests/test_x.py::test_reopen"
    for run_id, status in (("r1", "PASSED"), ("r2", "FAILED"), ("r3", "PASSED")):
        result = {"test_name": name, "status": status, "error_msg": "boom" if status == "FAILED" else None, "duration": 0.1}
        store_result(result, run_id, label_test(result, run_id))
    result = {"test_name": name, "status": "FAILED", "error_msg": "boom", "duration": 0.1}
    assert label_test(result, "r4") == "REOPENED"
