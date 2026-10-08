"""Keep repository tests isolated from the developer's dashboard database."""

import tempfile
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    # The TestSentry plugin initializes its database during pytest_configure.
    # Move the collector to a fresh temporary database before test collection
    # so unit tests cannot pollute the user's real testsentry.db.
    import testsentry.collector as collector

    temp_dir = Path(tempfile.mkdtemp(prefix="testsentry-pytest-"))
    collector.DB_PATH = str(temp_dir / "testsentry.db")
    collector.CACHE_NAMESPACE = str(temp_dir)

    thread_conn = getattr(collector._thread_local, "conn", None)
    if thread_conn is not None:
        try:
            thread_conn.close()
        except Exception:
            pass
        collector._thread_local.conn = None

    if collector._write_conn is not None:
        try:
            collector._write_conn.close()
        except Exception:
            pass
        collector._write_conn = None

    collector.init_db()

    session.testsentry_test_db = temp_dir
