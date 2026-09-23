import json
from pathlib import Path

from fastapi.testclient import TestClient

import testsentry.ai_triage as ai
from testsentry.api import app
from testsentry.repair import validate_candidate_patch, validate_patch_scope


def test_specific_categories_are_repair_gated():
    assert ai.automatic_repair_allowed({"category": "LOCATOR_FAILURE"})
    assert ai.automatic_repair_allowed({"category": "WAIT_OR_TIMING_FAILURE"})
    assert ai.automatic_repair_allowed({"category": "TEST_CODE_FAILURE"})
    for category in ("APPLICATION_BUG", "API_CONTRACT_FAILURE", "AUTHENTICATION_FAILURE", "ENVIRONMENT_FAILURE", "UNKNOWN"):
        assert not ai.automatic_repair_allowed({"category": category})


def test_patch_scope_rejects_application_changes():
    patch = """diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"""
    ok, reason, paths = validate_patch_scope(patch, "LOCATOR_FAILURE")
    assert not ok
    assert "non-test" in reason
    assert paths == ["src/app.py"]


def test_candidate_patch_passes_in_isolated_copy(tmp_path):
    (tmp_path / ".git").mkdir()
    # A real git repository is required because git apply validates the patch.
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    test_file = tmp_path / "tests"
    test_file.mkdir()
    target = test_file / "test_sample.py"
    target.write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    patch = """diff --git a/tests/test_sample.py b/tests/test_sample.py\nindex 0000000..1111111 100644\n--- a/tests/test_sample.py\n+++ b/tests/test_sample.py\n@@ -1,2 +1,2 @@\n def test_value():\n-    assert 1 == 1\n+    assert 1 == 1  # validated candidate\n"""
    result = validate_candidate_patch(tmp_path, patch, "TEST_CODE_FAILURE", "tests/test_sample.py")
    assert result.accepted
    assert not (target.read_text(encoding="utf-8").endswith("validated candidate\n"))


def test_api_key_guard_and_cors(monkeypatch):
    monkeypatch.setenv("TESTSENTRY_API_KEY", "secret")
    client = TestClient(app)
    response = client.get("/api/history")
    assert response.status_code == 401
    response = client.options("/api/history", headers={"Origin": "http://localhost:8088", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-api-key"})
    assert response.status_code == 200
    assert "x-api-key" in response.headers.get("access-control-allow-headers", "").lower()
    monkeypatch.delenv("TESTSENTRY_API_KEY", raising=False)
