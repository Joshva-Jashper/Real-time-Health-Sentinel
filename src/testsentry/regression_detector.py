from testsentry.collector import get_connection


def label_test(result: dict, run_id: str) -> str:
    """
    Compare current test status against previous run.
    Assigns one of 5 labels:

    NEW_TEST       — never seen before
    NEWLY_FAILING  — was passing, now failing ← most important
    FIXED          — was failing, now passing
    REOPENED       — was fixed, failed again
    STILL_FAILING  — was failing, still failing
    STABLE         — was passing, still passing
    """
    test_name = result["test_name"]
    current_status = result["status"]

    conn = get_connection()

    
    prev = conn.execute("""
        SELECT status
        FROM test_runs
        WHERE test_name = ?
        AND run_id != ?
        ORDER BY timestamp DESC
        LIMIT 1
    """, [test_name, run_id]).fetchone()

    pass  # shared connection — do not close

    if not prev:
        return "NEWLY_FAILING" if current_status == "FAILED" else "NEW_TEST"

    prev_status = prev[0]

    
    if prev_status == "PASSED" and current_status == "FAILED":
        label = "NEWLY_FAILING"   
    elif prev_status == "FAILED" and current_status == "PASSED":
        label = "FIXED"          
    elif prev_status == "FAILED" and current_status == "FAILED":
        label = "STILL_FAILING"   
    else:
        label = "STABLE"          

    return label


def get_regression_summary(run_id: str) -> dict:
    """
    Get a summary of all regression labels for a run.
    Used in HTML report and PR comment.
    """
    conn = get_connection()

    rows = conn.execute("""
        SELECT label, COUNT(*) as count
        FROM test_runs
        WHERE run_id = ?
        GROUP BY label
    """, [run_id]).fetchall()

    pass  # shared connection — do not close

   
    summary = {
        "NEWLY_FAILING": 0,
        "FIXED":         0,
        "REOPENED":      0,
        "STILL_FAILING": 0,
        "STABLE":        0,
        "NEW_TEST":      0,
    }

    for row in rows:
        if len(row) >= 2:
            label, count = row[0], row[1]
            if label in summary:
                summary[label] = count

    return summary