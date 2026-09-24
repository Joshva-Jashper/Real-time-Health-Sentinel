from testsentry.collector import get_connection


def label_test(result: dict, run_id: str) -> str:
    """Classify a result against its previous observed statuses."""
    test_name = result["test_name"]
    current_status = result["status"]
    conn = get_connection()
    history = conn.execute("""
        SELECT status FROM test_runs
        WHERE test_name = ? AND run_id != ? AND phase = 'call'
        ORDER BY timestamp DESC, rowid DESC
        LIMIT 2
    """, [test_name, run_id]).fetchall()
    previous = [row[0] for row in history]
    if not previous:
        # First observation is always a new test. The summary separately counts
        # failed NEW_TEST rows as newly failing, so the two dashboard counters
        # can correctly overlap.
        return "NEW_TEST"
    prev = previous[0]
    if prev == "PASSED" and current_status == "FAILED":
        return "REOPENED" if len(previous) > 1 and previous[1] == "FAILED" else "NEWLY_FAILING"
    if prev == "FAILED" and current_status == "PASSED":
        return "FIXED"
    if prev == "FAILED" and current_status == "FAILED":
        return "STILL_FAILING"
    return "STABLE"


def get_regression_summary(run_id: str) -> dict:
    conn = get_connection()
    rows = conn.execute("""
        SELECT label, status, COUNT(*) FROM test_runs
        WHERE run_id = ? AND phase = 'call' GROUP BY label, status
    """, [run_id]).fetchall()
    summary = {label: 0 for label in (
        "NEWLY_FAILING", "FIXED", "REOPENED", "STILL_FAILING", "STABLE", "NEW_TEST"
    )}
    for label, status, count in rows:
        if label in summary:
            summary[label] = count
        if label == "NEW_TEST" and status == "FAILED":
            summary["NEWLY_FAILING"] += count
    return summary
