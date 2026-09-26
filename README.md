# TestSentry

### Intelligent Test Suite Health Monitoring for Pytest, Playwright, and Selenium

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Pytest](https://img.shields.io/badge/Pytest-plugin-0A9EDC?style=flat-square&logo=pytest&logoColor=white)](https://pytest.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-history%20store-FFF000?style=flat-square&logo=duckdb&logoColor=black)](https://duckdb.org/)
[![AI](https://img.shields.io/badge/AI-OpenAI%20%7C%20Ollama-6E40C9?style=flat-square)](https://ollama.com/)
[![License](https://img.shields.io/badge/license-MIT-6B7280?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-79%20passing-16A34A?style=flat-square)](tests/)

> TestSentry turns a failing test run into an actionable engineering report: what failed, whether it is a regression or a genuine flaky test, what evidence was captured, and what should be investigated next.

---

## Overview

TestSentry is a local-first test observability and failure-analysis platform. It installs as a pytest plugin, records test history in DuckDB, compares results across runs, captures browser evidence when available, and presents the results through a CLI, HTML reports, and a FastAPI dashboard.

The project is designed to answer four practical questions:

1. **What failed?** — test name, phase, duration, error, and evidence.
2. **Is it new or recurring?** — regression labels and historical comparison.
3. **Is it actually flaky?** — repeated status alternation plus transient/environmental evidence.
4. **What should the team investigate?** — structured AI triage, ownership, risk, and safe repair validation.

## Key capabilities

- Automatic pytest result collection through a plugin.
- Persistent run history in a local DuckDB database.
- Regression labels: `NEW_TEST`, `NEWLY_FAILING`, `FIXED`, `REOPENED`, `STILL_FAILING`, and `STABLE`.
- Strict flakiness detection based on repeated pass/fail transitions and environmental evidence.
- OpenAI GPT triage or local Ollama triage with structured JSON output.
- Fingerprint-based triage caching for repeated failures.
- Playwright and Selenium evidence capture, including DOM/page HTML and screenshots.
- Sanitization of passwords, tokens, cookies, authorization values, API keys, and sensitive URL parameters.
- Health scoring across speed, stability, flakiness, coverage, and quality.
- Interactive dashboard and generated HTML reports.
- Risk and ownership analysis based on repository history.
- Isolated, test-only candidate repair validation with safety gates.
- GitHub Actions CI with coverage and browser support.

---

## Architecture

```text
                         ┌──────────────────────────┐
                         │       Test execution     │
                         │  Pytest / Playwright /   │
                         │        Selenium          │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │      Pytest plugin        │
                         │ Result + phase capture   │
                         └────────────┬─────────────┘
                                      │
                 ┌────────────────────┼────────────────────┐
                 ▼                    ▼                    ▼
       ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
       │ DuckDB history  │  │ Evidence bundles│  │ Error fingerprints│
       │ runs + results  │  │ DOM + screenshots│  │ SHA-256 cache    │
       └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
                └───────────────────┼───────────────────┘
                                    ▼
                         ┌──────────────────────────┐
                         │ Regression + flakiness   │
                         │ Health score + AI triage │
                         └────────────┬─────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
             HTML report        FastAPI dashboard     CLI / CI
```

---

## Installation

### From the repository

```bash
git clone https://github.com/Joshva-Jashper/Real-time-Health-Sentinel.git
cd Real-time-Health-Sentinel
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

TestSentry requires Python 3.10 or newer. Playwright and Selenium are optional; install them only for the browser workflows used by your project.

```bash
pip install playwright selenium
playwright install
```

### Verify the installation

```bash
testsentry version
pytest --help | grep testsentry
```

---

## Run a test suite

TestSentry activates automatically when the package is installed as a pytest plugin:

```bash
pytest tests/ -v
```

The run stores results in `testsentry.db` in the **current working directory**. Run pytest and the dashboard from the same project directory so they use the same database:

```bash
cd ~/testsentry-demo
pytest tests/ -v
testsentry dashboard
```

Open the dashboard at [http://127.0.0.1:8088](http://127.0.0.1:8088).

> If you have multiple `testsentry.db` files, each file belongs to the directory from which TestSentry was run. They are separate histories.

---

## AI triage backends

TestSentry supports two backends. AI triage is optional: test execution, result persistence, regression labels, reports, and the dashboard continue working if the selected model is unavailable.

### Option A: OpenAI GPT

Create a `.env` file in the directory where you run TestSentry:

```env
TRIAGE_BACKEND=openai
OPENAI_API_KEY=your_openai_api_key
```

The OpenAI-compatible client uses GPT-5 mini for routine triage and can escalate uncertain or potentially serious failures to GPT-5. Do not commit `.env` or expose your API key in source code.

### Option B: Local Ollama

Install [Ollama](https://ollama.com/download), start the Ollama service, and download a coding model:

```bash
ollama pull qwen2.5-coder:7b
```

Configure TestSentry:

```env
TRIAGE_BACKEND=ollama
OLLAMA_MODEL=qwen2.5-coder:7b
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

No OpenAI API key, OpenAI billing, or Python Ollama package is required. CPU-only execution works, although a GPU can improve response time.

---

## Failure categories

AI triage returns structured results with a category, confidence, explanation, suggested fix, and affected module.

| Category | Meaning |
|---|---|
| `LOCATOR_FAILURE` | A selector or locator no longer identifies the intended UI element. |
| `WAIT_OR_TIMING_FAILURE` | A synchronization, timeout, race, or ordering problem. |
| `API_CONTRACT_FAILURE` | The service response, status, or schema violates the expected contract. |
| `TEST_CODE_FAILURE` | The test, assertion, fixture, or setup is incorrect. |
| `APPLICATION_BUG` | Application or service behavior is incorrect. |
| `AUTHENTICATION_FAILURE` | Login, permission, credential, or security behavior failed. |
| `ENVIRONMENT_FAILURE` | Browser, driver, network, CI, dependency, or infrastructure problem. |
| `FLAKY` | Nondeterministic timing, ordering, race, or intermittent behavior. |
| `DATA_ISSUE` | Invalid, missing, stale, or conflicting test data. |
| `UNKNOWN` | The available evidence is insufficient. |

Application, API, authentication, environment, data, and unknown failures are not automatic repair candidates. They remain visible CI failures for human investigation.

---

## Regression labels and first-run behavior

Every call-phase test result receives a historical label:

| Label | Meaning |
|---|---|
| `NEW_TEST` | The test is being observed for the first time. |
| `NEWLY_FAILING` | A previously passing test is now failing. |
| `FIXED` | A previously failing test is now passing. |
| `REOPENED` | A previously fixed test has failed again. |
| `STILL_FAILING` | The test continues to fail. |
| `STABLE` | The test continues to pass. |

First-run counters intentionally overlap. For example, if 11 tests are executed for the first time and 8 fail:

```text
New Tests:       11
Newly Failing:    8
```

The eight failed rows are both new and newly failing. The Test Results table displays both badges for those rows.

---

## Flakiness rules

A test is not classified as flaky merely because it failed once or because its result changed once.

A test is classified as flaky only when all of the following are true:

1. It has at least three real call-phase executions.
2. It contains both passed and failed results.
3. It has at least two pass/fail transitions, such as `PASS → FAIL → PASS`.
4. At least one failure contains environmental or transient evidence.

Examples of environmental evidence include timeouts, network failures, DNS errors, refused connections, browser/page closure, stale elements, detached DOM elements, WebDriver errors, rate limits, deadlocks, and resource failures.

A plain `AssertionError` or deterministic application mismatch is treated as a regression, even if the test alternates between pass and fail.

---

## Evidence collection

When browser objects are available, TestSentry can collect sanitized failure evidence for Playwright and Selenium tests:

- Failure text and stack trace.
- Browser URL and page title.
- DOM/page HTML.
- Relevant interactive elements.
- Screenshots.
- Locator information.
- Browser and driver metadata.
- Playwright trace information.
- API request and response details when supplied.

Example Playwright usage:

```python
from testsentry.evidence import capture_playwright, create_bundle

bundle = create_bundle("test-results", "tests/test_login.py::test_valid_login")
capture_playwright(
    bundle,
    page,
    locator="get_by_role('button', name='Log in')",
)
```

Example Selenium usage:

```python
from testsentry.evidence import capture_selenium, create_bundle

bundle = create_bundle("test-results", "tests/test_login.py::test_valid_login")
capture_selenium(bundle, driver, locator="button#login")
```

Evidence collection is failure-safe. If a browser adapter is unavailable or a capture operation fails, the test result and failure message are still stored.

### Redaction

Before evidence is written or passed to AI, TestSentry redacts sensitive values including passwords, tokens, cookies, authorization headers, API keys, and sensitive URL query parameters.

---

## Health score

The health score is calculated out of 100:

| Dimension | Maximum | Measures |
|---|---:|---|
| Speed | 20 | Average test duration. |
| Stability | 20 | Pass rate for the selected run. |
| Flakiness | 20 | Strictly classified flaky tests. |
| Coverage | 20 | Available line-coverage results. |
| Quality | 20 | Newly failing and regression signals. |

The Overview and Flakiness pages use the same flakiness classifier so their counts remain consistent.

---

## Dashboard

Start the local dashboard:

```bash
testsentry dashboard
```

Default URL:

```text
http://127.0.0.1:8088
```

The dashboard includes:

- **Overview** — health score, pass rate, duration, flaky count, regression summary, and AI statistics.
- **Test Results** — every pytest call-phase result, status, label, error, and triage action.
- **Flakiness Analysis** — flaky-test leaderboard, transition counts, failure rate, rating, and trend.
- **Risk & Ownership** — ownership and change-frequency analysis when run inside a Git repository.
- **AI Triage** — cached analyses, explanations, suggested fixes, and affected modules.
- **History** — health scores and run summaries across completed sessions.

The `favicon.ico 404` message sometimes printed by the server is harmless and does not affect test execution or dashboard metrics.

---

## CLI reference

```bash
testsentry scan       # Generate an HTML health report
testsentry status     # Show recent test results
testsentry history    # Show health scores across runs
testsentry flaky      # Show the flaky-test leaderboard
testsentry dashboard  # Start the local FastAPI dashboard
testsentry risk       # Show ownership and risk information
testsentry coverage   # Show coverage by module
testsentry clear      # Clear the local database
testsentry version    # Print the installed version
testsentry validate-repair  # Validate a safe test-only candidate patch
```

---

## Safe repair validation

TestSentry does not automatically modify application code or push changes. The repair workflow is deliberately conservative:

- Candidate patches are applied in an isolated temporary copy.
- Only permitted test-side categories can enter candidate validation.
- Non-test file changes are rejected.
- The failed test and related suite can be rerun for validation.
- Application, API, authentication, environment, data, and unknown failures remain CI failures.
- A human must review any accepted candidate before committing or opening a pull request.

---

## Database and privacy

The default database file is:

```text
testsentry.db
```

It is created relative to the current working directory. This makes each project directory independent, but it also means that running pytest and the dashboard from different directories can produce apparently missing history.

To inspect database locations:

```bash
find ~ -name testsentry.db -print
```

Do not delete a database unless you intend to remove that directory's test history. Runtime audit logs and generated coverage artifacts are ignored by the repository configuration.

---

## CI/CD

The GitHub Actions workflow runs the automated suite and supports:

- Python 3.11 and 3.12.
- Dependency installation from the project requirements.
- Coverage generation.
- Optional browser dependencies.
- Failure-preserving report generation.

Run the local equivalent:

```bash
python -m pytest tests/ -q
```

The current repository suite contains **79 passing tests** with one non-blocking dependency warning in the verified environment.

---

## Project structure

```text
.
├── src/testsentry/
│   ├── ai_triage.py              # OpenAI/Ollama structured failure analysis
│   ├── api.py                    # FastAPI dashboard backend
│   ├── cli.py                    # Click command-line interface
│   ├── collector.py              # DuckDB persistence and migrations
│   ├── coverage_analyzer.py      # Coverage integration
│   ├── evidence.py               # Playwright/Selenium/API evidence capture
│   ├── fingerprinter.py          # Normalized SHA-256 error fingerprints
│   ├── flakiness_analyzer.py     # Strict flaky-test classification
│   ├── health_engine.py          # Five-dimension health score
│   ├── ownership_mapper.py       # Git ownership and risk analysis
│   ├── plugin.py                 # Pytest hooks
│   ├── regression_detector.py    # Historical result labels
│   ├── repair.py                 # Safe isolated patch validation
│   └── report_generator.py       # HTML report generation
├── dashboard/                    # Dashboard HTML, CSS, and JavaScript
├── templates/                    # HTML report templates
├── tests/                        # Unit, integration, safety, and regression tests
├── .github/workflows/            # GitHub Actions workflow
├── requirements.txt              # Direct dependencies
├── requirements-lock.txt         # Pinned dependency versions
└── pyproject.toml                # Package and pytest-plugin configuration
```

---

## Limitations and safety notes

- AI output is an analysis aid, not a replacement for engineering review.
- OpenAI triage requires a valid API key and may incur provider charges.
- Ollama requires a running local model and sufficient system resources.
- Ownership mapping requires running from a Git repository with accessible history.
- Browser evidence depends on the browser framework and objects being available.
- Automatic application-code repair is intentionally not supported.

---

## License

This project is released under the [MIT License](LICENSE).

## Author

**Joshva-Jashper**
**Mantraa**

Repository: [github.com/Joshva-Jashper/Real-time-Health-Sentinel](https://github.com/Joshva-Jashper/Real-time-Health-Sentinel)
