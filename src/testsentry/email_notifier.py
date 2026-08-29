import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

EMAIL_FROM     = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO       = os.getenv("EMAIL_TO", EMAIL_FROM)


def send_email_notification(
    run_id: str,
    newly_failing: list,
    fixed: list,
    health_score: dict,
    repo_name: str = "TestSentry",
    to_email: str = None
) -> bool:
    """
    Send email notification with test run summary.
    Called after pytest session finishes.
    """
    recipient = to_email or EMAIL_TO

    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("[TestSentry] ⚠️  EMAIL_FROM or EMAIL_PASSWORD not set — skipping")
        return False

    if not newly_failing and not fixed:
        print("[TestSentry] ℹ️  No changes to notify about")
        return False

    try:
        subject, body = build_email(
            run_id=run_id,
            newly_failing=newly_failing,
            fixed=fixed,
            health_score=health_score,
            repo_name=repo_name
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = recipient


        # Plain text version
        text_part = MIMEText(build_plain_text(
            newly_failing, fixed, health_score, run_id
        ), "plain")

        # HTML version
        html_part = MIMEText(body, "html")

        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"[TestSentry] 📧 Email notification sent to {EMAIL_TO}")
        return True

    except Exception as e:
        print(f"[TestSentry] ⚠️  Email error: {e}")
        return False


def build_email(
    run_id: str,
    newly_failing: list,
    fixed: list,
    health_score: dict,
    repo_name: str
) -> tuple:
    """Build email subject and HTML body."""

    score    = health_score.get("total_score", 0)
    grade    = health_score.get("grade", "?")
    pass_rate = health_score.get("pass_rate", 0)

    if newly_failing:
        subject = f"🔴 TestSentry Alert — {len(newly_failing)} test(s) failing in {repo_name}"
    else:
        subject = f"✅ TestSentry — All issues resolved in {repo_name}"

    # Build HTML body
    failing_rows = ""
    for test in newly_failing:
        short = test["test_name"].split("::")[-1]
        failing_rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">
                <code style="color:#e74c3c;">{short}</code>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;">
                {test.get("owner", "unowned")}
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;">
                <span style="background:#fff0f0;padding:2px 6px;
                border-radius:4px;color:#e74c3c;">
                    {test.get("category", "UNKNOWN")}
                </span>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;
            color:#555;font-size:13px;">
                {test.get("suggested_fix", "Check logs")[:80]}
            </td>
        </tr>"""

    fixed_list = ""
    for test in fixed:
        short = test["test_name"].split("::")[-1]
        fixed_list += f"""
        <li style="color:#27ae60;margin:4px 0;">
            ✅ <code>{short}</code>
        </li>"""

    score_color = "#27ae60" if score >= 80 else "#f39c12" if score >= 60 else "#e74c3c"

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:-apple-system,sans-serif;background:#f5f5f5;
    margin:0;padding:20px;">
        <div style="max-width:700px;margin:0 auto;background:white;
        border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

            <!-- Header -->
            <div style="background:#1a1d27;padding:24px;color:white;">
                <h1 style="margin:0;font-size:22px;">🛡️ TestSentry Health Report</h1>
                <p style="margin:8px 0 0;color:#9ca3af;font-size:14px;">
                    {repo_name} • Run ID: {run_id} •
                    {datetime.now().strftime("%Y-%m-%d %H:%M")}
                </p>
            </div>

            <!-- Health Score -->
            <div style="padding:24px;text-align:center;
            border-bottom:1px solid #eee;">
                <div style="font-size:48px;font-weight:700;
                color:{score_color};">{score}/100</div>
                <div style="color:#666;margin-top:4px;">
                    Grade {grade} • Pass Rate {pass_rate}%
                </div>
            </div>

            <!-- Newly Failing -->
            {"" if not newly_failing else f'''
            <div style="padding:24px;">
                <h2 style="color:#e74c3c;margin:0 0 16px;">
                    🔴 Newly Failing ({len(newly_failing)})
                </h2>
                <table style="width:100%;border-collapse:collapse;
                font-size:14px;">
                    <tr style="background:#f9f9f9;">
                        <th style="padding:8px;text-align:left;">Test</th>
                        <th style="padding:8px;text-align:left;">Owner</th>
                        <th style="padding:8px;text-align:left;">Category</th>
                        <th style="padding:8px;text-align:left;">Fix</th>
                    </tr>
                    {failing_rows}
                </table>
            </div>'''}

            <!-- Fixed -->
            {"" if not fixed else f'''
            <div style="padding:0 24px 24px;">
                <h2 style="color:#27ae60;margin:0 0 12px;">
                    ✅ Fixed ({len(fixed)})
                </h2>
                <ul style="margin:0;padding-left:20px;">
                    {fixed_list}
                </ul>
            </div>'''}

            <!-- Footer -->
            <div style="background:#f9f9f9;padding:16px 24px;
            color:#999;font-size:12px;">
                Generated by TestSentry v2.1 —
                Run <code>testsentry scan</code> for full HTML report
            </div>
        </div>
    </body>
    </html>"""

    return subject, html


def build_plain_text(
    newly_failing: list,
    fixed: list,
    health_score: dict,
    run_id: str
) -> str:
    """Plain text fallback for email clients that don't support HTML."""
    lines = [
        "TestSentry Health Report",
        "=" * 40,
        f"Run ID: {run_id}",
        f"Health Score: {health_score.get('total_score', 0)}/100"
        f" (Grade {health_score.get('grade', '?')})",
        f"Pass Rate: {health_score.get('pass_rate', 0)}%",
        ""
    ]

    if newly_failing:
        lines.append(f"NEWLY FAILING ({len(newly_failing)}):")
        for test in newly_failing:
            lines.append(f"  - {test['test_name']}")
            lines.append(f"    Owner: {test.get('owner', 'unowned')}")
            lines.append(f"    Category: {test.get('category', 'UNKNOWN')}")
            lines.append(f"    Fix: {test.get('suggested_fix', 'Check logs')}")
            lines.append("")

    if fixed:
        lines.append(f"FIXED ({len(fixed)}):")
        for test in fixed:
            lines.append(f"  + {test['test_name']}")

    return "\n".join(lines)