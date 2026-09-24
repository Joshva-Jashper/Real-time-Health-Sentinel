import json
from types import SimpleNamespace

import testsentry.ai_triage as ai


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.models = []
        self.requests = []

    def create(self, *, model, **kwargs):
        self.models.append(model)
        self.requests.append(kwargs)
        payload = next(self.responses)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _result(**overrides):
    value = {
        "run_id": "run-1",
        "test_name": "tests/login.spec.py::test_login",
        "error_msg": "Timeout while locating button token=private-token",
    }
    value.update(overrides)
    return value


def _triage(category="ENV_ISSUE", confidence=92):
    return {
        "category": category,
        "confidence_pct": confidence,
        "why_it_failed": "The browser locator timed out.",
        "suggested_fix": "Review the locator and wait condition in test code.",
        "affected_module": "tests/login.spec.py",
    }


def test_triage_skips_empty_error():
    assert ai.triage_failure({"error_msg": "", "test_name": "test_something"}) is None


def test_triage_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(ai, "TRIAGE_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai.triage_failure({"error_msg": "AssertionError", "test_name": "test_something"}) is None


def test_gpt_mini_handles_confident_failure_without_escalation(monkeypatch):
    monkeypatch.setattr(ai, "TRIAGE_BACKEND", "openai")
    client = FakeClient([_triage()])
    monkeypatch.setattr(ai, "cache_lookup", lambda _: None)
    monkeypatch.setattr(ai, "cache_store", lambda *_: None)
    monkeypatch.setattr(ai, "store_triage_event", lambda *args: None)

    result = ai.triage_with_gpt(_result(), client=client)

    assert result["model_used"] == "gpt-5-mini"
    assert result["cache_hit"] is False
    assert client.chat.completions.models == ["gpt-5-mini"]


def test_uncertain_real_bug_escalates_to_gpt5(monkeypatch):
    monkeypatch.setattr(ai, "TRIAGE_BACKEND", "openai")
    client = FakeClient([_triage("REAL_BUG", 65), _triage("REAL_BUG", 96)])
    monkeypatch.setattr(ai, "cache_lookup", lambda _: None)
    monkeypatch.setattr(ai, "cache_store", lambda *_: None)
    monkeypatch.setattr(ai, "store_triage_event", lambda *args: None)

    result = ai.triage_with_gpt(_result(), client=client)

    assert result["model_used"] == "gpt-5"
    assert result["category"] == "REAL_BUG"
    assert client.chat.completions.models == ["gpt-5-mini", "gpt-5"]


def test_analysis_context_redacts_evidence_files(tmp_path):
    (tmp_path / "page.html").write_text(
        "<input name='password' value='do-not-store'>", encoding="utf-8"
    )
    (tmp_path / "browser.json").write_text(
        '{"url": "https://example.test/?token=private-token"}', encoding="utf-8"
    )

    context = ai.build_analysis_context(_result(evidence_dir=str(tmp_path)))

    assert "do-not-store" not in context
    assert "private-token" not in context
    assert "[REDACTED]" in context


def test_cached_result_does_not_call_gpt(monkeypatch):
    cached = _triage()
    monkeypatch.setattr(ai, "cache_lookup", lambda _: cached)
    monkeypatch.setattr(ai, "store_triage_event", lambda *args: None)

    result = ai.triage_with_gpt(_result(), client=FakeClient([]))

    assert result["cache_hit"] is True
    assert result["model_used"] == "cache"


def test_ollama_backend_uses_local_model_and_json_mode(monkeypatch):
    client = FakeClient([_triage("LOCATOR_FAILURE", 94)])
    monkeypatch.setattr(ai, "TRIAGE_BACKEND", "ollama")
    monkeypatch.setattr(ai, "OLLAMA_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setattr(ai, "cache_lookup", lambda _: None)
    monkeypatch.setattr(ai, "cache_store", lambda *_: None)
    monkeypatch.setattr(ai, "store_triage_event", lambda *args: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = ai.triage_with_gpt(_result(), client=client)

    assert result["model_used"] == "ollama:qwen2.5-coder:7b"
    assert client.chat.completions.models == ["qwen2.5-coder:7b"]
    assert client.chat.completions.requests[0]["max_tokens"] == 700
    assert client.chat.completions.requests[0]["response_format"] == {"type": "json_object"}
    assert "extra_body" not in client.chat.completions.requests[0]
