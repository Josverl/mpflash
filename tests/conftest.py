"""Shared Pytest configuration and fixtures for mpflash tests."""

import sqlite3
import sys
from pathlib import Path

import peewee
import pytest

# ---------------------------------------------------------------------------
HERE = Path(__file__).parent


# ---------------------------------------------------------------------------


@pytest.fixture
def test_fw_path():
    """Return the path to the test firmware folder."""
    return HERE / "data" / "firmware"


# https://docs.pytest.org/en/stable/example/markers.html#marking-platform-specific-tests-with-pytest
ALL_OS = set("win32 linux darwin".split())


def pytest_runtest_setup(item):
    supported_platforms = ALL_OS.intersection(mark.name for mark in item.iter_markers())
    platform = sys.platform
    if supported_platforms and platform not in supported_platforms:
        pytest.skip("cannot run on platform {}".format(platform))


#############################################################
# Fixtures for database testing
#############################################################


@pytest.fixture(scope="session")
def _test_db_path():
    """Canonical path of the reference test database (read-only source)."""
    return HERE / "data/mpflash.db"


@pytest.fixture(scope="module")
def test_db(_test_db_path):
    """Yield the path to the reference test database (for backwards compat)."""
    yield _test_db_path


@pytest.fixture(scope="module")
def db_fx(_test_db_path):
    """In-memory Peewee database pre-populated from the file-based test DB.

    Each test module gets a fresh in-memory copy of the reference test data
    via SQLite's backup API.  All models are rebound to this in-memory
    database so application code uses the correct connection.
    """
    from mpflash.db.models import Board, Firmware, Metadata, database

    # Re-initialise the shared database object to an in-memory instance.
    database.init(":memory:")
    database.connect()

    # Populate from the reference file using SQLite's fast backup API.
    src = sqlite3.connect(str(_test_db_path))
    src.backup(database.connection())
    src.close()

    yield database

    if not database.is_closed():
        database.close()


@pytest.fixture(scope="function")
def session_fx(db_fx):
    """Yield the in-memory database for a single test.

    Since ``db_fx`` provides a fresh copy per module, no rollback is needed.
    Tests in the same module share the same in-memory database and may see
    each other's writes, which is acceptable for the current test suite.
    """
    yield db_fx


# ---------------------------------------------------------------------------
# Empty in-memory database fixtures (for unit tests that don't need data)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_mem():
    """Empty in-memory Peewee database for isolated unit tests."""
    from mpflash.db.models import Board, Firmware, Metadata, database

    mem_db = peewee.SqliteDatabase(":memory:")
    mem_db.bind([Metadata, Board, Firmware])
    mem_db.connect()
    mem_db.create_tables([Metadata, Board, Firmware])
    yield mem_db
    if not mem_db.is_closed():
        mem_db.close()
    # Restore model bindings to the shared module-level database so that
    # subsequent test modules using db_fx/session_fx see the correct DB.
    database.bind([Metadata, Board, Firmware])


@pytest.fixture(scope="function")
def session_mem(db_mem):
    """Yield the empty in-memory database for unit tests."""
    yield db_mem
