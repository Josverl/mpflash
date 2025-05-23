"""Shared Pytest configuration and fixtures for mpflash tests."""

import sys
from pathlib import Path

import pytest


@pytest.fixture
def test_fw_path():
    """Return the path to the test firmware folder."""
    return Path(__file__).parent / "data" / "firmware"


# --------------------------------------
# https://docs.pytest.org/en/stable/example/markers.html#marking-platform-specific-tests-with-pytest
ALL_OS = set("win32 linux darwin".split())


def pytest_runtest_setup(item):
    supported_platforms = ALL_OS.intersection(mark.name for mark in item.iter_markers())
    platform = sys.platform
    if supported_platforms and platform not in supported_platforms:
        pytest.skip("cannot run on platform {}".format(platform))


from pathlib import Path

import pytest

# Constants for test
HERE = Path(__file__).parent

#############################################################
# Fixtures for database testing
#############################################################
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
def test_db():
    """
    Fixture to provide a test database.
    """
    yield HERE / "data/mpflash.db"


@pytest.fixture(scope="module")
def engine_fx(test_db):
    # engine = create_engine("sqlite:///:memory:")
    # engine = create_engine("sqlite:///D:/mypython/mpflash/mpflash.db")
    engine = create_engine(f"sqlite:///{test_db.as_posix()}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def connection_fx(engine_fx):
    connection = engine_fx.connect()
    yield connection
    connection.close()


@pytest.fixture(scope="function")
def session_fx(connection_fx):
    transaction = connection_fx.begin()
    testSession = sessionmaker(bind=connection_fx)
    yield testSession
    transaction.rollback()


# in memory database


@pytest.fixture(scope="module")
def engine_mem():
    engine = create_engine("sqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def connection_mem(engine_mem):
    connection = engine_mem.connect()
    yield connection
    connection.close()


@pytest.fixture(scope="function")
def session_mem(connection_mem):
    transaction = connection_mem.begin()
    testSession = sessionmaker(bind=connection_fx)  # type: ignore
    yield testSession
    transaction.rollback()
