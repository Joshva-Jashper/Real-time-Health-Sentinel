import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

import testsentry.api as api
import testsentry.cli as cli
import testsentry.collector as collector
import testsentry.coverage_analyzer as coverage_analyzer
import testsentry.email_notifier as email_notifier
import testsentry.evidence as evidence
import testsentry.flakiness_analyzer as flaky
import testsentry.plugin as plugin
import testsentry.report_generator as reports


def test_coverage_analyzer_run_and_store(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    payload = {
        "totals": {"percent_covered": 82.4},
        "files": {"src/x.py": {"summary": {"percent_covered": 80, "covered_lines": 8, "missing_lines": 2, "num_statements": 10}}},
    }
    class Result:
        returncode = 0
        stdout = "ok"
    monkeypatch.setattr(coverage_analyzer.subprocess, "run", lambda *a, **k: Result())
    Path("coverage.json").write_text(json.dumps(payload), encoding="utf-8")
    assert coverage_analyzer.run_coverage() == {"src/x.py": 80}
    assert coverage_analyzer.get_coverage_score() == 15
    coverage_analyzer.store_coverage_in_db("coverage-run")
    row = collector.get_connection().execute("SELECT filepath, pct FROM coverage_data WHERE run_id = 'coverage-run'").fetchone()
    assert row == ("src/x.py", 80.0)

    Result.returncode = 1
    assert coverage_analyzer.run_coverage() == {}
    monkeypatch.setattr(coverage_analyzer.os.path, "exists", lambda _: True)
    monkeypatch.setattr(coverage_analyzer.json, "load", lambda _: (_ for _ in ()).throw(ValueError("bad json")))
    assert coverage_analyzer.get_coverage_summary() == {"total_pct": 0.0, "files": {}}


def _insert_history(name, statuses, start=None):
    start = start or datetime(2026, 1, 1, 9)
    conn = collector.get_connection()
    for index, status in enumerate(statuses):
        conn.execute(
            "INSERT INTO test_runs (run_id,test_name,status,duration,error_msg,label,phase,timestamp) VALUES (?,?,?,?,?,?,?,?)",
            [f"flaky-{index}", name, status, 0.1, "TimeoutError: network" if status == "FAILED" else None, "STABLE", "call", start + timedelta(days=index)],
        )


def test_flakiness_analysis_trends_patterns_and_summary():
    name = "tests/test_flaky.py::test_network"
    _insert_history(name, ["PASSED"] * 5 + ["FAILED"] * 5 + ["PASSED"] * 5 + ["FAILED"] * 5)
    metrics = flaky.calculate_flakiness_per_test(name, window=30)
    assert metrics["is_flaky"] is True
    assert metrics["status_changes"] == 3
    assert metrics["trend"] == "STABLE"
    pattern = flaky.detect_time_patterns(name)
    assert "day_patterns" in pattern and pattern["worst_time"]
    errors = flaky.detect_error_patterns(name)
    assert "Timeout" in errors["likely_causes"]
    assert flaky.get_all_flaky_tests()
    summary = flaky.get_flakiness_summary()
    assert summary["total_flaky_tests"] >= 1
    assert flaky.calculate_flakiness_per_test("missing")["flakiness_rating"] == "UNKNOWN"


def test_email_send_success_and_failure(monkeypatch):
    class SMTP:
        def __init__(self, *args): self.sent = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, msg): self.sent = True
    monkeypatch.setattr(email_notifier, "EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(email_notifier, "EMAIL_PASSWORD", "pw")
    monkeypatch.setattr(email_notifier.smtplib, "SMTP_SSL", SMTP)
    assert email_notifier.send_email_notification("r1", [{"test_name": "a::b"}], [], {"total_score": 50, "grade": "F", "pass_rate": 50})
    assert not email_notifier.send_email_notification("r1", [], [], {})
    class BrokenSMTP:
        def __enter__(self): raise OSError("offline")
        def __exit__(self, *args): pass
    monkeypatch.setattr(email_notifier.smtplib, "SMTP_SSL", BrokenSMTP)
    assert not email_notifier.send_email_notification("r1", [{"test_name": "a"}], [], {})


def test_evidence_async_and_edge_helpers(tmp_path):
    bundle = evidence.create_bundle(tmp_path, "../dangerous/test", metadata={"token": "secret"})
    assert "secret" not in (bundle.path / "manifest.json").read_text()
    safe_path = bundle.add_text("../escape.txt", "bad")
    assert safe_path.parent == bundle.path
    assert not (bundle.path.parent / "escape.txt").exists()
    class AsyncLocator:
        async def evaluate_all(self, *_): raise RuntimeError("locator failed")
    class AsyncPage:
        url = "https://example.test"
        async def title(self): raise RuntimeError("title failed")
        async def content(self): raise RuntimeError("content failed")
        def locator(self, *_): return AsyncLocator()
        async def screenshot(self, **kwargs): raise RuntimeError("screenshot failed")
    result = asyncio.run(evidence.capture_playwright_async(bundle, AsyncPage(), locator="button"))
    assert (result.path / "content-error.txt").exists()
    assert (result.path / "elements-error.txt").exists()
    assert (result.path / "screenshot-error.txt").exists()
    class Obj:
        method = "POST"; url = "https://x.test/?token=secret"; status_code = 500; headers = {"Authorization": "secret"}; content = b"body"
        def json(self): raise ValueError("not json")
    evidence.capture_api_failure(bundle, request=Obj(), response={"password": "secret"})
    assert "secret" not in (bundle.path / "api.json").read_text()
    assert evidence._slug("...") == "test"
    assert evidence._read_attr(Obj(), "missing", "fallback") == "fallback"
    assert evidence._call(Obj(), "missing", "fallback") == "fallback"


def test_report_generator_writes_html(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "calculate_health_score", lambda run_id: {"total_score": 88, "grade": "A"})
    monkeypatch.setattr(reports, "get_regression_summary", lambda run_id: {"STABLE": 1})
    monkeypatch.setattr(reports, "get_at_risk_modules", lambda root: [{"filepath": "src/x.py"}])
    monkeypatch.setattr(reports, "get_ai_stats", lambda run_id: {"total_failures": 0, "api_calls": 0, "cache_hits": 0})
    output = reports.generate_report("run-report", str(tmp_path / "report.html"))
    assert Path(output).exists()
    assert "run-report" in Path(output).read_text(encoding="utf-8")


def test_cli_commands_cover_empty_and_version(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(cli.cli, ["version"]).exit_code == 0
    assert runner.invoke(cli.cli, ["scan"]).exit_code == 0
    assert runner.invoke(cli.cli, ["status"]).exit_code == 0
    assert runner.invoke(cli.cli, ["history"]).exit_code == 0
    assert runner.invoke(cli.cli, ["coverage"]).exit_code == 0
    assert runner.invoke(cli.cli, ["flaky"]).exit_code == 0
    assert runner.invoke(cli.cli, ["risk"]).exit_code == 0
    assert runner.invoke(cli.cli, ["clear"]).exit_code == 0


def test_api_all_read_endpoints_and_triage_fallback(monkeypatch):
    client = TestClient(api.app)
    headers = {"x-api-key": os.getenv("TESTSENTRY_API_KEY", "ci-test-key")}
    for path in ("/api/runs", "/api/health/latest", "/api/flaky", "/api/risk", "/api/history", "/api/triage-cache"):
        response = client.get(path, headers=headers)
        assert response.status_code in (200, 404)
    monkeypatch.setattr(api, "get_ai_stats", lambda run_id: {"total_failures": 0})
    assert client.get("/api/ai-stats/run", headers=headers).json() == {"total_failures": 0}
    monkeypatch.setattr("testsentry.ai_triage.triage_failure", lambda result: None)
    assert client.post("/api/triage-test", headers=headers, json={"test_name": "test", "error_msg": "failure"}).status_code == 503
    monkeypatch.setattr("testsentry.ai_triage.triage_failure", lambda result: {"category": "LOCATOR_FAILURE"})
    assert client.post("/api/triage-test", headers=headers, json={"test_name": "test", "error_msg": "failure"}).status_code == 200


def test_plugin_session_finish_and_report_hook(monkeypatch):
    monkeypatch.setattr(plugin, "calculate_health_score", lambda run_id: {"total_score": 80, "grade": "A", "speed_score": 1, "stability_score": 2, "flakiness_score": 3, "coverage_score": 4, "quality_score": 5, "pass_rate": 100, "flaky_count": 0})
    monkeypatch.setattr(plugin, "get_connection", lambda: SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: (1, 0))))
    monkeypatch.setattr(plugin, "store_run_metadata", lambda **kwargs: None)
    monkeypatch.setattr(plugin, "generate_report", lambda run_id: None)
    monkeypatch.setattr(plugin, "get_newly_failing_with_triage", lambda run_id: [{"owner": "dev@example.com", "test_name": "x"}])
    monkeypatch.setattr(plugin, "get_fixed_tests", lambda run_id: [{"test_name": "fixed"}])
    monkeypatch.setattr(plugin, "send_email_notification", lambda **kwargs: True)
    monkeypatch.setattr(plugin.langfuse, "flush", lambda: None)
    plugin.pytest_sessionfinish(SimpleNamespace(testscollected=2), 0)

    class Report:
        when = "call"; skipped = False; failed = True; duration = 0.1; longrepr = "boom"
    class Outcome:
        def get_result(self): return Report()
    monkeypatch.setattr(plugin, "label_test", lambda result, run_id: "NEW_TEST")
    monkeypatch.setattr(plugin, "store_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(plugin, "triage_failure", lambda result: None)
    hook = plugin.pytest_runtest_makereport(SimpleNamespace(nodeid="test_x"), SimpleNamespace())
    next(hook)
    with pytest.raises(StopIteration): hook.send(Outcome())
