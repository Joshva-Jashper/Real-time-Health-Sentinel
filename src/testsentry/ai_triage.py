"""Tiered GPT analysis for test failures.

The analyzer uses GPT-5 mini for the normal path and escalates ambiguous or
potentially real application bugs to GPT-5. Browser/API evidence is included
when available, after the same redaction used by the evidence collector.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv
from langfuse import get_client
from pydantic import BaseModel, Field, field_validator

from testsentry.collector import cache_lookup, cache_store, store_triage_event
from testsentry.evidence import redact_text
from testsentry.fingerprinter import fingerprint

load_dotenv()
langfuse = get_client()

GPT_MINI_MODEL = "gpt-5-mini"
GPT_ESCALATION_MODEL = "gpt-5"
_MAX_EVIDENCE_CHARS = 12_000
_ESCALATION_CONFIDENCE = 80


class FailureCategory(str, Enum):
    LOCATOR_FAILURE = "LOCATOR_FAILURE"
    WAIT_OR_TIMING_FAILURE = "WAIT_OR_TIMING_FAILURE"
    API_CONTRACT_FAILURE = "API_CONTRACT_FAILURE"
    TEST_CODE_FAILURE = "TEST_CODE_FAILURE"
    APPLICATION_BUG = "APPLICATION_BUG"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    UNKNOWN = "UNKNOWN"
    # Legacy values remain accepted for cached results and backwards compatibility.
    REAL_BUG = "REAL_BUG"
    FLAKY = "FLAKY"
    ENV_ISSUE = "ENV_ISSUE"
    DATA_ISSUE = "DATA_ISSUE"


class TriageResult(BaseModel):
    category: FailureCategory
    confidence_pct: int = Field(ge=0, le=100)
    why_it_failed: str
    suggested_fix: str
    affected_module: str

    @field_validator("confidence_pct", mode="before")
    @classmethod
    def parse_confidence(cls, value: Any) -> int:
        return max(0, min(100, int(value)))


_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": [item.value for item in FailureCategory],
        },
        "confidence_pct": {"type": "integer", "minimum": 0, "maximum": 100},
        "why_it_failed": {"type": "string"},
        "suggested_fix": {"type": "string"},
        "affected_module": {"type": "string"},
    },
    "required": [
        "category",
        "confidence_pct",
        "why_it_failed",
        "suggested_fix",
        "affected_module",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You are TestSentry's senior QA failure analyst.
Classify the failure using exactly one category:
- LOCATOR_FAILURE: a selector or locator no longer identifies the intended UI element.
- WAIT_OR_TIMING_FAILURE: synchronization, timeout, race, or ordering problem.
- API_CONTRACT_FAILURE: the service response/status/schema violates the expected contract.
- TEST_CODE_FAILURE: the test itself is incorrect, including assertion/setup mistakes.
- APPLICATION_BUG: application or service behavior is incorrect.
- AUTHENTICATION_FAILURE: login, permissions, credentials, or security behavior failed.
- ENVIRONMENT_FAILURE: browser, driver, network, CI, dependency, or infrastructure problem.
- FLAKY: nondeterministic timing, ordering, race, or intermittent test behavior.
- DATA_ISSUE: invalid, missing, stale, or conflicting test data/configuration.
- UNKNOWN: evidence is insufficient.
- REAL_BUG and ENV_ISSUE are legacy aliases; prefer the specific categories above.

Use DOM and API evidence when present. A missing locator is not automatically a
real bug: distinguish a changed UI contract from a genuinely broken behavior.
Suggest changes to test code, selectors, waits, fixtures, or environment only
when justified. Never propose an automatic correction for APPLICATION_BUG,
REAL_BUG, API_CONTRACT_FAILURE, AUTHENTICATION_FAILURE, ENVIRONMENT_FAILURE,
ENV_ISSUE, DATA_ISSUE, or UNKNOWN. These failures must remain CI failures.
Return only the requested JSON object."""


def parse_triage_response(content: str | Mapping[str, Any]) -> dict[str, Any]:
    """Parse, validate, and bound a model response."""
    if isinstance(content, Mapping):
        data = dict(content)
    else:
        text = str(content).strip()
        if text.startswith("```"):
            parts = text.split("```", 2)
            text = parts[1] if len(parts) > 1 else text
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]
        data = json.loads(text.strip())

    categories = {item.value for item in FailureCategory}
    if data.get("category") not in categories:
        raise ValueError("invalid triage category")
    data["confidence_pct"] = max(0, min(100, int(data.get("confidence_pct", 0))))
    for key in ("why_it_failed", "suggested_fix", "affected_module"):
        data[key] = str(data.get(key, ""))
    return TriageResult.model_validate(data).model_dump(mode="json")


def build_analysis_context(result: Mapping[str, Any]) -> str:
    """Build a bounded, sanitized prompt context from a test result/evidence."""
    sections = [
        f"Test: {result.get('test_name', '')}",
        f"Error: {redact_text(str(result.get('error_msg', '')))}",
    ]
    for key in ("framework", "locator", "run_id", "affected_module"):
        if result.get(key) is not None:
            sections.append(f"{key}: {redact_text(str(result[key]))}")

    evidence = result.get("evidence")
    evidence_dir = result.get("evidence_dir")
    if evidence is None and evidence_dir:
        evidence = evidence_dir
    if isinstance(evidence, Mapping):
        sections.append("Evidence metadata:\n" + redact_text(json.dumps(evidence, default=str)))
    elif evidence:
        directory = Path(str(evidence))
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.suffix.lower() not in {".txt", ".json", ".html"} or not path.is_file():
                    continue
                try:
                    content = redact_text(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                sections.append(f"Evidence file {path.name}:\n{content[:4000]}")

    return "\n\n".join(sections)[:_MAX_EVIDENCE_CHARS]


def _client():
    """Create the OpenAI-compatible client lazily so offline test runs work."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from openai import OpenAI

    return OpenAI()


def _call_model(client: Any, model: str, context: str, review: dict[str, Any] | None = None) -> dict[str, Any]:
    user_prompt = context
    if review:
        user_prompt += "\n\nPreliminary GPT-5 mini result to review:\n" + json.dumps(review)
        user_prompt += "\nRe-evaluate it carefully; preserve it only if the evidence supports it."

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=700,
        extra_body={"reasoning": {"effort": "minimal" if model == GPT_MINI_MODEL else "medium"}},
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "testsentry_triage",
                "strict": True,
                "schema": _TRIAGE_SCHEMA,
            },
        },
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError(f"{model} returned an empty response")
    return parse_triage_response(content)


def _should_escalate(triage: Mapping[str, Any]) -> bool:
    return (
        int(triage.get("confidence_pct", 0)) < _ESCALATION_CONFIDENCE
        or triage.get("category") in {
            FailureCategory.APPLICATION_BUG.value,
            FailureCategory.API_CONTRACT_FAILURE.value,
            FailureCategory.AUTHENTICATION_FAILURE.value,
            FailureCategory.REAL_BUG.value,
        }
    )


def automatic_repair_allowed(triage: Mapping[str, Any]) -> bool:
    """Allow candidate repair only for narrowly scoped test-side failures."""
    from testsentry.repair import repair_allowed
    return repair_allowed(str(triage.get("category", "UNKNOWN")))


def triage_with_gpt(result: Mapping[str, Any], *, client: Any = None) -> dict[str, Any] | None:
    """Analyze a failure with GPT-5 mini, escalating uncertain results to GPT-5."""
    error_msg = str(result.get("error_msg", ""))
    if not error_msg:
        return None

    fp = fingerprint(error_msg)
    cached = cache_lookup(fp)
    if cached:
        cached["cache_hit"] = True
        cached["model_used"] = "cache"
        store_triage_event(result.get("run_id"), fp, "openai", True)
        return cached

    client = client or _client()
    if client is None:
        print("[TestSentry] OPENAI_API_KEY is not set; skipping GPT triage.")
        return None

    context = build_analysis_context(result)
    try:
        mini = _call_model(client, GPT_MINI_MODEL, context)
        selected = mini
        model_used = GPT_MINI_MODEL
        if _should_escalate(mini):
            try:
                selected = _call_model(client, GPT_ESCALATION_MODEL, context, review=mini)
                model_used = GPT_ESCALATION_MODEL
            except Exception as exc:
                print(f"[TestSentry] GPT-5 escalation failed; keeping mini result: {exc}")
        selected["cache_hit"] = False
        selected["model_used"] = model_used
        cache_store(fp, selected)
        store_triage_event(result.get("run_id"), fp, "openai", False)
        return selected
    except Exception as exc:
        print(f"[TestSentry] GPT triage failed: {exc}")
        return None


def triage_failure(result: dict) -> dict | None:
    """Main AI entry point used by the API and pytest plugin."""
    return triage_with_gpt(result)


# Compatibility alias for callers that used the provider-specific name.
def triage_with_openai(result: Mapping[str, Any]) -> dict[str, Any] | None:
    return triage_with_gpt(result)


__all__ = [
    "FailureCategory",
    "TriageResult",
    "build_analysis_context",
    "parse_triage_response",
    "triage_failure",
    "triage_with_gpt",
    "triage_with_openai",
    "automatic_repair_allowed",
]


if __name__ == "__main__":
    print("TestSentry GPT triage module loaded")
