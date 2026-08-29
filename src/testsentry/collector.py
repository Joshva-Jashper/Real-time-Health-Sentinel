import duckdb
import os
import threading
from datetime import datetime
from testsentry.fingerprinter import fingerprint


DB_PATH = os.path.join(os.getcwd(), "testsentry.db")

# One write connection for the collector/plugin (protected by a lock)
_write_lock = threading.Lock()
_write_conn: duckdb.DuckDBPyConnection | None = None

# Thread-local read connections for the API layer
_thread_local = threading.local()


def _get_write_conn() -> duckdb.DuckDBPyConnection:
    """Return the single write connection (used only by collector/init)."""
    global _write_conn
    with _write_lock:
        if _write_conn is None:
            _write_conn = duckdb.connect(DB_PATH, read_only=False)
        return _write_conn


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Return a per-thread DuckDB connection.

    Each OS thread (FastAPI worker thread / pytest main thread) gets its own
    private connection so that concurrent .execute() calls never corrupt each
    other's result sets.  The connection is lazily created and automatically
    re-opened if it was closed (e.g., by test code calling conn.close()).
    """
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        # Probe the connection — if it was closed externally, re-open it.
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception:
            conn = None
            _thread_local.conn = None

    if conn is None:
        try:
            conn = duckdb.connect(DB_PATH, read_only=False)
        except Exception:
            conn = duckdb.connect(DB_PATH, read_only=True)
        _thread_local.conn = conn
    return conn


def init_db():
    """
    Create all tables if they don't exist.
    Called once when TestSentry starts.
    """
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS test_runs (
            run_id      VARCHAR,
            test_name   VARCHAR,
            status      VARCHAR,
            duration    FLOAT,
            error_msg   VARCHAR,
            fingerprint VARCHAR,
            label       VARCHAR DEFAULT 'STABLE',
            timestamp   TIMESTAMP
        )
    """)
    # Add fingerprint column if DB existed prior to this update
    try:
        conn.execute("ALTER TABLE test_runs ADD COLUMN fingerprint VARCHAR")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_metadata (
            run_id      VARCHAR,
            started_at  TIMESTAMP,
            finished_at TIMESTAMP,
            total_tests INTEGER DEFAULT 0,
            passed      INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_cache (
            fingerprint     VARCHAR PRIMARY KEY,
            category        VARCHAR,
            confidence_pct  INTEGER,
            why_it_failed   VARCHAR,
            suggested_fix   VARCHAR,
            affected_module VARCHAR,
            hit_count       INTEGER DEFAULT 0,
            created_at      TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_cache_lock (dummy INTEGER)
    """)
    # Migrate triage_cache to ensure all expected columns exist
    for col_def in [
        ("confidence_pct",  "INTEGER DEFAULT 0"),
        ("why_it_failed",   "VARCHAR"),
        ("suggested_fix",   "VARCHAR"),
        ("affected_module", "VARCHAR"),
        ("hit_count",       "INTEGER DEFAULT 0"),
        ("created_at",      "TIMESTAMP"),
    ]:
        try:
            conn.execute(f"ALTER TABLE triage_cache ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass  # column already exists
    pass  # shared connection — do not close
    print("[TestSentry] Database initialized at testsentry.db")


def store_result(result: dict, run_id: str, label: str = "NEW_TEST"):
    """
    Save a single test result to DuckDB.
    Called after every test finishes.
    """
    conn = get_connection()
    fp = fingerprint(result["error_msg"]) if result.get("error_msg") else None
    conn.execute("""
        INSERT INTO test_runs
            (run_id, test_name, status, duration, error_msg, fingerprint, label, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        run_id,
        result["test_name"],
        result["status"],
        result["duration"],
        result["error_msg"],
        fp,
        label,
        datetime.now()
    ])
    pass  # shared connection — do not close


def store_run_metadata(run_id: str, started_at: datetime, finished_at: datetime, total: int, passed: int, failed: int):
    """
    Record complete run session metadata in DuckDB.
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO run_metadata
            (run_id, started_at, finished_at, total_tests, passed, failed)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [run_id, started_at, finished_at, total, passed, failed])
    pass  # shared connection — do not close


def get_recent_runs(limit: int = 10):
    """
    Fetch the most recent test results.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name, status, duration, timestamp
        FROM test_runs
        ORDER BY timestamp DESC
        LIMIT ?
    """, [limit]).fetchall()
    pass  # shared connection — do not close
    return rows


def _ensure_triage_cache(conn):
    """Ensure triage_cache table exists — safe to call multiple times."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_cache (
            fingerprint     VARCHAR PRIMARY KEY,
            category        VARCHAR,
            confidence_pct  INTEGER,
            why_it_failed   VARCHAR,
            suggested_fix   VARCHAR,
            affected_module VARCHAR,
            hit_count       INTEGER DEFAULT 0,
            created_at      TIMESTAMP
        )
    """)


def cache_lookup(fp: str):
    """
    Check if a fingerprint exists in the triage cache.
    Returns cached result dict or None if not found.
    """
    conn = get_connection()
    _ensure_triage_cache(conn)
    row = conn.execute("""
        SELECT category, confidence_pct, why_it_failed,
               suggested_fix, affected_module
        FROM triage_cache
        WHERE fingerprint = ?
    """, [fp]).fetchone()

    if row:
        # Increment hit counter
        conn.execute("""
            UPDATE triage_cache
            SET hit_count = hit_count + 1
            WHERE fingerprint = ?
        """, [fp])
        pass  # shared connection — do not close
        return {
            "category":        row[0],
            "confidence_pct":  row[1],
            "why_it_failed":   row[2],
            "suggested_fix":   row[3],
            "affected_module": row[4],
            "cache_hit":       True
        }

    pass  # shared connection — do not close
    return None


def cache_store(fp: str, triage_result: dict):
    """
    Store a new triage result in the cache.
    Called after every fresh AI API call.
    """
    conn = get_connection()
    _ensure_triage_cache(conn)
    try:
        conn.execute("""
            INSERT INTO triage_cache
                (fingerprint, category, confidence_pct,
                 why_it_failed, suggested_fix, affected_module,
                 hit_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT (fingerprint) DO UPDATE SET
                category        = EXCLUDED.category,
                confidence_pct  = EXCLUDED.confidence_pct,
                why_it_failed   = EXCLUDED.why_it_failed,
                suggested_fix   = EXCLUDED.suggested_fix,
                affected_module = EXCLUDED.affected_module,
                created_at      = EXCLUDED.created_at
        """, [
            fp,
            triage_result["category"],
            triage_result["confidence_pct"],
            triage_result["why_it_failed"],
            triage_result["suggested_fix"],
            triage_result.get("affected_module", "unknown"),
            datetime.now()
        ])
    except Exception as e:
        print(f"[TestSentry] ⚠️ cache_store error: {e}")
    pass  # shared connection — do not close


def get_newly_failing_with_triage(run_id: str) -> list:
    """
    Get newly failing tests with triage data for notifications.
    Joined on matching error stack trace fingerprint.
    """
    from testsentry.ownership_mapper import get_file_owners

    conn = get_connection()
    rows = conn.execute("""
        SELECT t.test_name,
               t.error_msg,
               c.category,
               c.suggested_fix
        FROM test_runs t
        LEFT JOIN triage_cache c
            ON t.fingerprint = c.fingerprint
        WHERE t.run_id = ?
        AND t.label = 'NEWLY_FAILING'
        LIMIT 10
    """, [run_id]).fetchall()
    pass  # shared connection — do not close

    owners = get_file_owners(".")
    results = []

    for row in rows:
        test_name, error_msg, category, suggested_fix = row
        file_path = test_name.split("::")[0] if "::" in test_name else test_name
        owner = owners.get(file_path, "unowned")
        results.append({
            "test_name":     test_name,
            "owner":         owner,
            "category":      category or "UNKNOWN",
            "suggested_fix": suggested_fix or "Check the error logs"
        })

    return results


def get_fixed_tests(run_id: str) -> list:
    """Get tests that were fixed in this run."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name
        FROM test_runs
        WHERE run_id = ?
        AND label = 'FIXED'
    """, [run_id]).fetchall()
    pass  # shared connection — do not close
    return [{"test_name": row[0]} for row in rows]
 