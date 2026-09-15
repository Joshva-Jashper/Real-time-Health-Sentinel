# 🛡️ TestSentry v2.1
### Intelligent Test Suite Health Monitor

> *Turn "47 tests failed, good luck" into "here's exactly what broke, why, who needs to fix it, and what it cost to find out."*

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![pytest](https://img.shields.io/badge/pytest-plugin-green?style=flat-square&logo=pytest)
![DuckDB](https://img.shields.io/badge/DuckDB-analytical%20DB-yellow?style=flat-square)
![Groq](https://img.shields.io/badge/Groq-LLM%20triage-purple?style=flat-square)
![Langfuse](https://img.shields.io/badge/Langfuse-observability-orange?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)
![Tests](https://img.shields.io/badge/tests-40%20passing-brightgreen?style=flat-square)
![Coverage](https://img.shields.io/badge/coverage-48%25-yellow?style=flat-square)

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
When a test fails, a fine-tuned AI model (Llama 3.2 3B, trained on 3000 pytest + Playwright + Selenium failure examples) categorizes the failure and suggests the exact fix:

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

---

## 🏗️ Architecture

```
INPUT LAYER              PROCESSING LAYER           OUTPUT LAYER
─────────────────────    ──────────────────────     ──────────────────────
pytest plugin       →    Fingerprinter             →    HTML Health Report
  (live hook)              (SHA-256 hash)                (score + charts)

Git log + authors   →    Triage Cache (DuckDB)     →    GitHub PR Comment
                           (skip known failures)         (NEWLY_FAILING etc)

coverage.py XML     →    AI Triage (Fine-tuned     →    Langfuse Dashboard
                           Llama 3.2 3B via Ollama)      (cost + latency)

CI run logs         →    Regression Detector       →    CLI Commands
  (GitHub Actions)         (NEW/FIXED/STABLE)            (scan/status/risk)
```

---

## 📊 Health Score

TestSentry gives your test suite a score out of 100 across 5 dimensions:

| Dimension | What it measures | Max |
|---|---|---|
| Speed | Average test duration | 20 |
| Stability | Pass rate this run | 20 |
| Flakiness | Tests flipping pass/fail | 20 |
| Coverage | Line coverage % | 20 |
| Quality | Newly failing tests | 20 |

---

## 🧰 CLI Commands

```bash
testsentry scan       # Generate HTML health report
testsentry status     # Show recent test results
testsentry history    # Health score across runs
testsentry flaky      # Flaky test leaderboard
testsentry risk       # Who needs to act table
testsentry coverage   # Code coverage per module
testsentry clear      # Reset database
testsentry version    # Show version
```

---

## 🤖 AI Triage — 4 Failure Categories

| Category | Meaning | Example |
|---|---|---|
| `REAL_BUG` | Actual code defect | `assert result == 4` but returns 3 |
| `FLAKY` | Non-deterministic failure | Network timeout, passes on retry |
| `ENV_ISSUE` | Environment problem | Database not running in CI |
| `DATA_ISSUE` | Test data missing | Expected row not in DB |

### Fingerprint Cache

The same error is **never triaged twice**. Stack traces are normalized (line numbers, memory addresses, timestamps stripped) and SHA-256 hashed. Cache hits return in under 1ms at zero API cost.

```
Run 1  → test_checkout fails → AI called → $0.002
Run 2  → same error         → cache hit  → $0.000
Run 20 → same error         → cache hit  → $0.000
```

In testing: **70% reduction in API calls**, per-run AI cost from $0.020 → $0.006.

---

## 🔬 Fine-Tuned Model

TestSentry uses a **fine-tuned Llama 3.2 3B Instruct** model trained on 3000 labeled failure examples across 29 categories:

```
pytest failures    (11 categories) — AssertionError, TypeError, etc.
Playwright errors  (7 categories)  — Selector, Navigation, Timeout, etc.
Selenium errors    (7 categories)  — StaleElement, NoSuchElement, etc.
E2E / Backend      (4 categories)  — Auth, Database, Network, etc.
```

Fine-tuned using **LoRA** on Google Colab free T4 GPU. Runs locally via Ollama — **zero API cost, fully offline**.

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
| Groq API | LLM backend during development |
| Llama 3.2 3B (fine-tuned) | Final AI model — runs locally |
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

GitHub PR comment shows: `2 NEWLY FAILING | 1 FIXED | 0 REOPENED | 47 STABLE`

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
├── tests/                     # 45 tests; coverage depends on the current run
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
| Fine-tuned local model | ✅ | ❌ | ❌ | ❌ |
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

*TestSentry v2.1 — 7 modules · 45 tests · Fine-tuned AI · GitHub Actions 