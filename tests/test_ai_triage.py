from testsentry.ai_triage import triage_failure
import os


def test_triage_skips_empty_error():
    """Should return None for empty error message."""
    result = triage_failure({
        "error_msg": "",
        "test_name": "tests/test_sample.py::test_something"
    })
    assert result is None


def test_triage_returns_none_without_key(monkeypatch):
    """Should return None when no backend available."""
    import testsentry.ai_triage as ai
    from unittest.mock import patch

    # Mock both Ollama and Groq as unavailable
    with patch("testsentry.ai_triage.is_ollama_running", return_value=False):
        original_key = os.getenv("GROQ_API_KEY", "")
        ai_module_key = ai.GROQ_API_KEY
        ai.GROQ_API_KEY = ""

        import os as _os
        original_env = _os.environ.get("GROQ_API_KEY", "")
        _os.environ["GROQ_API_KEY"] = ""

        result = triage_failure({
            "error_msg": "AssertionError: assert 1 == 2",
            "test_name": "tests/test_sample.py::test_something"
        })

        ai.GROQ_API_KEY = ai_module_key
        _os.environ["GROQ_API_KEY"] = original_env

    assert result is None