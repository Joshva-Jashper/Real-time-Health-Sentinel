from datetime import datetime
from testsentry.ai_triage import langfuse
import pytest
import uuid
from testsentry.collector import init_db, store_result, get_newly_failing_with_triage, get_fixed_tests, store_run_metadata
from testsentry.ai_triage import triage_failure
from testsentry.health_engine import calculate_health_score
from testsentry.regression_detector import label_test
from testsentry.report_generator import generate_report
from testsentry.email_notifier import send_email_notification


RUN_ID = str(uuid.uuid4())[:8]
START_TIME = datetime.now()


def pytest_configure(config):
    """Initialize database when pytest starts."""
    init_db()
    print(f"\n[TestSentry] Run ID: {RUN_ID}")


def pytest_sessionfinish(session, exitstatus):
    """
    Fires after ALL tests finish.
    Calculate health score, record run metadata, and generate HTML report.
    """
    score = calculate_health_score(RUN_ID)
    print(f"\n{'='*50}")
    print(f"[TestSentry] 🏥 HEALTH SCORE: {score['total_score']}/100 (Grade: {score['grade']})")
    print(f"  Speed:      {score['speed_score']}/20")
    print(f"  Stability:  {score['stability_score']}/20")
    print(f"  Flakiness:  {score['flakiness_score']}/20")
    print(f"  Coverage:   {score['coverage_score']}/20")
    print(f"  Quality:    {score['quality_score']}/20")
    print(f"  Pass rate:  {score['pass_rate']}%")
    print(f"  Flaky tests: {score['flaky_count']}")
    print(f"{'='*50}")

    # Record run session metadata
    try:
        passed_cnt = session.testscollected - session.testsfailed if hasattr(session, 'testscollected') else 0
        failed_cnt = getattr(session, 'testsfailed', 0)
        store_run_metadata(
            run_id=RUN_ID,
            started_at=START_TIME,
            finished_at=datetime.now(),
            total=getattr(session, 'testscollected', 0),
            passed=passed_cnt,
            failed=failed_cnt
        )
    except Exception as e:
        print(f"[TestSentry] ⚠️ Metadata error: {e}")

    generate_report(RUN_ID)

    newly_failing = get_newly_failing_with_triage(RUN_ID)
    fixed = get_fixed_tests(RUN_ID)

    if newly_failing or fixed:
        owner_failures = {}
        for test in newly_failing:
            owner = test.get("owner", "unowned")
            if owner == "unowned" or "@" not in owner:
                continue
            if owner not in owner_failures:
                owner_failures[owner] = []
            owner_failures[owner].append(test)

        if owner_failures:
            for owner_email, failures in owner_failures.items():
                send_email_notification(
                    run_id=RUN_ID,
                    newly_failing=failures,
                    fixed=fixed,
                    health_score=score,
                    repo_name="Real-time-Health-Sentinel",
                    to_email=owner_email
                )
        else:
            # Fallback — no git owners found, send to default EMAIL_TO
            if newly_failing or fixed:
                send_email_notification(
                    run_id=RUN_ID,
                    newly_failing=newly_failing,
                    fixed=fixed,
                    health_score=score,
                    repo_name="Real-time-Health-Sentinel"
                )

    langfuse.flush()
    print(f"[TestSentry] 📡 Langfuse traces sent")




@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Fires the moment each test finishes.
    Captures and stores result in DuckDB.
    """
    outcome = yield

    report = outcome.get_result()

    if report.when == "call":
        result = {
            "test_name": item.nodeid,
            "status": "PASSED" if report.passed else "FAILED",
            "duration": round(report.duration, 4),
            "error_msg": str(report.longrepr) if report.failed else None,
        }
        
        label = label_test(result, RUN_ID)
        
        store_result(result, RUN_ID, label)

        label_icon = {
            "NEWLY_FAILING": "🔴",
            "FIXED":         "✅",
            "STILL_FAILING": "⚠️",
            "STABLE":        "✓",
            "NEW_TEST":      "🆕",
            "REOPENED":      "🔁",
        }.get(label, "")

        print(f"\n[TestSentry] {result['status']} {label_icon} {label} — {result['test_name']} ({result['duration']}s)")

        if result["status"] == "FAILED":
            try:
                triage_failure(result)
            except Exception as e:
                print(f"\n[TestSentry] ⚠️ Triage error (skipping): {type(e).__name__}")
 
            