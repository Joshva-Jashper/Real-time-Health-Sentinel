import git
import os
from testsentry.collector import get_connection


def get_file_owners(repo_path: str = ".", max_commits: int = 50) -> dict:
    """
    Return {filename: last_author_email} from git log.
    Walks through recent commits and records the FIRST (most recent)
    author who touched each file.
    """
    try:
        repo = git.Repo(repo_path)
    except git.InvalidGitRepositoryError:
        print("[TestSentry] ⚠️ Not a git repository — skipping ownership mapping")
        return {}

    owners = {}

    try:
        for commit in repo.iter_commits(max_count=max_commits):
            for filepath in commit.stats.files:
                if filepath not in owners:
                    # First (most recent) author wins
                    owners[filepath] = commit.author.email
    except Exception as e:
        print(f"[TestSentry] ⚠️ Error reading git history: {e}")

    return owners


def get_file_change_frequency(repo_path: str = ".", max_commits: int = 50) -> dict:
    """
    Return {filename: change_count} — how many times
    each file was changed in recent commits.
    """
    try:
        repo = git.Repo(repo_path)
    except git.InvalidGitRepositoryError:
        return {}

    change_counts = {}

    try:
        for commit in repo.iter_commits(max_count=max_commits):
            for filepath in commit.stats.files:
                change_counts[filepath] = change_counts.get(filepath, 0) + 1
    except Exception as e:
        print(f"[TestSentry] ⚠️ Error reading git history: {e}")

    return change_counts


def get_at_risk_modules(repo_path: str = ".") -> list:
    """
    Join ownership + change frequency + test failure data
    to build the 'Who Needs to Act' risk table.

    Risk formula:
    - Failures matter MUCH more than churn alone.
    - Pure churn with zero failures = low risk (just the change count).
    - Any failures present = risk jumps significantly, since a file
      that is both frequently changed AND currently failing tests
      is the one a developer needs to act on first.
    """
    owners = get_file_owners(repo_path)
    changes = get_file_change_frequency(repo_path)

    conn = get_connection()
    failure_rows = conn.execute("""
        SELECT test_name, COUNT(*) as failure_count
        FROM test_runs
        WHERE status = 'FAILED'
        GROUP BY test_name
    """).fetchall()
    pass  # shared connection — do not close

   
    file_failures = {}
    for test_name, count in failure_rows:
       
        file_path = test_name.split("::")[0]
        file_failures[file_path] = file_failures.get(file_path, 0) + count

    
    ignored_patterns = [
        ".pyc",
        "__pycache__",
        ".egg-info",
        "testsentry.db",
        ".pytest_cache",
    ]

   
    at_risk = []
    all_files = set(list(changes.keys()) + list(file_failures.keys()))

    for filepath in all_files:
        
        if any(pattern in filepath for pattern in ignored_patterns):
            continue

        change_count = changes.get(filepath, 0)
        failure_count = file_failures.get(filepath, 0)
        owner = owners.get(filepath, "unowned")

        if failure_count > 0:
            risk_score = (change_count * 2) + (failure_count * 10)
        else:
            risk_score = change_count  

        if change_count > 0 or failure_count > 0:
            
            if risk_score >= 20:
                risk_level = "HIGH"
            elif risk_score >= 8:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"

            at_risk.append({
                "filepath":      filepath,
                "owner":         owner,
                "change_count":  change_count,
                "failure_count": failure_count,
                "risk_score":    risk_score,
                "risk_level":    risk_level
            })

    
    at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

    return at_risk[:10]  