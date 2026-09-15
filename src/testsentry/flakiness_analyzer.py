from testsentry.collector import get_connection
from datetime import datetime, timedelta
from collections import defaultdict


def calculate_flakiness_per_test(test_name: str, window: int = 30, run_id: str = None) -> dict:
    """
    Calculate detailed flakiness metrics for a single test.
    
    Returns:
    {
        'test_name': 'test_login',
        'total_runs': 30,
        'passed': 20,
        'failed': 10,
        'flakiness_pct': 33.33,
        'flakiness_rating': 'HIGH',  # LOW, MEDIUM, HIGH, CRITICAL
        'status_changes': 5,  # How many times it switched PASS <-> FAIL
        'is_flaky': True,
        'trend': 'WORSENING'  # IMPROVING, STABLE, WORSENING
    }
    """
    conn = get_connection()
    
    cutoff = None
    if run_id:
        cutoff_row = conn.execute("SELECT MAX(timestamp) FROM test_runs WHERE run_id = ?", [run_id]).fetchone()
        cutoff = cutoff_row[0] if cutoff_row else None
    query = """
        SELECT status, timestamp FROM test_runs
        WHERE test_name = CAST(? AS VARCHAR)
    """
    params = [str(test_name)]
    if cutoff is not None:
        query += " AND timestamp <= ?"
        params.append(cutoff)
    query += " ORDER BY timestamp ASC, rowid ASC LIMIT ?"
    params.append(int(window))
    rows = conn.execute(query, params).fetchall()
    
    pass  # shared connection — do not close
    
    if not rows:
        return {
            'test_name': test_name,
            'total_runs': 0,
            'passed': 0,
            'failed': 0,
            'flakiness_pct': 0.0,
            'flakiness_rating': 'UNKNOWN',
            'status_changes': 0,
            'is_flaky': False,
            'trend': 'UNKNOWN'
        }
    
    statuses = [row[0] for row in rows]
    total_runs = len(statuses)
    passed = sum(1 for s in statuses if s == 'PASSED')
    failed = sum(1 for s in statuses if s == 'FAILED')
    
    failure_rate = (failed / total_runs * 100) if total_runs > 0 else 0.0
    
    if failure_rate == 0:
        flakiness_rating = 'STABLE'
    elif failure_rate < 10:
        flakiness_rating = 'LOW'
    elif failure_rate < 40:
        flakiness_rating = 'MEDIUM'
    elif failure_rate < 70:
        flakiness_rating = 'HIGH'
    else:
        flakiness_rating = 'CRITICAL'
    
    
    status_changes = 0
    for i in range(len(statuses) - 1):
        if statuses[i] != statuses[i + 1]:
            status_changes += 1
    
    if failure_rate == 0 or failure_rate == 100:
        is_flaky = False
    else:
        is_flaky = status_changes > 0

    
    trend = 'STABLE'
    if total_runs >= 10:
        first_half = statuses[:total_runs // 2]
        second_half = statuses[total_runs // 2:]
        first_fail_rate = sum(1 for s in first_half if s == 'FAILED') / len(first_half)
        second_fail_rate = sum(1 for s in second_half if s == 'FAILED') / len(second_half)
        
        if second_fail_rate > first_fail_rate * 1.2:
            trend = 'WORSENING'
        elif second_fail_rate < first_fail_rate * 0.8:
            trend = 'IMPROVING'
    
    status_change_rate = round((status_changes / max(total_runs - 1, 1)) * 100, 2)
    return {
        'test_name': test_name,
        'total_runs': total_runs,
        'passed': passed,
        'failed': failed,
        'flakiness_pct': status_change_rate,
        'failure_rate': round(failure_rate, 2),
        'status_change_rate': status_change_rate,
        'flakiness_rating': flakiness_rating,
        'status_changes': status_changes,
        'is_flaky': is_flaky,
        'trend': trend
    }


def detect_time_patterns(test_name: str, window: int = 30) -> dict:
    """
    Detect if test failures follow time-based patterns.
    
    Checks:
    - Day of week (Monday failures higher?)
    - Hour of day (late night failures?)
    - Time since test started
    
    Returns:
    {
        'day_patterns': {'Monday': 45%, 'Tuesday': 20%, ...},
        'hour_patterns': {'09': 15%, '18': 50%, ...},
        'worst_time': 'Friday 18:00',
        'has_pattern': True
    }
    """
    conn = get_connection()
    
    cutoff = None
    if run_id:
        cutoff_row = conn.execute("SELECT MAX(timestamp) FROM test_runs WHERE run_id = ?", [run_id]).fetchone()
        cutoff = cutoff_row[0] if cutoff_row else None
    query = """
        SELECT status, timestamp FROM test_runs
        WHERE test_name = CAST(? AS VARCHAR)
    """
    params = [str(test_name)]
    if cutoff is not None:
        query += " AND timestamp <= ?"
        params.append(cutoff)
    query += " ORDER BY timestamp ASC, rowid ASC LIMIT ?"
    params.append(int(window))
    rows = conn.execute(query, params).fetchall()
    
    pass  # shared connection — do not close
    
    if not rows:
        return {'has_pattern': False, 'day_patterns': {}, 'hour_patterns': {}, 'worst_time': None}
    
    day_stats = defaultdict(lambda: {'fail': 0, 'total': 0})
    hour_stats = defaultdict(lambda: {'fail': 0, 'total': 0})
    
    for status, timestamp in rows:
        dt = datetime.fromisoformat(str(timestamp))
        day_name = dt.strftime('%A')
        hour = dt.strftime('%H')
        
        day_stats[day_name]['total'] += 1
        hour_stats[hour]['total'] += 1
        
        if status == 'FAILED':
            day_stats[day_name]['fail'] += 1
            hour_stats[hour]['fail'] += 1
    
    day_patterns = {}
    for day, stats in day_stats.items():
        day_patterns[day] = round(stats['fail'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0
    
    hour_patterns = {}
    for hour, stats in hour_stats.items():
        hour_patterns[hour] = round(stats['fail'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0
    
    worst_time = None
    worst_rate = 0
    if day_patterns:
        worst_day = max(day_patterns, key=day_patterns.get)
        if hour_patterns:
            worst_hour = max(hour_patterns, key=hour_patterns.get)
            worst_time = f"{worst_day} {worst_hour}:00"
            worst_rate = max(day_patterns[worst_day], hour_patterns[worst_hour])
    
    has_pattern = any(rate > 30 for rate in day_patterns.values()) or \
                  any(rate > 30 for rate in hour_patterns.values())
    
    return {
        'day_patterns': day_patterns,
        'hour_patterns': hour_patterns,
        'worst_time': worst_time,
        'worst_rate': worst_rate,
        'has_pattern': has_pattern
    }


def detect_error_patterns(test_name: str, window: int = 30) -> dict:
    """
    Analyze error messages to detect root causes of flakiness.
    
    Looks for:
    - Race conditions ("race", "concurrent", "lock", "deadlock")
    - Timeouts ("timeout", "timed out")
    - Environmental issues ("connection", "database", "network")
    - Timing/Sleep issues ("sleep", "wait", "delay")
    
    Returns:
    {
        'common_errors': ['TimeoutError', 'ConnectionError', ...],
        'likely_causes': ['Race Condition', 'Network Issue', ...],
        'error_count': 5,
        'top_error': 'TimeoutError'
    }
    """
    conn = get_connection()
    
    rows = conn.execute("""
        SELECT error_msg, status
        FROM test_runs
        WHERE test_name = CAST(? AS VARCHAR) AND status = 'FAILED'
        ORDER BY timestamp ASC
        LIMIT ?
    """, [str(test_name), int(window)]).fetchall()
    
    pass  # shared connection — do not close
    
    error_keywords = {
        'race_condition': ['race', 'concurrent', 'lock', 'deadlock', 'race condition'],
        'timeout': ['timeout', 'timed out', 'time out'],
        'network': ['connection', 'network', 'socket', 'refused', 'unreachable'],
        'database': ['database', 'sql', 'query', 'schema', 'transaction'],
        'timing': ['sleep', 'wait', 'delay', 'timing'],
        'memory': ['memory', 'out of memory', 'oom', 'segfault']
    }
    
    cause_counts = defaultdict(int)
    error_types = defaultdict(int)
    
    for error_msg, _ in rows:
        if not error_msg:
            continue
        
        error_lower = error_msg.lower()
        
        
        error_parts = error_msg.split(':')[0].strip().split()[-1]
        error_types[error_parts] += 1
        
       
        for cause, keywords in error_keywords.items():
            if any(kw in error_lower for kw in keywords):
                cause_counts[cause] += 1
    
    
    likely_causes = {
        'race_condition': 'Race Condition',
        'timeout': 'Timeout',
        'network': 'Network Issue',
        'database': 'Database Issue',
        'timing': 'Timing Sensitivity',
        'memory': 'Memory Issue'
    }
    
    detected_causes = []
    for cause, count in sorted(cause_counts.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            detected_causes.append(likely_causes[cause])
    
    top_error = max(error_types, key=error_types.get) if error_types else 'Unknown'
    
    return {
        'common_errors': list(dict(sorted(error_types.items(), key=lambda x: x[1], reverse=True)).keys()),
        'likely_causes': detected_causes,
        'error_count': len(rows),
        'top_error': top_error
    }


def get_all_flaky_tests(run_id: str = None) -> list:
    """
    Get list of all flaky tests across the entire test suite or a specific run.
    Returns sorted by flakiness percentage (worst first).
    """
    conn = get_connection()
    
   
    if run_id:
        tests = conn.execute("""
            SELECT DISTINCT test_name
            FROM test_runs
            WHERE run_id = ?
            ORDER BY test_name
        """, [run_id]).fetchall()
    else:
        tests = conn.execute("""
            SELECT DISTINCT test_name
            FROM test_runs
            ORDER BY test_name
        """).fetchall()
    
    pass  # shared connection — do not close
    
    flaky_list = []
    for row in tests:
        test_name = row[0]
        metrics = calculate_flakiness_per_test(test_name, run_id=run_id)
        if metrics['is_flaky']:
            flaky_list.append(metrics)
    
    
    flaky_list.sort(key=lambda x: x['flakiness_pct'], reverse=True)
    
    return flaky_list


def get_flakiness_summary(run_id: str = None) -> dict:
    """
    Get overall flakiness summary for dashboard.
    
    Returns:
    {
        'total_flaky_tests': 5,
        'critical_flaky': 2,  # >70% failure rate
        'high_flaky': 1,      # 40-70%
        'medium_flaky': 2,    # 10-40%
        'avg_flakiness': 35.5,
        'worst_test': 'test_payment',
        'worst_rate': 85.5
    }
    """
    flaky_tests = get_all_flaky_tests(run_id)
    
    total_flaky = len([t for t in flaky_tests if t['is_flaky']])
    critical = len([t for t in flaky_tests if t['flakiness_pct'] >= 70])
    high = len([t for t in flaky_tests if 40 <= t['flakiness_pct'] < 70])
    medium = len([t for t in flaky_tests if 10 <= t['flakiness_pct'] < 40])
    
    avg_flakiness = sum(t['flakiness_pct'] for t in flaky_tests) / len(flaky_tests) if flaky_tests else 0
    
    worst_test = flaky_tests[0] if flaky_tests else None
    worst_rate = worst_test['flakiness_pct'] if worst_test else 0
    worst_name = worst_test['test_name'] if worst_test else None
    
    return {
        'total_flaky_tests': total_flaky,
        'critical_flaky': critical,
        'high_flaky': high,
        'medium_flaky': medium,
        'avg_flakiness': round(avg_flakiness, 2),
        'worst_test': worst_name,
        'worst_rate': round(worst_rate, 2)
    }
