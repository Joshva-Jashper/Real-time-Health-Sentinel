"""FastAPI backend for the TestSentry dashboard."""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from testsentry.collector import get_connection, init_db
from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary
from testsentry.health_engine import calculate_health_score
from testsentry.ownership_mapper import get_at_risk_modules
from testsentry.regression_detector import get_regression_summary
from testsentry.report_generator import get_ai_stats


app = FastAPI(
    title="TestSentry Dashboard API",
    version="2.1.0",
    description="Test health analytics with optional AI triage.",
)

# Make the dashboard safe to open before the first test run.
init_db()


class TriageRequest(BaseModel):
    test_name: str = Field(default="unknown", min_length=1, max_length=500)
    error_msg: str = Field(min_length=1, max_length=20_000)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    expected = os.getenv("TESTSENTRY_API_KEY")
    if expected and request.url.path.startswith("/api/"):
        if request.headers.get("x-api-key") != expected:
            return JSONResponse({"detail": "API key required"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8088").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def _latest_run_id() -> Optional[str]:
    conn = get_connection()
    row = conn.execute(
        "SELECT run_id FROM run_metadata ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


@app.get("/api/runs")
def list_runs(limit: int = Query(10, ge=1, le=100)):
    """Return completed pytest sessions from authoritative run metadata."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT run_id, started_at, finished_at, total_tests, passed, failed
        FROM run_metadata
        ORDER BY finished_at DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {
            "run_id": row[0],
            "started": str(row[1]),
            "finished": str(row[2]),
            "total": row[3],
            "passed": row[4],
            "failed": row[5],
        }
        for row in rows
    ]


@app.get("/api/health/latest")
def health_latest():
    run_id = _latest_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    return calculate_health_score(run_id)


@app.get("/api/health/{run_id}")
def health(run_id: str):
    return calculate_health_score(run_id)


@app.get("/api/regression/{run_id}")
def regression(run_id: str):
    return get_regression_summary(run_id)


@app.get("/api/flaky")
def flaky(run_id: Optional[str] = None):
    return {
        "summary": get_flakiness_summary(run_id),
        "tests": get_all_flaky_tests(run_id),
    }


@app.get("/api/risk")
def risk():
    try:
        return get_at_risk_modules(".")
    except Exception:
        return []


@app.get("/api/ai-stats/{run_id}")
def ai_stats(run_id: str):
    return get_ai_stats(run_id)


@app.get("/api/tests/{run_id}")
def test_results(run_id: str):
    """Return one row per actual pytest call, excluding setup/teardown phases."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT test_name, status, duration, error_msg, label, timestamp
        FROM test_runs
        WHERE run_id = ? AND phase = 'call'
        ORDER BY timestamp DESC
        """,
        [run_id],
    ).fetchall()
    return [
        {
            "test_name": row[0],
            "status": row[1],
            "duration": row[2],
            "error_msg": row[3],
            "label": row[4],
            "timestamp": str(row[5]),
        }
        for row in rows
    ]


@app.get("/api/triage-cache")
def triage_cache():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT fingerprint, category, confidence_pct, why_it_failed,
               suggested_fix, affected_module, hit_count, created_at
        FROM triage_cache
        ORDER BY hit_count DESC
        LIMIT 50
        """
    ).fetchall()
    return [
        {
            "fingerprint": f"{row[0][:12]}..." if row[0] else "unknown",
            "category": row[1] or "UNKNOWN",
            "confidence_pct": row[2] or 0,
            "why_it_failed": row[3] or "",
            "suggested_fix": row[4] or "",
            "affected_module": row[5] or "unknown",
            "hit_count": row[6] or 0,
            "created_at": str(row[7]) if row[7] else "",
        }
        for row in rows
    ]


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    """Return history for completed sessions, excluding synthetic result rows."""
    conn = get_connection()
    runs = conn.execute(
        """
        SELECT run_id, started_at
        FROM run_metadata
        ORDER BY finished_at DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    result = []
    for run_id, started in reversed(runs):
        score = calculate_health_score(run_id)
        result.append(
            {
                "run_id": run_id,
                "started": str(started),
                "total_score": score["total_score"],
                "pass_rate": score["pass_rate"],
                "flaky_count": score["flaky_count"],
                "grade": score["grade"],
            }
        )
    return result


@app.post("/api/triage-test")
def triage_test_endpoint(payload: TriageRequest):
    """Run AI triage for a failure supplied by the dashboard."""
    from testsentry.ai_triage import triage_failure

    result = triage_failure(
        {"test_name": payload.test_name, "error_msg": payload.error_msg}
    )
    if not result:
        raise HTTPException(
            status_code=503,
            detail="AI triage service unavailable. Configure an AI backend.",
        )
    return result


_STATIC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")
)
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


def main():
    import uvicorn

    uvicorn.run(
        "testsentry.api:app",
        host=os.getenv("TESTSENTRY_HOST", "127.0.0.1"),
        port=int(os.getenv("TESTSENTRY_PORT", "8088")),
        reload=os.getenv("TESTSENTRY_RELOAD", "false").lower() == "true",
    )
