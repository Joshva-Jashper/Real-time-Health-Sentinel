import os
import json
import subprocess
from testsentry.collector import get_connection


def run_coverage(test_path: str = "tests/") -> dict:
    """
    Run pytest with coverage and return per-file coverage data.
    Returns {filepath: coverage_pct} dict.
    """
    try:
        # Run pytest with coverage
        result = subprocess.run([
            "python3", "-m", "pytest",
            test_path,
            "--cov=src/testsentry",
            "--cov-report=json:coverage.json",
            "--cov-report=term-missing",
            "-q",
            "--no-header"
        ], capture_output=True, text=True, timeout=120)

        # Parse coverage.json
        if os.path.exists("coverage.json"):
            with open("coverage.json") as f:
                data = json.load(f)

            coverage_by_file = {}
            for filepath, stats in data["files"].items():
                pct = stats["summary"]["percent_covered"]
                coverage_by_file[filepath] = round(pct, 1)

            return coverage_by_file

    except Exception as e:
        print(f"[TestSentry] ⚠️ Coverage error: {e}")

    return {}


def get_coverage_summary() -> dict:
    """
    Get overall coverage summary.
    Returns overall percentage and per-file breakdown.
    """
    try:
        if os.path.exists("coverage.json"):
            with open("coverage.json") as f:
                data = json.load(f)

            total = data["totals"]["percent_covered"]
            files = {}
            for filepath, stats in data["files"].items():
                files[filepath] = {
                    "covered":   stats["summary"]["covered_lines"],
                    "missing":   stats["summary"]["missing_lines"],
                    "total":     stats["summary"]["num_statements"],
                    "pct":       round(stats["summary"]["percent_covered"], 1)
                }

            return {
                "total_pct": round(total, 1),
                "files":     files
            }
    except Exception as e:
        print(f"[TestSentry] ⚠️ Coverage summary error: {e}")

    return {"total_pct": 0.0, "files": {}}


def get_coverage_score() -> int:
    """
    Convert coverage percentage to 0-20 score for health engine.
    """
    summary = get_coverage_summary()
    pct = summary["total_pct"]

    if pct >= 90:
        return 20
    elif pct >= 75:
        return 15
    elif pct >= 60:
        return 10
    elif pct >= 40:
        return 5
    else:
        return 0


def store_coverage_in_db(run_id: str):
    """
    Store coverage data in DuckDB for historical tracking.
    """
    summary = get_coverage_summary()
    if not summary["files"]:
        return

    conn = get_connection()

    # Create coverage table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coverage_data (
            run_id       VARCHAR,
            filepath     VARCHAR,
            covered      INTEGER,
            missing      INTEGER,
            total        INTEGER,
            pct          FLOAT,
            timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for filepath, data in summary["files"].items():
        conn.execute("""
            INSERT INTO coverage_data
                (run_id, filepath, covered, missing, total, pct)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            run_id,
            filepath,
            data["covered"],
            data["missing"],
            data["total"],
            data["pct"]
        ])

    pass  # shared connection — do not close
    print(f"[TestSentry] 📊 Coverage stored: {summary['total_pct']}% overall")