"""Safe, local validation for AI-suggested test-only patches.

This module deliberately does not create branches, push commits, or open pull
requests. It validates a candidate unified diff in an isolated temporary copy
and refuses any patch that touches application code or unsafe categories.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

SAFE_REPAIR_CATEGORIES = frozenset({
    "LOCATOR_FAILURE",
    "WAIT_OR_TIMING_FAILURE",
    "TEST_CODE_FAILURE",
    "FLAKY",
})
BLOCKED_REPAIR_CATEGORIES = frozenset({
    "APPLICATION_BUG",
    "REAL_BUG",
    "API_CONTRACT_FAILURE",
    "AUTHENTICATION_FAILURE",
    "ENVIRONMENT_FAILURE",
    "ENV_ISSUE",
    "DATA_ISSUE",
    "UNKNOWN",
})

# Test-only paths. Configuration and application modules are intentionally not
# allowed because a seemingly harmless config change can alter production code.
_TEST_PATH = re.compile(
    r"^(?:tests?/|test_[^/]+\.py$|[^/]+_test\.py$|.*\.(?:spec|e2e)\.(?:js|ts|py)$)",
    re.IGNORECASE,
)


@dataclass
class RepairValidation:
    accepted: bool
    category: str
    reason: str
    failed_test_returncode: int | None = None
    suite_returncode: int | None = None
    changed_files: list[str] = field(default_factory=list)
    workspace: str | None = None
    failed_test_output: str = ""
    suite_output: str = ""


def repair_allowed(category: str) -> bool:
    """Return whether an AI result may be considered for test-only repair."""
    return str(category).upper() in SAFE_REPAIR_CATEGORIES


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[6:].strip())
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            paths.append(line[4:].strip())
    return paths


def validate_patch_scope(patch: str, category: str) -> tuple[bool, str, list[str]]:
    """Validate category and every changed path before touching the filesystem."""
    if not repair_allowed(category):
        return False, f"automatic repair blocked for category {category}", []
    if not patch.strip():
        return False, "candidate patch is empty", []
    if "diff --git" not in patch and "--- " not in patch:
        return False, "candidate must be a unified diff", []
    paths = _patch_paths(patch)
    if not paths:
        return False, "candidate contains no changed files", []
    unsafe = [path for path in paths if path.startswith(("/", "../")) or not _TEST_PATH.match(path)]
    if unsafe:
        return False, "patch touches non-test files: " + ", ".join(unsafe), paths
    return True, "test-only patch scope accepted", paths


def _run(command: Sequence[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(command), cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
            env={**os.environ, "TESTSENTRY_REPAIR_VALIDATION": "1"},
        )
        return proc.returncode, proc.stdout[-20_000:]
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, output + "\ncommand timed out"


def validate_candidate_patch(
    project_dir: str | Path,
    patch: str,
    category: str,
    failed_test: str,
    *,
    related_suite: str | None = None,
    timeout: int = 120,
    keep_workspace: bool = False,
) -> RepairValidation:
    """Apply and validate a candidate patch in a temporary project copy.

    The original project is never modified. Both the failed test and the
    related suite must pass. The candidate is rejected if the resulting git
    diff contains a non-test path or if either command fails.
    """
    source = Path(project_dir).resolve()
    ok, reason, paths = validate_patch_scope(patch, category)
    if not ok:
        return RepairValidation(False, category, reason, changed_files=paths)
    if not source.is_dir():
        return RepairValidation(False, category, "project directory does not exist", changed_files=paths)

    temp_root = Path(tempfile.mkdtemp(prefix="testsentry-repair-"))
    workspace = temp_root / source.name
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns(".git", "testsentry.db", "__pycache__", ".pytest_cache"))
    try:
        patch_file = temp_root / "candidate.patch"
        patch_file.write_text(patch, encoding="utf-8")
        apply = subprocess.run(
            ["git", "apply", "--check", str(patch_file)], cwd=workspace,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if apply.returncode != 0:
            return RepairValidation(False, category, "candidate patch does not apply: " + apply.stdout[-4000:], changed_files=paths)
        applied = subprocess.run(
            ["git", "apply", str(patch_file)], cwd=workspace,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if applied.returncode != 0:
            return RepairValidation(False, category, "candidate patch could not be applied: " + applied.stdout[-4000:], changed_files=paths)

        # The temporary copy deliberately excludes .git. The patch paths were
        # validated before application, so use them as the authoritative diff
        # scope instead of treating Git's "not a repository" message as a file.
        diff_names = list(paths)
        if any(not _TEST_PATH.match(name) for name in diff_names):
            return RepairValidation(False, category, "applied diff contains non-test changes", changed_files=diff_names)

        failed_rc, failed_output = _run(["python", "-m", "pytest", failed_test, "-q"], workspace, timeout)
        if failed_rc != 0:
            return RepairValidation(False, category, "failed test still fails", failed_rc, None, diff_names, str(workspace) if keep_workspace else None, failed_output, "")
        suite_command = related_suite or str(Path(failed_test).parent)
        suite_rc, suite_output = _run(["python", "-m", "pytest", suite_command, "-q"], workspace, timeout)
        accepted = suite_rc == 0
        return RepairValidation(
            accepted, category,
            "candidate passed failed test and related suite" if accepted else "related suite still fails",
            failed_rc, suite_rc, diff_names, str(workspace) if keep_workspace else None,
            failed_output, suite_output,
        )
    finally:
        if not keep_workspace:
            shutil.rmtree(temp_root, ignore_errors=True)


__all__ = ["SAFE_REPAIR_CATEGORIES", "RepairValidation", "repair_allowed", "validate_patch_scope", "validate_candidate_patch"]


if __name__ == "__main__":
    raise SystemExit("Use validate_candidate_patch from Python or the testsentry repair command.")
