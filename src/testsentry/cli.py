import click
from testsentry.collector import get_connection


@click.group()
def cli():
    """🛡️ TestSentry — Intelligent Test Suite Health Monitor"""
    pass


@cli.command()
@click.option('--output', default='report.html', help='Output file path')
@click.option('--runs', default=30, help='Number of recent runs to analyze')
def scan(output, runs):
    """Generate a TestSentry health report."""
    click.echo("[TestSentry] 🔍 Scanning test history...")

    conn = get_connection()
    row = conn.execute("""
        SELECT run_id FROM test_runs
        ORDER BY timestamp DESC
        LIMIT 1
    """).fetchone()
    pass  # shared connection — do not close

    if not row:
        click.echo("[TestSentry] ⚠️  No runs found. Run pytest first.")
        return

    run_id = row[0]
    click.echo(f"[TestSentry] 📊 Analyzing run: {run_id}")

    from testsentry.report_generator import generate_report
    generate_report(run_id, output)
    click.echo(f"[TestSentry] ✅ Report saved to {output}")


@cli.command()
@click.option('--runs', default=5, help='Number of recent runs to show')
def status(runs):
    """Show recent test run results."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT test_name, status, duration, label, timestamp
        FROM test_runs
        ORDER BY timestamp DESC
        LIMIT ?
    """, [runs]).fetchall()
    pass  # shared connection — do not close

    if not rows:
        click.echo("[TestSentry] ⚠️  No test runs found. Run pytest first.")
        return

    click.echo(f"\n{'Test Name':<55} {'Status':<10} {'Label':<15} {'Duration'}")
    click.echo("─" * 100)
    for row in rows:
        test_name, status, duration, label, timestamp = row
        # Shorten test name if too long
        short_name = test_name[-52:] if len(test_name) > 52 else test_name
        status_icon = "✅" if status == "PASSED" else "❌"
        click.echo(f"{short_name:<55} {status_icon} {status:<8} {label:<15} {duration:.4f}s")


@cli.command()
def flaky():
    """Show flaky test leaderboard ranked by flip rate."""
    from testsentry.flakiness_analyzer import get_all_flaky_tests, get_flakiness_summary

    click.echo("\n🔴 FLAKY TEST LEADERBOARD")
    click.echo("─" * 70)

    summary = get_flakiness_summary()
    click.echo(f"Total flaky: {summary['total_flaky_tests']} | "
               f"Critical: {summary['critical_flaky']} | "
               f"High: {summary['high_flaky']} | "
               f"Medium: {summary['medium_flaky']}")
    click.echo("─" * 70)

    flaky_tests = get_all_flaky_tests()

    if not flaky_tests:
        click.echo("✅ No flaky tests detected!")
        return

    click.echo(f"\n{'Test Name':<50} {'Flip%':<8} {'Rating':<10} {'Trend'}")
    click.echo("─" * 85)

    for test in flaky_tests[:10]:
        short_name = test['test_name'][-47:] if len(test['test_name']) > 47 else test['test_name']
        rating = test['flakiness_rating']
        icon = "🔴" if rating == "CRITICAL" else "🟠" if rating == "HIGH" else "🟡" if rating == "MEDIUM" else "🟢"
        click.echo(f"{short_name:<50} {test['flakiness_pct']:<8.1f} {icon} {rating:<8} {test['trend']}")


@cli.command()
def history():
    """Show health score history across recent runs."""
    from testsentry.health_engine import calculate_health_score

    conn = get_connection()
    runs = conn.execute("""
        SELECT DISTINCT run_id, MIN(timestamp) as started
        FROM test_runs
        GROUP BY run_id
        ORDER BY started DESC
        LIMIT 10
    """).fetchall()
    pass  # shared connection — do not close

    if not runs:
        click.echo("[TestSentry] ⚠️  No runs found. Run pytest first.")
        return

    click.echo(f"\n{'Run ID':<12} {'Score':<10} {'Grade':<8} {'Pass%':<8} {'Flaky':<8} {'Time'}")
    click.echo("─" * 65)

    for run_id, started in runs:
        score = calculate_health_score(run_id)
        grade = score['grade']
        grade_icon = "🟢" if grade == "A" else "🔵" if grade == "B" else "🟡" if grade == "C" else "🔴"
        click.echo(
            f"{run_id:<12} "
            f"{score['total_score']}/100   "
            f"{grade_icon} {grade:<6} "
            f"{score['pass_rate']:<8} "
            f"{score['flaky_count']:<8} "
            f"{str(started)[:16]}"
        )


@cli.command()
def risk():
    """Show who needs to act — file risk table with owners."""
    from testsentry.ownership_mapper import get_at_risk_modules

    click.echo("\n⚠️  WHO NEEDS TO ACT")
    click.echo("─" * 85)

    at_risk = get_at_risk_modules(".")

    if not at_risk:
        click.echo("✅ No high-risk modules detected!")
        return

    click.echo(f"\n{'File':<40} {'Owner':<30} {'Changes':<10} {'Failures':<10} {'Risk'}")
    click.echo("─" * 100)

    for item in at_risk:
        filepath = item['filepath'][-37:] if len(item['filepath']) > 37 else item['filepath']
        owner = item['owner'][-27:] if len(item['owner']) > 27 else item['owner']
        level = item['risk_level']
        icon = "🔴" if level == "HIGH" else "🟡" if level == "MEDIUM" else "🟢"
        click.echo(
            f"{filepath:<40} "
            f"{owner:<30} "
            f"{item['change_count']:<10} "
            f"{item['failure_count']:<10} "
            f"{icon} {level}"
        )


@cli.command()
def clear():
    """Clear the TestSentry database and start fresh."""
    import os
    db_path = os.path.join(os.getcwd(), "testsentry.db")

    if not os.path.exists(db_path):
        click.echo("[TestSentry] No database found.")
        return

    confirm = click.confirm("⚠️  This will delete all test history. Are you sure?")
    if confirm:
        os.remove(db_path)
        click.echo("[TestSentry] ✅ Database cleared. Run pytest to start fresh.")
    else:
        click.echo("[TestSentry] Cancelled.")


@cli.command()
def version():
    """Show TestSentry version."""
    click.echo("TestSentry v2.1.0")
    click.echo("Intelligent Test Suite Health Monitor")
    click.echo("Built at Sri Shakthi Institute of Engineering and Technology")

@cli.command()
def coverage():
    """Show code coverage report per module."""
    from testsentry.coverage_analyzer import get_coverage_summary

    summary = get_coverage_summary()

    if not summary["files"]:
        click.echo("[TestSentry] ⚠️  No coverage data found.")
        click.echo("             Run: pytest --cov=src/testsentry tests/")
        return

    click.echo(f"\n📊 CODE COVERAGE REPORT")
    click.echo(f"Overall: {summary['total_pct']}%")
    click.echo("─" * 70)
    click.echo(f"\n{'File':<45} {'Covered':<10} {'Missing':<10} {'%'}")
    click.echo("─" * 70)

    # Sort by coverage % ascending (worst first)
    files = sorted(summary["files"].items(),
                   key=lambda x: x[1]["pct"])

    for filepath, data in files:
        short = filepath[-42:] if len(filepath) > 42 else filepath
        icon = "🟢" if data["pct"] >= 80 else "🟡" if data["pct"] >= 50 else "🔴"
        click.echo(
            f"{short:<45} "
            f"{data['covered']:<10} "
            f"{data['missing']:<10} "
            f"{icon} {data['pct']}%"
        )    



def _free_port_if_in_use(port: int):
    """Check if port is in use and auto-kill stale processes on that port."""
    import os
    import signal
    import subprocess

    current_pid = str(os.getpid())
    # Try fuser -k first
    try:
        subprocess.run(f"fuser -k {port}/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    # Backup check with lsof
    try:
        output = subprocess.check_output(f"lsof -t -i:{port}", shell=True, text=True).strip()
        if output:
            for pid in output.split():
                if pid != current_pid:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except Exception:
                        pass
    except Exception:
        pass



@cli.command()
@click.option('--port', default=8088, help='Port to run the dashboard on')
@click.option('--host', default='0.0.0.0', help='Host to bind to')
def dashboard(port, host):
    """Launch the TestSentry web dashboard (FastAPI + beautiful UI)."""
    import signal
    import sys

    # Handle Ctrl+Z (SIGTSTP) to terminate cleanly instead of suspending process
    def _on_signal_exit(signum, frame):
        click.echo("\n[TestSentry] 🛑 Shutdown signal received. Terminating dashboard process...")
        sys.exit(0)

    for sig in [signal.SIGINT, signal.SIGTERM]:
        try:
            signal.signal(sig, _on_signal_exit)
        except Exception:
            pass

    if hasattr(signal, 'SIGTSTP'):
        try:
            signal.signal(signal.SIGTSTP, _on_signal_exit)
        except Exception:
            pass

    # Auto-kill any stale process holding the port before starting
    _free_port_if_in_use(port)

    try:
        import uvicorn
    except ImportError:
        click.echo("[TestSentry] ⚠️  uvicorn not installed. Run: pip install uvicorn fastapi")
        return

    click.echo(f"[TestSentry] 🚀 Starting dashboard at http://{host}:{port}")
    click.echo(f"[TestSentry] 🌐 Open http://localhost:{port} in your browser")
    click.echo(f"[TestSentry] 🤖 AI model: qwen2.5-coder:7b via Ollama")
    click.echo(f"[TestSentry] Press Ctrl+C or Ctrl+Z to exit cleanly")
    try:
        uvicorn.run("testsentry.api:app", host=host, port=port, reload=False)
    except OSError as e:
        if getattr(e, 'errno', None) == 98 or "address already in use" in str(e).lower():
            # Retry auto-clear once
            _free_port_if_in_use(port)
            try:
                uvicorn.run("testsentry.api:app", host=host, port=port, reload=False)
                return
            except Exception:
                pass
            click.echo(f"\n[TestSentry] ⚠️  Port {port} is already in use by another application.")
            click.echo(f"[TestSentry] 💡 Open http://localhost:{port} in your browser, or run on a different port:")
            click.echo(f"             testsentry dashboard --port {port + 1}")
        else:
            raise




def main():
    cli()