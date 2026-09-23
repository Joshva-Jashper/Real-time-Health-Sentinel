import json
from pathlib import Path

from testsentry.evidence import (
    capture_api_failure,
    capture_failure,
    capture_playwright,
    capture_selenium,
    redact_text,
)


class FakeSelenium:
    current_url = "https://example.test/account?token=secret-token"
    title = "Account"
    page_source = "<html><body><button data-testid='save'>Save</button></body></html>"

    def execute_script(self, script):
        return [{"tag": "BUTTON", "testid": "save", "visible": True}]

    def save_screenshot(self, path):
        Path(path).write_bytes(b"png")
        return True


class FakeLocator:
    def evaluate_all(self, script):
        return [{"tag": "BUTTON", "testid": "save", "visible": True}]


class FakePlaywright:
    url = "https://example.test/account?access_token=secret-token"

    def title(self):
        return "Account"

    def content(self):
        return "<html><body><button data-testid='save'>Save</button></body></html>"

    def locator(self, selector):
        return FakeLocator()

    def screenshot(self, path, full_page=True):
        Path(path).write_bytes(b"png")
        return b"png"


def test_redact_text_hides_common_secrets():
    redacted = redact_text(
        "password=secret password: other token=abc https://x.test?a=1&api_key=hidden"
    )
    assert "secret" not in redacted
    assert "other" not in redacted
    assert "abc" not in redacted
    assert "hidden" not in redacted
    assert "[REDACTED]" in redacted


def test_generic_failure_bundle_is_sanitized(tmp_path):
    bundle = capture_failure(
        tmp_path,
        "tests/login.py::test_login",
        "Assertion failed token=abc123",
        metadata={"authorization": "Bearer secret"},
    )
    assert (bundle.path / "error.txt").read_text(encoding="utf-8").find("abc123") == -1
    manifest = json.loads((bundle.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["authorization"] == "[REDACTED]"


def test_selenium_capture_writes_dom_elements_and_screenshot(tmp_path):
    bundle = capture_failure(tmp_path, "test_selenium", "locator failure")
    capture_selenium(bundle, FakeSelenium(), locator="button#save")
    assert (bundle.path / "page.html").exists()
    assert (bundle.path / "elements.json").exists()
    assert (bundle.path / "screenshot.png").read_bytes() == b"png"
    browser = json.loads((bundle.path / "browser.json").read_text(encoding="utf-8"))
    assert browser["url"] == "https://example.test/account?token=%5BREDACTED%5D"


def test_playwright_capture_writes_dom_elements_and_screenshot(tmp_path):
    bundle = capture_failure(tmp_path, "test_playwright", "locator failure")
    capture_playwright(bundle, FakePlaywright(), locator="[data-testid=save]")
    assert (bundle.path / "page.html").exists()
    assert (bundle.path / "elements.json").exists()
    assert (bundle.path / "screenshot.png").read_bytes() == b"png"


def test_api_capture_redacts_headers_and_body(tmp_path):
    bundle = capture_failure(tmp_path, "test_api", "API failure")
    capture_api_failure(
        bundle,
        request={"method": "POST", "headers": {"Authorization": "Bearer secret"}, "body": {"password": "hidden"}},
        response={"status_code": 500, "body": {"error": "database unavailable"}},
    )
    payload = json.loads((bundle.path / "api.json").read_text(encoding="utf-8"))
    assert payload["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert payload["request"]["body"]["password"] == "[REDACTED]"
    assert payload["response"]["status_code"] == 500
