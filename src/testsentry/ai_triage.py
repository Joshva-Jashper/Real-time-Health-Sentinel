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
from testsentry.collector import cache_lookup, cache_store, store_triage_event

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Langfuse v4 client
langfuse = get_client()

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "testsentry-model:latest"  # custom fine-tuned llama3.2 model


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


def get_installed_ollama_model() -> str:
    """Return an available installed Ollama model if primary target is missing."""
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        if res.status_code == 200:
            models = [m.get("name") for m in res.json().get("models", [])]
            for target in ["testsentry-model", "llama3.2", OLLAMA_MODEL]:
                for m in models:
                    if target in m:
                        return m
            if models:
                return models[0]
    except Exception:
        pass
    return OLLAMA_MODEL




def parse_triage_response(content: str) -> dict:
    """Strictly parse and validate model output."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:] if text.lstrip().startswith("json") else text
    data = json.loads(text.strip())
    categories = {"REAL_BUG", "FLAKY", "ENV_ISSUE", "DATA_ISSUE"}
    if data.get("category") not in categories:
        raise ValueError("invalid triage category")
    confidence = max(0, min(100, int(data.get("confidence_pct", 85))))
    for key in ("why_it_failed", "suggested_fix", "affected_module"):
        data[key] = str(data.get(key, ""))
    data["confidence_pct"] = confidence
    return data


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
        store_triage_event(result.get("run_id"), fp, "ollama", True)
        print(f"\n[TestSentry] 💾 CACHE HIT — {test_name}")
        print(f"             Category: {cached['category']}")
        return cached

    active_model = get_installed_ollama_model()

    try:
        print(f"\n[TestSentry] 🤖 LOCAL MODEL ({active_model}) — {test_name}")

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": active_model,
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

        res_json = response.json()
        if "error" in res_json or "response" not in res_json:
            raise ValueError(res_json.get("error", "Invalid response format from Ollama"))

        content = res_json["response"]

        triage_dict = parse_triage_response(content)
        triage_dict["cache_hit"] = False

        cache_store(fp, triage_dict)
        store_triage_event(result.get("run_id"), fp, "ollama", False)

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
    Fallback when Ollama is not running or fails.
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
        store_triage_event(result.get("run_id"), fp, "groq", True)
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

    # Models confirmed available on this Groq account (checked 2026-08-29)
    groq_models = [
        "qwen/qwen3.8-27b",       # best reasoning
        "openai/gpt-oss-120b",    # largest, strong fallback
        "openai/gpt-oss-20b",     # fast fallback
    ]
    # Use plain Groq client (not instructor) — new models don't support tool-calling schema
    raw_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    start_time = time.time()

    prompt = f"""Analyze this pytest failure and return ONLY valid JSON, no explanation.

Test: {test_name}
Error: {error_msg}

Return exactly this JSON structure:
{{"category": "REAL_BUG or FLAKY or ENV_ISSUE or DATA_ISSUE",
"confidence_pct": 90,
"why_it_failed": "plain English explanation",
"suggested_fix": "exact fix to apply",
"affected_module": "filename.py"}}"""

    for gmodel in groq_models:
        try:
            print(f"             Trying Groq model: {gmodel}")
            completion = raw_client.chat.completions.create(
                model=gmodel,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior QA engineer. Return ONLY valid JSON, no markdown, no explanation."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=512,
            )
            content = completion.choices[0].message.content.strip()

            # Strip markdown fences if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            triage_dict = parse_triage_response(content)
            triage_dict["cache_hit"] = False
            triage_dict["groq_model_used"] = gmodel

            print(f"             ✅ Success with model: {gmodel}")
            print(f"             Category:   {triage_dict['category']}")
            print(f"             Confidence: {triage_dict['confidence_pct']}%")
            print(f"             Why:        {triage_dict.get('why_it_failed', '')}")
            print(f"             Fix:        {triage_dict.get('suggested_fix', '')}")
           
            cache_store(fp, triage_dict)
            store_triage_event(result.get("run_id"), fp, "groq", False)
            return triage_dict

        except Exception as err:
            print(f"[TestSentry] ⚠️ Groq error ({gmodel}): {err}")
            continue

    print("[TestSentry] ❌ All Groq models failed.")
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