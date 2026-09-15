import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from testsentry.health_engine import calculate_health_score
from testsentry.regression_detector import get_regression_summary
from testsentry.ownership_mapper import get_at_risk_modules
from testsentry.collector import get_connection


def get_ai_stats(run_id: str) -> dict:
    """Return AI triage metrics for this run only."""
    conn = get_connection()
    failures = conn.execute("SELECT COUNT(*) FROM test_runs WHERE run_id = ? AND status = 'FAILED' AND phase = 'call'", [run_id]).fetchone()[0]
    hits, calls = conn.execute("""
        SELECT COALESCE(SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN api_call THEN 1 ELSE 0 END), 0)
        FROM triage_events WHERE run_id = ?
    """, [run_id]).fetchone()
    return {"total_failures": int(failures or 0), "api_calls": int(calls or 0), "cache_hits": int(hits or 0)}


def generate_report(run_id: str, output_path: str = "report.html"):
    """
    Generate the complete HTML health report.
    Combines health score, regression summary,
    ownership mapping, and AI stats.
    """
    health = calculate_health_score(run_id)
    regression = get_regression_summary(run_id)
    
    try:
        at_risk = get_at_risk_modules(".") or []
    except Exception as e:
        print(f"[TestSentry] ⚠️  Could not fetch at-risk modules: {e}")
        at_risk = []

    ai_stats = get_ai_stats(run_id)

    
    template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("report.html")

    html = template.render(
        run_id=run_id,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        health=health,
        regression=regression,
        at_risk=at_risk,
        ai_stats=ai_stats
    )

    # Always write UTF-8: the report contains Unicode status icons and must
    # not depend on the host platform's legacy text encoding (for example,
    # cp1252 on Windows).
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write(html)

    print(f"\n[TestSentry] 📄 Report generated: {output_path}")
    return output_path
