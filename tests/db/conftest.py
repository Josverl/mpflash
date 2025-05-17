from pathlib import Path

import pytest

# Constants for test
HERE = Path(__file__).parent

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def test_db():
    """
    Fixture to provide a test database.
    """
    yield HERE.parent / "data/mpflash.db"


@pytest.fixture(scope="session")
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
