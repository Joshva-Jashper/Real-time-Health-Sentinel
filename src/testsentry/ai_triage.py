import os
import time
import json
import requests
from enum import Enum
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator
import instructor
from groq import Groq
from langfuse import get_client

from testsentry.fingerprinter import fingerprint
from testsentry.collector import cache_lookup, cache_store

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Langfuse v4 client
langfuse = get_client()

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "testsentry-model"


class FailureCategory(str, Enum):
    REAL_BUG   = "REAL_BUG"
    FLAKY      = "FLAKY"
    ENV_ISSUE  = "ENV_ISSUE"
    DATA_ISSUE = "DATA_ISSUE"


class TriageResult(BaseModel):
    category:        FailureCategory
    confidence_pct:  int
    why_it_failed:   str
    suggested_fix:   str
    affected_module: str

    @field_validator("confidence_pct", mode="before")
    @classmethod
    def parse_confidence(cls, v):
        """Accept both int and string for confidence_pct."""
        return int(v)


def get_groq_client():
    """Create Instructor-wrapped Groq client."""
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return instructor.from_groq(groq_client)


def is_ollama_running() -> bool:
    """Check if Ollama is running locally."""
    try:
        response = requests.get(OLLAMA_URL, timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def triage_with_ollama(result: dict) -> dict:
    """
    Use local fine-tuned model via Ollama.
    Zero API cost — runs completely offline.
    """
    error_msg = result.get("error_msg", "")
    test_name = result.get("test_name", "")

    if not error_msg:
        return None

    # Check cache first
    fp = fingerprint(error_msg)
    cached = cache_lookup(fp)
    if cached:
        print(f"\n[TestSentry] 💾 CACHE HIT — {test_name}")
        print(f"             Category: {cached['category']}")
        return cached

    try:
        print(f"\n[TestSentry] 🤖 LOCAL MODEL — {test_name}")

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"""Analyze this pytest failure and return ONLY valid JSON.

Test: {test_name}
Error: {error_msg}

Return exactly this JSON structure:
{{"category": "REAL_BUG or FLAKY or ENV_ISSUE or DATA_ISSUE",
"confidence_pct": 90,
"why_it_failed": "plain English explanation",
"suggested_fix": "exact fix to apply",
"affected_module": "filename.py"}}""",
                "stream": False
            },
            timeout=60
        )

        content = response.json()["response"]

        # Extract JSON from response
        start = content.find("{")
        end = content.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON found in response")

        triage_dict = json.loads(content[start:end])
        triage_dict["cache_hit"] = False

        # Validate category
        valid_categories = ["REAL_BUG", "FLAKY", "ENV_ISSUE", "DATA_ISSUE"]
        if triage_dict.get("category") not in valid_categories:
            triage_dict["category"] = "REAL_BUG"

        # Ensure confidence_pct is int
        triage_dict["confidence_pct"] = int(triage_dict.get("confidence_pct", 85))

        cache_store(fp, triage_dict)

        print(f"             Category:   {triage_dict['category']}")
        print(f"             Confidence: {triage_dict['confidence_pct']}%")
        print(f"             Why:        {triage_dict['why_it_failed']}")
        print(f"             Fix:        {triage_dict['suggested_fix']}")

        return triage_dict

    except Exception as e:
        print(f"\n[TestSentry] ⚠️ Local model error: {e}")
        print(f"             Falling back to Groq API")
        return triage_with_groq(result)


def triage_with_groq(result: dict) -> dict:
    """
    Use Groq API for triage.
    Fallback when Ollama is not running.
    """
    error_msg = result.get("error_msg", "")
    test_name = result.get("test_name", "")

    if not os.getenv("GROQ_API_KEY"):
        print("\n[TestSentry] ⚠️ GROQ_API_KEY not set. Skipping AI triage.")
        return None

    if not error_msg:
        return None

    fp = fingerprint(error_msg)
    cached = cache_lookup(fp)
    if cached:
        print(f"\n[TestSentry] 💾 CACHE HIT — {test_name}")
        print(f"             Category: {cached['category']}")

        try:
            with langfuse.start_as_current_observation(
                as_type="span",
                name="triage-cache-hit",
                input={"test_name": test_name, "fingerprint": fp},
            ) as span:
                span.update(
                    output={"category": cached["category"]},
                    metadata={"cache_hit": True, "api_cost": 0.0}
                )
            langfuse.flush()
        except Exception as e:
            print(f"[TestSentry] ⚠️ Langfuse error: {e}")

        return cached

    print(f"\n[TestSentry] 🤖 GROQ API — {test_name}")

    try:
        client = get_groq_client()
        start_time = time.time()

        triage = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            response_model=TriageResult,
            messages=[
                {
                    "role": "system",
                    "content": """You are a senior QA engineer analyzing pytest failures.
                    Categorize each failure into exactly one of:
                    - REAL_BUG: actual code defect
                    - FLAKY: non-deterministic, passes sometimes
                    - ENV_ISSUE: environment/infrastructure problem
                    - DATA_ISSUE: test data missing or wrong
                    Always provide a clear explanation and actionable fix."""
                },
                {
                    "role": "user",
                    "content": f"""Analyze this pytest failure:

Test name: {test_name}
Error message: {error_msg}

Return a structured triage with category, confidence as a plain integer
(not a string, e.g. 92 not "92"), why it failed, and suggested fix."""
                }
            ]
        )

        latency_ms = round((time.time() - start_time) * 1000, 2)

        try:
            category_value = triage.category.value if isinstance(triage.category, Enum) else str(triage.category)
        except Exception:
            category_value = str(triage.category)

        triage_dict = {
            "category":        category_value,
            "confidence_pct":  int(triage.confidence_pct),
            "why_it_failed":   triage.why_it_failed,
            "suggested_fix":   triage.suggested_fix,
            "affected_module": triage.affected_module,
            "cache_hit":       False
        }

        cache_store(fp, triage_dict)

        try:
            with langfuse.start_as_current_observation(
                as_type="generation",
                name="triage-api-call",
                model="llama-3.3-70b-versatile",
                input={"test_name": test_name, "error_msg": error_msg[:200]},
            ) as span:
                span.update(
                    output=triage_dict,
                    metadata={
                        "cache_hit": False,
                        "latency_ms": latency_ms,
                    }
                )
            langfuse.flush()
        except Exception as e:
            print(f"[TestSentry] ⚠️ Langfuse error: {e}")

        print(f"             Category:   {triage_dict['category']}")
        print(f"             Confidence: {triage_dict['confidence_pct']}%")
        print(f"             Why:        {triage_dict['why_it_failed']}")
        print(f"             Fix:        {triage_dict['suggested_fix']}")

        return triage_dict

    except Exception as e:
        print(f"\n[TestSentry] ⚠️ Triage error: {type(e).__name__}: {str(e)}")
        print(f"             Skipping AI analysis for this failure")
        return None


def triage_failure(result: dict) -> dict:
    """
    Main entry point. Auto-selects best available backend.

    Priority:
    1. Local Ollama model (testsentry-model) — zero cost, offline
    2. Groq API — free tier, requires API key
    3. Skip — no backend available
    """
    # Try local model first
    if is_ollama_running():
        print(f"[TestSentry] 🏠 Using local fine-tuned model")
        return triage_with_ollama(result)

    # Fall back to Groq
    if os.getenv("GROQ_API_KEY"):
        print(f"[TestSentry] ☁️  Ollama not running — using Groq API")
        return triage_with_groq(result)

    # No backend available
    print("\n[TestSentry] ⚠️ No AI backend available.")
    print("             Start Ollama: ollama serve")
    print("             Or set GROQ_API_KEY in .env")
    return None