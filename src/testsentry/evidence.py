"""Failure evidence capture for browser and API test integrations.

The module deliberately uses duck typing instead of importing Selenium or
Playwright, so TestSentry remains installable for projects that only use
pytest or API tests. Integrations call the adapter that matches their driver.
Sensitive values are redacted before evidence is written to disk or sent to an
AI backend.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|"
    r"set-cookie|access[_-]?token|refresh[_-]?token|client[_-]?secret)",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(\b(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|"
    r"set-cookie|access[_-]?token|refresh[_-]?token|client[_-]?secret)\b"
    r"\s*[:=]\s*)([^,;\s}\]]+)",
    re.IGNORECASE,
)


@dataclass
class EvidenceBundle:
    """A directory containing one sanitized failure's evidence files."""

    path: Path
    test_name: str
    files: dict[str, str] = field(default_factory=dict)

    def add_text(self, name: str, content: str) -> Path:
        target = _safe_child(self.path, name)
        target.write_text(redact_text(content), encoding="utf-8")
        self.files[name] = str(target)
        return target

    def add_json(self, name: str, value: Any) -> Path:
        target = _safe_child(self.path, name)
        target.write_text(
            json.dumps(redact_value(value), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        self.files[name] = str(target)
        return target

    def add_bytes(self, name: str, value: bytes) -> Path:
        target = _safe_child(self.path, name)
        target.write_bytes(value)
        self.files[name] = str(target)
        return target

    def manifest(self, metadata: Mapping[str, Any] | None = None) -> Path:
        payload = {
            "test_name": self.test_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": self.files,
            "metadata": redact_value(dict(metadata or {})),
        }
        return self.add_json("manifest.json", payload)


def create_bundle(root_dir: str | Path, test_name: str, *, metadata: Mapping[str, Any] | None = None) -> EvidenceBundle:
    """Create a unique evidence directory for one test failure."""
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    directory = root / f"{_slug(test_name)}-{uuid.uuid4().hex[:10]}"
    directory.mkdir()
    bundle = EvidenceBundle(directory, test_name)
    bundle.manifest(metadata)
    return bundle


def redact_value(value: Any) -> Any:
    """Recursively redact secrets in mappings, lists, and scalar values."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    """Redact common secret assignments and sensitive URL query values."""
    text = _SENSITIVE_ASSIGNMENT.sub(r"\1[REDACTED]", str(value))
    if "?" in text:
        try:
            parts = urlsplit(text)
            query = []
            for key, item in parse_qsl(parts.query, keep_blank_values=True):
                query.append((key, "[REDACTED]" if _SENSITIVE_KEY.search(key) else item))
            text = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        except ValueError:
            pass
    return text


def capture_failure(
    root_dir: str | Path,
    test_name: str,
    error: BaseException | str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceBundle:
    """Create a generic evidence bundle when no browser object is available."""
    bundle = create_bundle(root_dir, test_name, metadata=metadata)
    bundle.add_text("error.txt", str(error))
    bundle.manifest(metadata)
    return bundle


def capture_selenium(
    bundle: EvidenceBundle,
    driver: Any,
    *,
    locator: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceBundle:
    """Capture evidence from a Selenium-compatible WebDriver instance."""
    page_metadata: dict[str, Any] = dict(metadata or {})
    page_metadata.update(
        {
            "framework": "selenium",
            "url": _read_attr(driver, "current_url"),
            "title": _read_attr(driver, "title"),
            "locator": locator,
        }
    )
    bundle.add_json("browser.json", page_metadata)

    source = _call(driver, "page_source", default="")
    if source:
        bundle.add_text("page.html", str(source))

    try:
        elements = driver.execute_script(
            """
            return Array.from(document.querySelectorAll(
              'button,input,textarea,select,a,[role],[data-testid]'
            )).map(el => ({
              tag: el.tagName,
              text: (el.innerText || '').trim().slice(0, 300),
              role: el.getAttribute('role'),
              id: el.id,
              name: el.getAttribute('name'),
              testid: el.getAttribute('data-testid'),
              ariaLabel: el.getAttribute('aria-label'),
              visible: !!(el.offsetWidth || el.offsetHeight),
              disabled: el.disabled === true
            }));
            """
        )
        bundle.add_json("elements.json", elements)
    except Exception as exc:
        bundle.add_text("elements-error.txt", str(exc))

    _save_screenshot(bundle, driver, "screenshot.png")
    bundle.manifest(page_metadata)
    return bundle


def capture_playwright(
    bundle: EvidenceBundle,
    page: Any,
    *,
    locator: Any = None,
    trace_path: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceBundle:
    """Capture evidence from a synchronous Playwright-compatible Page."""
    page_metadata: dict[str, Any] = dict(metadata or {})
    page_metadata.update(
        {
            "framework": "playwright",
            "url": _read_attr(page, "url"),
            "title": _call(page, "title", default=""),
            "locator": locator,
        }
    )
    bundle.add_json("browser.json", page_metadata)

    content = _call(page, "content", default="")
    if content:
        bundle.add_text("page.html", str(content))

    try:
        elements = page.locator(
            "button,input,textarea,select,a,[role],[data-testid]"
        ).evaluate_all(
            """
            els => els.map(el => ({
              tag: el.tagName,
              text: (el.innerText || '').trim().slice(0, 300),
              role: el.getAttribute('role'),
              id: el.id,
              name: el.getAttribute('name'),
              testid: el.getAttribute('data-testid'),
              ariaLabel: el.getAttribute('aria-label'),
              visible: !!(el.offsetWidth || el.offsetHeight),
              disabled: el.disabled === true
            }))
            """
        )
        bundle.add_json("elements.json", elements)
    except Exception as exc:
        bundle.add_text("elements-error.txt", str(exc))

    _save_screenshot(bundle, page, "screenshot.png")
    if trace_path:
        trace = Path(trace_path)
        if trace.is_file():
            target = bundle.path / "trace.zip"
            shutil.copy2(trace, target)
            bundle.files["trace.zip"] = str(target)
    bundle.manifest(page_metadata)
    return bundle


async def capture_playwright_async(
    bundle: EvidenceBundle,
    page: Any,
    *,
    locator: Any = None,
    trace_path: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceBundle:
    """Capture evidence from an asynchronous Playwright Page."""
    page_metadata: dict[str, Any] = dict(metadata or {})
    page_metadata.update({"framework": "playwright", "url": _read_attr(page, "url"), "locator": locator})
    try:
        page_metadata["title"] = await page.title()
    except Exception:
        page_metadata["title"] = ""
    bundle.add_json("browser.json", page_metadata)

    try:
        bundle.add_text("page.html", await page.content())
    except Exception as exc:
        bundle.add_text("content-error.txt", str(exc))
    try:
        elements = await page.locator(
            "button,input,textarea,select,a,[role],[data-testid]"
        ).evaluate_all(
            "els => els.map(el => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 300), role: el.getAttribute('role'), id: el.id, name: el.getAttribute('name'), testid: el.getAttribute('data-testid'), ariaLabel: el.getAttribute('aria-label'), visible: !!(el.offsetWidth || el.offsetHeight), disabled: el.disabled === true}))"
        )
        bundle.add_json("elements.json", elements)
    except Exception as exc:
        bundle.add_text("elements-error.txt", str(exc))
    try:
        await page.screenshot(path=str(bundle.path / "screenshot.png"), full_page=True)
        bundle.files["screenshot.png"] = str(bundle.path / "screenshot.png")
    except Exception as exc:
        bundle.add_text("screenshot-error.txt", str(exc))
    if trace_path and Path(trace_path).is_file():
        target = bundle.path / "trace.zip"
        shutil.copy2(trace_path, target)
        bundle.files["trace.zip"] = str(target)
    bundle.manifest(page_metadata)
    return bundle


def capture_api_failure(
    bundle: EvidenceBundle,
    *,
    request: Any = None,
    response: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceBundle:
    """Capture sanitized request/response evidence from requests/httpx-like objects."""
    payload: dict[str, Any] = dict(metadata or {})
    if request is not None:
        payload["request"] = _http_object(request)
    if response is not None:
        payload["response"] = _http_object(response)
    bundle.add_json("api.json", payload)
    bundle.manifest(payload)
    return bundle


def _http_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    result: dict[str, Any] = {}
    for attr in ("method", "url", "status_code", "reason", "text"):
        item = getattr(value, attr, None)
        if item is not None:
            result[attr] = item() if callable(item) else item
    headers = getattr(value, "headers", None)
    if headers is not None:
        result["headers"] = dict(headers)
    body = getattr(value, "json", None)
    if callable(body):
        try:
            result["body"] = body()
        except Exception:
            pass
    if "body" not in result:
        raw = getattr(value, "content", None)
        if raw is not None:
            result["body"] = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    return result


def _save_screenshot(bundle: EvidenceBundle, object_: Any, filename: str) -> None:
    try:
        target = bundle.path / filename
        result = object_.save_screenshot(str(target)) if hasattr(object_, "save_screenshot") else object_.screenshot(path=str(target), full_page=True)
        if isinstance(result, bytes):
            target.write_bytes(result)
        bundle.files[filename] = str(target)
    except Exception as exc:
        bundle.add_text("screenshot-error.txt", str(exc))


def _read_attr(object_: Any, name: str, default: Any = "") -> Any:
    try:
        value = getattr(object_, name, default)
        return value() if callable(value) else value
    except Exception:
        return default


def _call(object_: Any, name: str, default: Any = "") -> Any:
    try:
        value = getattr(object_, name)
        return value() if callable(value) else value
    except Exception:
        return default


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return (slug or "test")[:100]


def _safe_child(directory: Path, name: str) -> Path:
    target = directory / Path(name).name
    if target.parent != directory:
        raise ValueError("Evidence filename must not contain a directory")
    return target
