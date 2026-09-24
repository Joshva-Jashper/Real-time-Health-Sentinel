from testsentry.collector import get_connection
from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary


def calculate_health_score(run_id: str) -> dict:
    """
    Calculate a 5-dimension health score for a test run.
    Each dimension scores 0-20. Total is 0-100.

    Dimensions:
    1. Speed      — how fast are the tests?
    2. Stability  — how often do they pass?
    3. Flakiness  — which tests flip randomly?
    4. Coverage   — are all modules tested?
    5. Quality    — are failures meaningful?
    """
    conn = get_connection()

    # Average test duration check:
    speed_row = conn.execute("""
        SELECT AVG(duration) as avg_duration
        FROM test_runs
        WHERE run_id = ? AND phase = 'call'
    """, [run_id]).fetchone()

    try:
        avg_duration = float(speed_row[0]) if (speed_row and speed_row[0] is not None) else 0.0
    except (ValueError, TypeError):
        avg_duration = 0.0

    if avg_duration < 0.1:
        speed_score = 20      
    elif avg_duration < 0.5:
        speed_score = 15     
    elif avg_duration < 1.0:
        speed_score = 10     
    elif avg_duration < 2.0:
        speed_score = 5      
    else:
        speed_score = 0       

    
    # Pass rate in current run:
    stability_row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) as passed
        FROM test_runs
        WHERE run_id = ? AND phase = 'call'
    """, [run_id]).fetchone()

    try:
        total = int(stability_row[0]) if (stability_row and stability_row[0] is not None) else 1
        passed = int(stability_row[1]) if (stability_row and len(stability_row) > 1 and stability_row[1] is not None) else 0
    except (ValueError, TypeError, IndexError):
        total, passed = 1, 0
    pass_rate = (passed / total) * 100 if total > 0 else 0

    if pass_rate >= 95:
        stability_score = 20
    elif pass_rate >= 85:
        stability_score = 15
    elif pass_rate >= 70:
        stability_score = 10
    elif pass_rate >= 50:
        stability_score = 5
    else:
        stability_score = 0

    # Use the same strict classifier as the flaky leaderboard: repeated
    # alternation plus environmental/transient failure evidence.
    flaky_count = len(get_all_flaky_tests(run_id))

    if flaky_count == 0:
        flakiness_score = 20
    elif flaky_count <= 2:
        flakiness_score = 15
    elif flaky_count <= 5:
        flakiness_score = 10
    elif flaky_count <= 10:
        flakiness_score = 5
    else:
        flakiness_score = 0

  
    # Source coverage is unavailable without coverage.json; do not substitute
    # a different metric such as test stability under the coverage label.
    from testsentry.coverage_analyzer import get_coverage_summary, get_coverage_score
    cov_summary = get_coverage_summary()
    coverage_score = get_coverage_score() if cov_summary.get("total_pct", 0) > 0 else 0

    
    # Ratio of new_failing tests — fewer = better quality:
    quality_row = conn.execute("""
        SELECT COUNT(*) as newly_failing
        FROM test_runs
        WHERE run_id = ?
        AND phase = 'call'
        AND (label = 'NEWLY_FAILING' OR (label = 'NEW_TEST' AND status = 'FAILED'))
    """, [run_id]).fetchone()

    try:
        newly_failing = int(quality_row[0]) if (quality_row and quality_row[0] is not None) else 0
    except (ValueError, TypeError):
        newly_failing = 0

    if newly_failing == 0:
        quality_score = 20
    elif newly_failing <= 1:
        quality_score = 15
    elif newly_failing <= 3:
        quality_score = 10
    elif newly_failing <= 5:
        quality_score = 5
    else:
        quality_score = 0

    pass  # shared connection — do not close
    
    # Get detailed flakiness metrics
    flakiness_summary = get_flakiness_summary(run_id)
    flaky_tests_list = get_all_flaky_tests(run_id)

    # ── Total Score ───────────────────────────────────────────
    total_score = (
        speed_score +
        stability_score +
        flakiness_score +
        coverage_score +
        quality_score
    )

    return {
        "run_id":                run_id,
        "total_score":           total_score,
        "speed_score":           speed_score,
        "stability_score":       stability_score,
        "flakiness_score":       flakiness_score,
        "coverage_score":        coverage_score,
        "quality_score":         quality_score,
        "pass_rate":             round(pass_rate, 1),
        "avg_duration":          round(avg_duration, 4),
        "flaky_count":           flaky_count,
        "grade":                 get_grade(total_score),
        "flakiness_summary":     flakiness_summary,
        "flaky_tests_details":   flaky_tests_list[:10]  # Top 10 flakiest
    }


def get_grade(score: int) -> str:
    """Convert numeric score to letter grade."""
    if score >= 90:
        return "A"
    elif score >= 75:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"
