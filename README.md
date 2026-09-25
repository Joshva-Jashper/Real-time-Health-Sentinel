# 🛡️ TestSentry v2.1
### Intelligent Test Suite Health Monitor

> *Turn "47 tests failed, good luck" into "here's exactly what broke, why, who needs to fix it, and what it cost to find out."*

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![pytest](https://img.shields.io/badge/pytest-plugin-green?style=flat-square&logo=pytest)
![DuckDB](https://img.shields.io/badge/DuckDB-analytical%20DB-yellow?style=flat-square)
![AI](https://img.shields.io/badge/AI-OpenAI%20%7C%20Ollama-purple?style=flat-square)
![Langfuse](https://img.shields.io/badge/Langfuse-observability-orange?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)
![Tests](https://img.shields.io/badge/tests-79%20passing-brightgreen?style=flat-square)

---

## 📌 The Problem

In any software company, developers run hundreds of automated tests every day. When tests fail, nobody knows:

- **Why** it failed — real bug, flaky test, or environment issue?
- **Whether** it just broke today or has been broken for weeks
- **Who** is responsible for fixing it

Developers waste **2–3 hours** every morning just understanding what went wrong. TestSentry cuts that down to **10 seconds**.

---

## ✨ What TestSentry Does

**1. Monitors every test in real-time**
A custom pytest plugin fires the moment each test finishes and saves results to DuckDB permanently — not just today, but across every CI run forever.

**2. Explains why it failed and how to fix it**
When a test fails, the configured OpenAI-compatible backend (OpenAI or local Ollama) categorizes the failure and suggests a safe next step:

```
❌ test_checkout — FAILED

Category:    ENV_ISSUE (92% confidence)
Why:         Database connection pool exhausted —
             too many parallel CI jobs hitting the same DB
Fix:         Add db.close() in test teardown or set
             pool_size=20 in your database config
```

**3. Tells you who needs to act**
Git history is analyzed to find who last changed each file. Coverage gaps are mapped to responsible developers — the report says exactly who needs to add tests.

---

## 🚀 Quick Start

```bash
# Install
pip install testsentry

# Run your tests — TestSentry activates automatically
pytest tests/

# Generate health report
testsentry scan

# View results
open report.html
```

### Free local AI triage with Ollama

OpenAI is the default hosted backend, but AI triage can run locally without an
OpenAI API key. Install [Ollama](https://ollama.com/download), start it, and
download a coding-capable model:

```bash
ollama pull qwen2.5-coder:7b
```

Create `.env` from `.env.example` or set:

```env
TRIAGE_BACKEND=ollama
OLLAMA_MODEL=qwen2.5-coder:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

TestSentry uses Ollama's OpenAI-compatible local endpoint. No `OPENAI_API_KEY`,
OpenAI billing, GPU, or Python Ollama package is required. CPU-only execution
works, though a GPU can make responses faster. If Ollama is not running or the
model is missing, the test run still completes and AI triage is reported as
unavailable; monitoring, persistence, regression labels, and reports remain
available.

---

## 🏗️ Architecture

```
INPUT LAYER              PROCESSING LAYER           OUTPUT LAYER
─────────────────────    ──────────────────────     ──────────────────────
pytest plugin       →    Fingerprinter             →    HTML Health Report
  (live hook)              (SHA-256 hash)                (score + charts)

Git log + authors   →    Triage Cache (DuckDB)     →    Dashboard + HTML Report
                           (skip known failures)         (dashboard + report)

coverage.py XML     →    AI Triage (OpenAI or       →    Langfuse Dashboard
                           local Ollama)                 (cost + latency)

  CI run logs         →    Regression Detector       →    CLI + Dashboard
  (GitHub Actions)         (NEW/FIXED/STABLE)            (scan/status/risk)
```

---

## 📊 Health Score

TestSentry gives your test suite a score out of 100 across 5 dimensions:

| Dimension | What it measures | Max |
|---|---|---|
| Speed | Average test duration | 20 |
| Stability | Pass rate this run | 20 |
| Flakiness | Repeated pass/fail alternation with environmental evidence | 20 |
| Coverage | Line coverage % | 20 |
| Quality | Newly failing tests | 20 |

---

## 🧰 CLI Commands

```bash
testsentry scan       # Generate HTML health report
testsentry status     # Show recent test results
testsentry history    # Health score across runs
testsentry flaky      # Flaky test leaderboard
testsentry dashboard   # Run the local dashboard on port 8088
testsentry risk       # Who needs to act table
testsentry coverage   # Code coverage per module
testsentry clear      # Reset database
testsentry version    # Show version
```

---

## 🤖 AI Triage — Structured Failure Analysis

| Category | Meaning | Example |
|---|---|---|
| `REAL_BUG` | Actual code defect | `assert result == 4` but returns 3 |
| `FLAKY` | Non-deterministic failure | Repeated environmental timeout and recovery |
| `ENV_ISSUE` | Environment problem | Database not running in CI |
| `DATA_ISSUE` | Test data missing | Expected row not in DB |

The analyzer also supports more specific categories for locator, timing, API
contract, test-code, application, authentication, and unknown failures.

### Fingerprint Cache

The same error is **never triaged twice**. Stack traces are normalized (line numbers, memory addresses, timestamps stripped) and SHA-256 hashed. Cache hits return in under 1ms at zero API cost.

```
Run 1  → test_checkout fails → AI called → $0.002
Run 2  → same error         → cache hit  → $0.000
Run 20 → same error         → cache hit  → $0.000
```

In testing: **70% reduction in API calls**, per-run AI cost from $0.020 → $0.006.

---

## 🔬 AI Backends

TestSentry supports two OpenAI-compatible triage backends. The hosted backend
uses the configured OpenAI API and the local backend uses Ollama, so users can
run triage without OpenAI billing or an API key when Ollama is selected. The
structured analyzer covers pytest, Playwright, Selenium, API, application,
authentication, data, environment, timing, locator, and unknown failures.

---

## 📚 Research Foundation

This project is grounded in two recent papers from top venues:

**[1] FlakyFix** — Fatima et al., *IEEE Transactions on Software Engineering*, 2024
Uses LLMs for predicting fix categories for flaky tests. TestSentry extends this to all 4 failure types with live CI/CD deployment.

**[2] More & Bradbury** — *ICST 2025* (IEEE International Conference on Software Testing)
Fine-tunes LLMs for flaky test classification. TestSentry extends this with structured output, fix suggestions, and a fingerprint cache.

---

## ⚙️ Tech Stack

| Library | Purpose |
|---|---|
| DuckDB | Serverless analytical DB — stores all test history |
| Instructor + Pydantic | Guaranteed structured AI output |
| OpenAI-compatible API | Hosted GPT triage backend |
| Ollama | Optional free local triage backend |
| Langfuse | LLMOps — tracks tokens, cost, cache hits |
| gitpython | Git history reader for ownership mapping |
| coverage.py | Line coverage measurement |
| Jinja2 + matplotlib | HTML report generation |
| Click | CLI framework |
| GitHub Actions | CI/CD automation |

---

## 🔄 Regression Labels

Every test gets labeled on every run:

```
NEWLY_FAILING  — was passing, now failing  ← developer must act NOW
FIXED          — was failing, now passing  ← celebrate
REOPENED       — was fixed, failed again   ← investigate
STILL_FAILING  — ongoing issue
STABLE         — passing consistently
NEW_TEST       — first time seen
```

On a first run, a failed test is both **new** and **newly failing**. The
dashboard therefore intentionally allows these counters to overlap: if 11
tests run for the first time and 8 fail, it shows `New Tests: 11` and
`Newly Failing: 8`. In the Test Results table, those failed rows display both
badges.

TestSentry does not classify every repeated failure as flaky. A flaky result
requires both repeated status alternation (at least two pass/fail transitions)
and environmental or transient evidence such as a timeout, network failure,
browser closure, stale element, rate limit, or resource failure. A plain
`AssertionError`, even when it alternates between pass and fail, remains a
test or application regression rather than an environmental flaky test.

Dashboard and reports show: `NEWLY FAILING | FIXED | REOPENED | STILL FAILING | STABLE | NEW TEST`

---

## 🗂️ Project Structure

```
testsentry/
├── src/testsentry/
│   ├── plugin.py              # pytest hook — captures every test live
│   ├── collector.py           # DuckDB storage layer
│   ├── fingerprinter.py       # SHA-256 stack trace hashing
│   ├── ai_triage.py           # AI failure categorization
│   ├── regression_detector.py # NEW/FIXED/STABLE labeling
│   ├── health_engine.py       # 5-dimension health score
│   ├── ownership_mapper.py    # Git author + coverage gap mapping
│   ├── flakiness_analyzer.py  # Detailed flakiness metrics
│   ├── coverage_analyzer.py   # coverage.py integration
│   ├── report_generator.py    # HTML report with Jinja2
│   └── cli.py                 # Click CLI — 8 commands
├── templates/
│   └── report.html            # Jinja2 report template
├── tests/                     # Automated regression and integration tests
├── scripts/
│   └── generate_dataset.py    # 3000-example dataset generator
├── data/
│   └── training_dataset.json  # Fine-tuning dataset
└── .github/workflows/
    └── testsentry.yml         # GitHub Actions CI/CD
```

---

## 🆚 Why Not BuildPulse or Allure?

| Feature | TestSentry | BuildPulse | Allure | Datadog |
|---|---|---|---|---|
| AI triage + fix suggestions | ✅ | ❌ | ❌ | ❌ |
| Fingerprint cache | ✅ | ❌ | ❌ | ❌ |
| Optional local AI backend | ✅ | ❌ | ❌ | ❌ |
| Ownership mapping | ✅ | ❌ | ❌ | ✅ |
| Regression labels | ✅ | ❌ | ✅ | ✅ |
| Cost tracking | ✅ | ❌ | ❌ | ✅ |
| Free + local | ✅ | ❌ | Partial | ❌ |
| Playwright support | ✅ | ✅ | ✅ | ✅ |

---

## 👥 Done By

| Member | Role |
|---|---|
| Joshva | Core system, AI triage, CLI, CI/CD, Dataset generation, fine-tuning, testing|

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

*TestSentry v2.1 — pytest monitoring · OpenAI/Ollama triage · DuckDB history · GitHub Actions

## Implementation status

### Working today

- Pytest result collection with setup, call, and teardown phase tracking.
- DuckDB persistence for test results, completed-run metadata, triage cache, and AI events.
- Health scoring, regression labels, flakiness analysis, ownership analysis, HTML reports, CLI commands, and dashboard API.
- Optional tiered GPT triage: GPT-5 mini for routine failures and GPT-5 escalation for uncertain or potentially real bugs, with fingerprint-based caching.
- GitHub Actions execution and report artifact generation.
- Specific triage categories for locator, timing, API contract, test-code, application, authentication, environment, flaky, data, and unknown failures.
- Automatic-repair safety gates: only locator, timing, flaky, and test-code categories may enter candidate validation; application, API, authentication, environment, data, and unknown failures remain CI failures.
- Isolated candidate patch validation through `testsentry validate-repair`; it applies a unified diff in a temporary copy, runs the failed test and related suite, and rejects non-test file changes.
- API request-size limits, triage rate limiting, API-key enforcement when configured, CORS support for `X-API-Key`, and sanitized local audit events.
- CI coverage generation, Python 3.11/3.12 matrix testing, browser dependencies, and failure-preserving report generation.

### Safety boundaries and roadmap

The browser-repair roadmap remains intentionally conservative. Candidate validation is implemented locally, but branch creation, pushing, and pull-request creation are not automated. A human must review an accepted candidate before committing or opening a PR. Automatic changes to application logic are not planned; real application bugs must remain failed CI results.

### Phase 1 stabilization

The repository test suite uses an isolated temporary DuckDB database so unit and regression tests do not add synthetic runs to a developer's dashboard database. The dashboard run selector and history use completed run metadata, while test-result views count only pytest call-phase records. The baseline repository suite is expected to pass before later browser and AI-repair phases are added.

### Phase 2 evidence collection

The optional `testsentry.evidence` module now captures sanitized failure bundles without requiring Selenium or Playwright to be installed by every project. A bundle can contain the failure text, browser metadata, DOM/page HTML, relevant interactive elements, screenshots, Playwright traces, and API request/response details. Passwords, tokens, cookies, authorization values, API keys, and sensitive URL query parameters are redacted before evidence is written.

Synchronous Playwright usage:

```python
from testsentry.evidence import create_bundle, capture_playwright

bundle = create_bundle("test-results", "tests/login.spec.py::valid_login")
capture_playwright(bundle, page, locator="get_by_role('button', name='Log in')")
```

Selenium usage:

```python
from testsentry.evidence import create_bundle, capture_selenium

bundle = create_bundle("test-results", "tests/test_login.py::test_valid_login")
capture_selenium(bundle, driver, locator="button#login")
```

The adapters are evidence collectors only. They do not change locators, application code, or test expectations. Candidate repair validation is available separately and is restricted to test-only diffs in a temporary workspace.

### Phase 3 GPT integration

The AI analyzer now uses the OpenAI-compatible GPT-5 catalog. GPT-5 mini handles normal failure triage with strict JSON-schema output. Results with confidence below 80 percent or the `REAL_BUG` category are reviewed by GPT-5 with the preliminary result and sanitized evidence as context. If escalation fails, the validated GPT-5 mini result is retained; if no `OPENAI_API_KEY` is configured, triage is skipped without breaking test execution.

The analyzer includes sanitized DOM, browser metadata, API evidence, locator information, and failure text when available. It never treats a `REAL_BUG` classification as an automatic repair candidate. Cached fingerprints avoid repeating analysis for identical failures.

### Current local operation

The dashboard reads `testsentry.db` from the directory in which it is started.
Run pytest and the dashboard from the same project directory so both processes
use the same history database:

```bash
cd ~/testsentry-demo
pytest tests/ -v
testsentry dashboard
```

Open `http://127.0.0.1:8088`. The dashboard provides Overview, Test Results,
Flakiness Analysis, Risk & Ownership, AI Triage, and History views. Test
Results count only pytest call-phase rows, excluding setup and teardown rows.
If multiple `testsentry.db` files exist, inspect or remove only the database
belonging to the project you are running; databases in other directories are
separate histories.

The local Ollama backend is optional. If Ollama is stopped, the model is
missing, or a triage request fails, the pytest run, result persistence,
regression labels, and dashboard still work; only that AI analysis is marked
unavailable. The `favicon.ico` 404 sometimes printed by the dashboard server
is harmless and does not affect test collection or metrics.
