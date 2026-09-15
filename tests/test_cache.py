from testsentry.collector import cache_lookup, cache_store, init_db


SAMPLE_TRIAGE = {
    "category":        "ENV_ISSUE",
    "confidence_pct":  92,
    "why_it_failed":   "Database connection refused",
    "suggested_fix":   "Start PostgreSQL before running tests",
    "affected_module": "tests/test_db.py"
}

SAMPLE_FINGERPRINT = "abc123def456abcd"


def test_cache_miss_returns_none():
    """Cache should return None for unknown fingerprint."""
    result = cache_lookup("nonexistent_fingerprint_xyz")
    assert result is None


def test_cache_store_and_lookup():
    """Store a result then look it up — should return it."""
    cache_store(SAMPLE_FINGERPRINT, SAMPLE_TRIAGE)
    result = cache_lookup(SAMPLE_FINGERPRINT)

    assert result is not None
    assert result["category"] == "ENV_ISSUE"
    assert result["confidence_pct"] == 92
    assert result["cache_hit"] == True


def test_cache_hit_count_increments():
    """Hit count should go up every time cache is hit."""
    from testsentry.collector import get_connection, cache_key

    # Look up twice
    cache_lookup(SAMPLE_FINGERPRINT)
    cache_lookup(SAMPLE_FINGERPRINT)

    conn = get_connection()
    row = conn.execute("""
        SELECT hit_count FROM triage_cache
        WHERE fingerprint = ?
    """, [cache_key(SAMPLE_FINGERPRINT)]).fetchone()
    # Do NOT close — this is a shared thread-local connection managed by collector

    assert row[0] >= 2


def test_different_fingerprints_stored_separately():
    """Two different fingerprints should be stored independently."""
    triage_2 = {**SAMPLE_TRIAGE, "category": "REAL_BUG"}

    cache_store("fingerprint_aaa", SAMPLE_TRIAGE)
    cache_store("fingerprint_bbb", triage_2)

    result_a = cache_lookup("fingerprint_aaa")
    result_b = cache_lookup("fingerprint_bbb")

    assert result_a["category"] == "ENV_ISSUE"
    assert result_b["category"] == "REAL_BUG"
