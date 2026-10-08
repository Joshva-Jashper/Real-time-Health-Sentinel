from datetime import datetime, timedelta
import json

from fastapi.testclient import TestClient

from testsentry import api
from testsentry.collector import get_connection, start_run_metadata, store_result, store_run_metadata
from testsentry.evidence import capture_failure


def test_live_endpoint_reports_incremental_counts():
    run_id = "live-dashboard-run"
    start_run_metadata(run_id, datetime.now())
    store_result({"test_name": "tests/test_live.py::test_pass", "status": "PASSED", "duration": 0.1}, run_id, "NEW_TEST")
    store_result({"test_name": "tests/test_live.py::test_fail", "status": "FAILED", "duration": 0.2, "error_msg": "AssertionError"}, run_id, "NEW_TEST")

    response = TestClient(api.app).get("/api/live", params={"run_id": run_id})
    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is True
    assert payload["completed"] == 2
    assert payload["passed"] == 1
    assert payload["failed"] == 1


def test_analytics_endpoint_returns_quality_trends():
    run_id = "analytics-dashboard-run"
    started = datetime.now() - timedelta(seconds=2)
    store_result({"test_name": "tests/test_analytics.py::test_one", "status": "PASSED", "duration": 0.15}, run_id, "NEW_TEST")
    store_result({"test_name": "tests/test_analytics.py::test_two", "status": "FAILED", "duration": 0.25, "error_msg": "boom"}, run_id, "NEW_TEST")
    store_run_metadata(run_id, started, datetime.now(), 2, 1, 1)

    response = TestClient(api.app).get("/api/analytics")
    assert response.status_code == 200
    row = next(item for item in response.json() if item["run_id"] == run_id)
    assert row["pass_rate"] == 50.0
    assert row["failure_frequency"] == 50.0
    assert row["avg_duration"] == 0.2
    assert "health_score" in row and "flaky_count" in row


def test_evidence_endpoint_lists_files_and_downloads_bundle(tmp_path):
    run_id = "evidence-dashboard-run"
    test_name = "tests/test_browser.py::test_login"
    bundle = capture_failure(tmp_path, test_name, "AssertionError: expected", metadata={"browser": "fake"})
    (bundle.path / "page.html").write_text("<html><body>failure</body></html>", encoding="utf-8")
    bundle.manifest({"browser": "fake"})
    store_result({"test_name": test_name, "status": "FAILED", "duration": 0.3, "error_msg": "AssertionError", "evidence_dir": str(bundle.path)}, run_id, "NEW_TEST")

    client = TestClient(api.app)
    response = client.get("/api/evidence/{0}".format(run_id), params={"test_name": test_name})
    assert response.status_code == 200
    payload = response.json()
    assert "page.html" in payload["files"]
    assert payload["timeline"][0]["status"] == "FAILED"

    file_response = client.get(payload["file_urls"]["page.html"])
    assert file_response.status_code == 200
    assert "failure" in file_response.text

    zip_response = client.get(payload["download_url"])
    assert zip_response.status_code == 200
    assert zip_response.headers["content-type"].startswith("application/zip")
