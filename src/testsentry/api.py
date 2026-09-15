"""
TestSentry FastAPI Backend
Serves all dashboard data from the existing DuckDB + modules.
No logic changes — pure presentation layer.
"""
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from testsentry.collector import get_connection
from testsentry.health_engine import calculate_health_score
from testsentry.regression_detector import get_regression_summary
from testsentry.ownership_mapper import get_at_risk_modules
from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary
from testsentry.report_generator import get_ai_stats

app = FastAPI(
    title="TestSentry Dashboard API",
    version="2.1.0",
    description="Read-only test health analytics with optional AI triage.",
)


class TriageRequest(BaseModel):
    test_name: str = Field(default="unknown", min_length=1, max_length=500)
    error_msg: str = Field(min_length=1, max_length=20_000)

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    expected = os.getenv("TESTSENTRY_API_KEY")
    if expected and request.url.path.startswith("/api/") and request.headers.get("x-api-key") != expected:
        return JSONResponse({"detail": "API key required"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8088").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _get_latest_run_id() -> str | None:
    conn = get_connection()
    row = conn.execute("""
        SELECT run_id FROM test_runs
        ORDER BY timestamp DESC LIMIT 1
    """).fetchone()
    pass  # shared connection — do not close
    return row[0] if row else None


@app.get("/api/runs")
def list_runs(limit: int = Query(10, ge=1, le=100)):
    """Return a list of recent run IDs with timestamps."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT run_id, MIN(timestamp) as started, MAX(timestamp) as finished,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) as passed,
               SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed
        FROM test_runs
        GROUP BY run_id
        ORDER BY started DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "run_id": r[0],
            "started": str(r[1]),
            "finished": str(r[2]),
            "total": r[3],
            "passed": r[4],
            "failed": r[5],
        }
        for r in rows
    ]


@app.get("/api/health/latest")
def health_latest():
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    return calculate_health_score(run_id)


@app.get("/api/health/{run_id}")
def health(run_id: str):
    """Return the 5-dimension health score for a run."""
    return calculate_health_score(run_id)


@app.get("/api/regression/{run_id}")
def regression(run_id: str):
    """Return regression label summary for a run."""
    return get_regression_summary(run_id)


@app.get("/api/flaky")
def flaky(run_id: str = None):
    """Return flaky test list and summary."""
    tests = get_all_flaky_tests(run_id)
    summary = get_flakiness_summary(run_id)
    return {"summary": summary, "tests": tests}


@app.get("/api/risk")
def risk():
    """Return at-risk modules with owner + failure data."""
    try:
        return get_at_risk_modules(".")
    except Exception as e:
        return []


@app.get("/api/ai-stats/{run_id}")
def ai_stats(run_id: str):
    """Return AI triage cache statistics."""
    return get_ai_stats(run_id)


@app.get("/api/tests/{run_id}")
def test_results(run_id: str):
    """Return all test results for a specific run."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name, status, duration, error_msg, label, timestamp
        FROM test_runs
        WHERE run_id = ?
        ORDER BY timestamp DESC
    """, [run_id]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "test_name": r[0] if len(r) > 0 else "",
            "status":    r[1] if len(r) > 1 else "",
            "duration":  r[2] if len(r) > 2 else None,
            "error_msg": r[3] if len(r) > 3 else None,
            "label":     r[4] if len(r) > 4 else "",
            "timestamp": str(r[5]) if len(r) > 5 else "",
        }
        for r in rows
    ]


@app.get("/api/triage-cache")
def triage_cache():
    """Return all cached triage results."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fingerprint, category, confidence_pct, why_it_failed,
               suggested_fix, affected_module, hit_count, created_at
        FROM triage_cache
        ORDER BY hit_count DESC
        LIMIT 50
    """).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "fingerprint":    (r[0][:12] + "...") if r[0] else "unknown",
            "category":       r[1] if len(r) > 1 else "UNKNOWN",
            "confidence_pct": r[2] if len(r) > 2 else 0,
            "why_it_failed":  r[3] if len(r) > 3 else "",
            "suggested_fix":  r[4] if len(r) > 4 else "",
            "affected_module":r[5] if len(r) > 5 else "unknown",
            "hit_count":      r[6] if len(r) > 6 else 0,
            "created_at":     str(r[7]) if len(r) > 7 else "",
        }
        for r in rows
    ]


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    """Return health score history for sparkline charts."""
    conn = get_connection()
    runs = conn.execute("""
        SELECT DISTINCT run_id, MIN(timestamp) as started
        FROM test_runs
        GROUP BY run_id
        ORDER BY started DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close

    result = []
    for row in reversed(runs):
        rid = row[0]
        started = row[1] if len(row) > 1 else None
        score = calculate_health_score(rid)
        result.append({
            "run_id": rid,
            "started": str(started),
            "total_score": score["total_score"],
            "pass_rate": score["pass_rate"],
            "flaky_count": score["flaky_count"],
            "grade": score["grade"],
        })
    return result



@app.post("/api/triage-test")
def triage_test_endpoint(payload: TriageRequest):
    """
    On-demand AI triage endpoint for UI interaction.
    Expects {'test_name': str, 'error_msg': str}.
    """
    from testsentry.ai_triage import triage_failure
    test_name = payload.test_name
    error_msg = payload.error_msg

    result = triage_failure({"test_name": test_name, "error_msg": error_msg})
    if not result:
        raise HTTPException(status_code=500, detail="AI triage service unavailable. Ensure Ollama is running.")
    return result



# Serve static dashboard assets at /static/* so /api/* routes are never shadowed
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")
_STATIC_DIR = os.path.abspath(_STATIC_DIR)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve the SPA index.html from the dashboard directory."""
    index_path = os.path.join(_STATIC_DIR, "index.html")
    return FileResponse(index_path)


def main():
    import uvicorn
    uvicorn.run("testsentry.api:app", host=os.getenv("TESTSENTRY_HOST", "127.0.0.1"), port=8088, reload=True)
"""
TestSentry FastAPI Backend
Serves all dashboard data from the existing DuckDB + modules.
No logic changes — pure presentation layer.
"""
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from testsentry.collector import get_connection, init_db
from testsentry.health_engine import calculate_health_score
from testsentry.regression_detector import get_regression_summary
from testsentry.ownership_mapper import get_at_risk_modules
from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary
from testsentry.report_generator import get_ai_stats

app = FastAPI(
    title="TestSentry Dashboard API",
    version="2.1.0",
    description="Read-only test health analytics with optional AI triage.",
)

# Make the empty dashboard safe to open before the first test run.
init_db()


class TriageRequest(BaseModel):
    test_name: str = Field(default="unknown", min_length=1, max_length=500)
    error_msg: str = Field(min_length=1, max_length=20_000)

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    expected = os.getenv("TESTSENTRY_API_KEY")
    if expected and request.url.path.startswith("/api/") and request.headers.get("x-api-key") != expected:
        return JSONResponse({"detail": "API key required"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8088").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _get_latest_run_id() -> str | None:
    conn = get_connection()
    row = conn.execute("""
        SELECT run_id FROM test_runs
        ORDER BY timestamp DESC LIMIT 1
    """).fetchone()
    pass  # shared connection — do not close
    return row[0] if row else None


@app.get("/api/runs")
def list_runs(limit: int = Query(10, ge=1, le=100)):
    """Return completed pytest runs, not synthetic/history result rows."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.run_id, m.started_at, m.finished_at,
               m.total_tests, m.passed, m.failed
        FROM run_metadata AS m
        ORDER BY m.finished_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "run_id": r[0],
            "started": str(r[1]),
            "finished": str(r[2]),
            "total": r[3],
            "passed": r[4],
            "failed": r[5],
        }
        for r in rows
    ]


@app.get("/api/health/latest")
def health_latest():
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    return calculate_health_score(run_id)


@app.get("/api/health/{run_id}")
def health(run_id: str):
    """Return the 5-dimension health score for a run."""
    return calculate_health_score(run_id)


@app.get("/api/regression/{run_id}")
def regression(run_id: str):
    """Return regression label summary for a run."""
    return get_regression_summary(run_id)


@app.get("/api/flaky")
def flaky(run_id: str = None):
    """Return flaky test list and summary."""
    tests = get_all_flaky_tests(run_id)
    summary = get_flakiness_summary(run_id)
    return {"summary": summary, "tests": tests}


@app.get("/api/risk")
def risk():
    """Return at-risk modules with owner + failure data."""
    try:
        return get_at_risk_modules(".")
    except Exception as e:
        return []


@app.get("/api/ai-stats/{run_id}")
def ai_stats(run_id: str):
    """Return AI triage cache statistics."""
    return get_ai_stats(run_id)


@app.get("/api/tests/{run_id}")
def test_results(run_id: str):
    """Return all test results for a specific run."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name, status, duration, error_msg, label, timestamp
        FROM test_runs
        WHERE run_id = ? AND phase = 'call'
        ORDER BY timestamp DESC
    """, [run_id]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "test_name": r[0] if len(r) > 0 else "",
            "status":    r[1] if len(r) > 1 else "",
            "duration":  r[2] if len(r) > 2 else None,
            "error_msg": r[3] if len(r) > 3 else None,
            "label":     r[4] if len(r) > 4 else "",
            "timestamp": str(r[5]) if len(r) > 5 else "",
        }
        for r in rows
    ]


@app.get("/api/triage-cache")
def triage_cache():
    """Return all cached triage results."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fingerprint, category, confidence_pct, why_it_failed,
               suggested_fix, affected_module, hit_count, created_at
        FROM triage_cache
        ORDER BY hit_count DESC
        LIMIT 50
    """).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "fingerprint":    (r[0][:12] + "...") if r[0] else "unknown",
            "category":       r[1] if len(r) > 1 else "UNKNOWN",
            "confidence_pct": r[2] if len(r) > 2 else 0,
            "why_it_failed":  r[3] if len(r) > 3 else "",
            "suggested_fix":  r[4] if len(r) > 4 else "",
            "affected_module":r[5] if len(r) > 5 else "unknown",
            "hit_count":      r[6] if len(r) > 6 else 0,
            "created_at":     str(r[7]) if len(r) > 7 else "",
        }
        for r in rows
    ]


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    """Return health score history for sparkline charts."""
    conn = get_connection()
    runs = conn.execute("""
        SELECT DISTINCT run_id, MIN(timestamp) as started
        FROM test_runs
        GROUP BY run_id
        ORDER BY started DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close

    result = []
    for row in reversed(runs):
        rid = row[0]
        started = row[1] if len(row) > 1 else None
        score = calculate_health_score(rid)
        result.append({
            "run_id": rid,
            "started": str(started),
            "total_score": score["total_score"],
            "pass_rate": score["pass_rate"],
            "flaky_count": score["flaky_count"],
            "grade": score["grade"],
        })
    return result



@app.post("/api/triage-test")
def triage_test_endpoint(payload: TriageRequest):
    """
    On-demand AI triage endpoint for UI interaction.
    Expects {'test_name': str, 'error_msg': str}.
    """
    from testsentry.ai_triage import triage_failure
    test_name = payload.test_name
    error_msg = payload.error_msg

    result = triage_failure({"test_name": test_name, "error_msg": error_msg})
    if not result:
        raise HTTPException(status_code=500, detail="AI triage service unavailable. Ensure Ollama is running.")
    return result



# Serve static dashboard assets at /static/* so /api/* routes are never shadowed
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")
_STATIC_DIR = os.path.abspath(_STATIC_DIR)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve the SPA index.html from the dashboard directory."""
    index_path = os.path.join(_STATIC_DIR, "index.html")
    return FileResponse(index_path)


def main():
    import uvicorn
    uvicorn.run("testsentry.api:app", host=os.getenv("TESTSENTRY_HOST", "127.0.0.1"), port=8088, reload=True)
"""
TestSentry FastAPI Backend
Serves all dashboard data from the existing DuckDB + modules.
No logic changes — pure presentation layer.
"""
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from testsentry.collector import get_connection, init_db
from testsentry.health_engine import calculate_health_score
from testsentry.regression_detector import get_regression_summary
from testsentry.ownership_mapper import get_at_risk_modules
from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary
from testsentry.report_generator import get_ai_stats

app = FastAPI(
    title="TestSentry Dashboard API",
    version="2.1.0",
    description="Read-only test health analytics with optional AI triage.",
)

# Make the empty dashboard safe to open before the first test run.
init_db()


class TriageRequest(BaseModel):
    test_name: str = Field(default="unknown", min_length=1, max_length=500)
    error_msg: str = Field(min_length=1, max_length=20_000)

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    expected = os.getenv("TESTSENTRY_API_KEY")
    if expected and request.url.path.startswith("/api/") and request.headers.get("x-api-key") != expected:
        return JSONResponse({"detail": "API key required"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8088").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _get_latest_run_id() -> str | None:
    conn = get_connection()
    row = conn.execute("""
        SELECT run_id FROM test_runs
        ORDER BY timestamp DESC LIMIT 1
    """).fetchone()
    pass  # shared connection — do not close
    return row[0] if row else None


@app.get("/api/runs")
def list_runs(limit: int = Query(10, ge=1, le=100)):
    """Return completed pytest runs, not synthetic/history result rows."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.run_id, m.started_at, m.finished_at,
               m.total_tests, m.passed, m.failed
        FROM run_metadata AS m
        ORDER BY m.finished_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "run_id": r[0],
            "started": str(r[1]),
            "finished": str(r[2]),
            "total": r[3],
            "passed": r[4],
            "failed": r[5],
        }
        for r in rows
    ]


@app.get("/api/health/latest")
def health_latest():
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    return calculate_health_score(run_id)


@app.get("/api/health/{run_id}")
def health(run_id: str):
    """Return the 5-dimension health score for a run."""
    return calculate_health_score(run_id)


@app.get("/api/regression/{run_id}")
def regression(run_id: str):
    """Return regression label summary for a run."""
    return get_regression_summary(run_id)


@app.get("/api/flaky")
def flaky(run_id: str = None):
    """Return flaky test list and summary."""
    tests = get_all_flaky_tests(run_id)
    summary = get_flakiness_summary(run_id)
    return {"summary": summary, "tests": tests}


@app.get("/api/risk")
def risk():
    """Return at-risk modules with owner + failure data."""
    try:
        return get_at_risk_modules(".")
    except Exception as e:
        return []


@app.get("/api/ai-stats/{run_id}")
def ai_stats(run_id: str):
    """Return AI triage cache statistics."""
    return get_ai_stats(run_id)


@app.get("/api/tests/{run_id}")
def test_results(run_id: str):
    """Return all test results for a specific run."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name, status, duration, error_msg, label, timestamp
        FROM test_runs
        WHERE run_id = ? AND phase = 'call'
        ORDER BY timestamp DESC
    """, [run_id]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "test_name": r[0] if len(r) > 0 else "",
            "status":    r[1] if len(r) > 1 else "",
            "duration":  r[2] if len(r) > 2 else None,
            "error_msg": r[3] if len(r) > 3 else None,
            "label":     r[4] if len(r) > 4 else "",
            "timestamp": str(r[5]) if len(r) > 5 else "",
        }
        for r in rows
    ]


@app.get("/api/triage-cache")
def triage_cache():
    """Return all cached triage results."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fingerprint, category, confidence_pct, why_it_failed,
               suggested_fix, affected_module, hit_count, created_at
        FROM triage_cache
        ORDER BY hit_count DESC
        LIMIT 50
    """).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "fingerprint":    (r[0][:12] + "...") if r[0] else "unknown",
            "category":       r[1] if len(r) > 1 else "UNKNOWN",
            "confidence_pct": r[2] if len(r) > 2 else 0,
            "why_it_failed":  r[3] if len(r) > 3 else "",
            "suggested_fix":  r[4] if len(r) > 4 else "",
            "affected_module":r[5] if len(r) > 5 else "unknown",
            "hit_count":      r[6] if len(r) > 6 else 0,
            "created_at":     str(r[7]) if len(r) > 7 else "",
        }
        for r in rows
    ]


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    """Return health score history for sparkline charts."""
    conn = get_connection()
    runs = conn.execute("""
        SELECT DISTINCT run_id, MIN(timestamp) as started
        FROM test_runs
        GROUP BY run_id
        ORDER BY started DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close

    result = []
    for row in reversed(runs):
        rid = row[0]
        started = row[1] if len(row) > 1 else None
        score = calculate_health_score(rid)
        result.append({
            "run_id": rid,
            "started": str(started),
            "total_score": score["total_score"],
            "pass_rate": score["pass_rate"],
            "flaky_count": score["flaky_count"],
            "grade": score["grade"],
        })
    return result



@app.post("/api/triage-test")
def triage_test_endpoint(payload: TriageRequest):
    """
    On-demand AI triage endpoint for UI interaction.
    Expects {'test_name': str, 'error_msg': str}.
    """
    from testsentry.ai_triage import triage_failure
    test_name = payload.test_name
    error_msg = payload.error_msg

    result = triage_failure({"test_name": test_name, "error_msg": error_msg})
    if not result:
        raise HTTPException(status_code=500, detail="AI triage service unavailable. Ensure Ollama is running.")
    return result



# Serve static dashboard assets at /static/* so /api/* routes are never shadowed
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")
_STATIC_DIR = os.path.abspath(_STATIC_DIR)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve the SPA index.html from the dashboard directory."""
    index_path = os.path.join(_STATIC_DIR, "index.html")
    return FileResponse(index_path)


def main():
    import uvicorn
    uvicorn.run("testsentry.api:app", host=os.getenv("TESTSENTRY_HOST", "127.0.0.1"), port=8088, reload=True)
"""
TestSentry FastAPI Backend
Serves all dashboard data from the existing DuckDB + modules.
No logic changes — pure presentation layer.
"""
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from testsentry.collector import get_connection, init_db
from testsentry.health_engine import calculate_health_score
from testsentry.regression_detector import get_regression_summary
from testsentry.ownership_mapper import get_at_risk_modules
from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary
from testsentry.report_generator import get_ai_stats

app = FastAPI(
    title="TestSentry Dashboard API",
    version="2.1.0",
    description="Read-only test health analytics with optional AI triage.",
)

# Make the empty dashboard safe to open before the first test run.
init_db()


class TriageRequest(BaseModel):
    test_name: str = Field(default="unknown", min_length=1, max_length=500)
    error_msg: str = Field(min_length=1, max_length=20_000)

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    expected = os.getenv("TESTSENTRY_API_KEY")
    if expected and request.url.path.startswith("/api/") and request.headers.get("x-api-key") != expected:
        return JSONResponse({"detail": "API key required"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8088").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _get_latest_run_id() -> str | None:
    conn = get_connection()
    row = conn.execute("""
        SELECT run_id FROM test_runs
        ORDER BY timestamp DESC LIMIT 1
    """).fetchone()
    pass  # shared connection — do not close
    return row[0] if row else None


@app.get("/api/runs")
def list_runs(limit: int = Query(10, ge=1, le=100)):
    """Return completed pytest runs, not synthetic/history result rows."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT m.run_id, m.started_at, m.finished_at,
               m.total_tests, m.passed, m.failed
        FROM run_metadata AS m
        ORDER BY m.finished_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "run_id": r[0],
            "started": str(r[1]),
            "finished": str(r[2]),
            "total": r[3],
            "passed": r[4],
            "failed": r[5],
        }
        for r in rows
    ]


@app.get("/api/health/latest")
def health_latest():
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    return calculate_health_score(run_id)


@app.get("/api/health/{run_id}")
def health(run_id: str):
    """Return the 5-dimension health score for a run."""
    return calculate_health_score(run_id)


@app.get("/api/regression/{run_id}")
def regression(run_id: str):
    """Return regression label summary for a run."""
    return get_regression_summary(run_id)


@app.get("/api/flaky")
def flaky(run_id: str = None):
    """Return flaky test list and summary."""
    tests = get_all_flaky_tests(run_id)
    summary = get_flakiness_summary(run_id)
    return {"summary": summary, "tests": tests}


@app.get("/api/risk")
def risk():
    """Return at-risk modules with owner + failure data."""
    try:
        return get_at_risk_modules(".")
    except Exception as e:
        return []


@app.get("/api/ai-stats/{run_id}")
def ai_stats(run_id: str):
    """Return AI triage cache statistics."""
    return get_ai_stats(run_id)


@app.get("/api/tests/{run_id}")
def test_results(run_id: str):
    """Return all test results for a specific run."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name, status, duration, error_msg, label, timestamp
        FROM test_runs
        WHERE run_id = ? AND phase = 'call'
        ORDER BY timestamp DESC
    """, [run_id]).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "test_name": r[0] if len(r) > 0 else "",
            "status":    r[1] if len(r) > 1 else "",
            "duration":  r[2] if len(r) > 2 else None,
            "error_msg": r[3] if len(r) > 3 else None,
            "label":     r[4] if len(r) > 4 else "",
            "timestamp": str(r[5]) if len(r) > 5 else "",
        }
        for r in rows
    ]


@app.get("/api/triage-cache")
def triage_cache():
    """Return all cached triage results."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fingerprint, category, confidence_pct, why_it_failed,
               suggested_fix, affected_module, hit_count, created_at
        FROM triage_cache
        ORDER BY hit_count DESC
        LIMIT 50
    """).fetchall()
    pass  # shared connection — do not close
    return [
        {
            "fingerprint":    (r[0][:12] + "...") if r[0] else "unknown",
            "category":       r[1] if len(r) > 1 else "UNKNOWN",
            "confidence_pct": r[2] if len(r) > 2 else 0,
            "why_it_failed":  r[3] if len(r) > 3 else "",
            "suggested_fix":  r[4] if len(r) > 4 else "",
            "affected_module":r[5] if len(r) > 5 else "unknown",
            "hit_count":      r[6] if len(r) > 6 else 0,
            "created_at":     str(r[7]) if len(r) > 7 else "",
        }
        for r in rows
    ]


@app.get("/api/history")
def history(limit: int = Query(20, ge=1, le=100)):
    """Return health score history for sparkline charts."""
    conn = get_connection()
    runs = conn.execute("""
        SELECT DISTINCT run_id, MIN(timestamp) as started
        FROM test_runs
        GROUP BY run_id
        ORDER BY started DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close

    result = []
    for row in reversed(runs):
        rid = row[0]
        started = row[1] if len(row) > 1 else None
        score = calculate_health_score(rid)
        result.append({
            "run_id": rid,
            "started": str(started),
            "total_score": score["total_score"],
            "pass_rate": score["pass_rate"],
            "flaky_count": score["flaky_count"],
            "grade": score["grade"],
        })
    return result



@app.post("/api/triage-test")
def triage_test_endpoint(payload: TriageRequest):
    """
    On-demand AI triage endpoint for UI interaction.
    Expects {'test_name': str, 'error_msg': str}.
    """
    from testsentry.ai_triage import triage_failure
    test_name = payload.test_name
    error_msg = payload.error_msg

    result = triage_failure({"test_name": test_name, "error_msg": error_msg})
    if not result:
        raise HTTPException(status_code=500, detail="AI triage service unavailable. Ensure Ollama is running.")
    return result



# Serve static dashboard assets at /static/* so /api/* routes are never shadowed
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard")
_STATIC_DIR = os.path.abspath(_STATIC_DIR)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve the SPA index.html from the dashboard directory."""
    index_path = os.path.join(_STATIC_DIR, "index.html")
    return FileResponse(index_path)


def main():
    import uvicorn
    uvicorn.run("testsentry.api:app", host=os.getenv("TESTSENTRY_HOST", "127.0.0.1"), port=8088, reload=True)
