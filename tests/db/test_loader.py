from pathlib import Path

import pytest

from mpflash.db.core import create_database, migrate_database
from mpflash.db.loader import load_data_from_zip, load_jsonl_to_db, update_boards


def test_load_data_from_zip(session_fx, engine_fx, mocker, pytestconfig):
    """
    Test the get_metadata function.
    """
    # Mock the session
    mocker.patch("mpflash.db.loader.Session", session_fx)
    mocker.patch("mpflash.db.meta.Session", session_fx)
    # mock the engine
    mocker.patch("mpflash.db.core.Session", session_fx)
    mocker.patch("mpflash.db.core.engine", engine_fx)

    # create empty database
    create_database()

    zip = pytestconfig.rootpath / "mpflash/db/micropython_boards.zip"
    assert zip.exists()
    c_loaded = load_data_from_zip(zip)
    assert c_loaded > 0
    # check if the database is not empty
    from mpflash.db.models import Board

    with session_fx() as session:
        count = session.query(Board).count()
    assert count >= c_loaded


def test_update_boards(session_fx, engine_fx, mocker, pytestconfig):
    """
    load the boards from the zip to the database
    """
    # Mock the session
    mocker.patch("mpflash.db.loader.Session", session_fx)
    # mock the engine
    mocker.patch("mpflash.db.core.Session", session_fx)
    mocker.patch("mpflash.db.core.engine", engine_fx)

    metadata = {"boards_version": "v0.0.0"}
    # mock old  metadata
    mocker.patch("mpflash.db.loader.get_metadata", return_value=metadata)

    update_boards()


def test_load_jsonl_to_db(session_fx, engine_fx, mocker, pytestconfig):
    """
    Load a JSONL file into the database
    """
    # Mock the session
    mocker.patch("mpflash.db.loader.Session", session_fx)
    # mock the engine
    mocker.patch("mpflash.db.core.Session", session_fx)
    mocker.patch("mpflash.db.core.engine", engine_fx)

    # create empty database
    create_database()

    jsonl_file = pytestconfig.rootpath / "tests/data/firmware.jsonl"
    assert jsonl_file.exists()
    c_loaded = load_jsonl_to_db(jsonl_file)
    assert c_loaded > 0
