from pathlib import Path

import pytest
from unittest.mock import MagicMock

from mpflash.db.core import create_database, migrate_database
from mpflash.db.loader import load_data_from_zip, load_jsonl_to_db, update_boards


def test_load_data_from_zip(session_fx, mocker, pytestconfig):
    """
    Test the load_data_from_zip function.
    """
    zip = pytestconfig.rootpath / "mpflash/db/micropython_boards.zip"
    assert zip.exists()
    c_loaded = load_data_from_zip(zip)
    assert c_loaded > 0
    # check if the database is not empty
    from mpflash.db.models import Board

    count = Board.select().count()
    assert count >= c_loaded


def test_load_data_includes_v129_p4_variants(session_fx, pytestconfig):
    """Test that all ESP32 P4 variants released with v1.29 are available."""
    from mpflash.db.models import Board

    zip_file = pytestconfig.rootpath / "mpflash/db/micropython_boards.zip"
    load_data_from_zip(zip_file)

    variants = {
        board.variant
        for board in Board.select().where(
            (Board.board_name == "ESP32_GENERIC_P4")
            & (Board.version == "v1.29.0")
        )
        if board.variant
    }

    assert variants == {
        "C5_WIFI",
        "C6_WIFI",
        "PRE_REV3",
        "PRE_REV3_C5_WIFI",
        "PRE_REV3_C6_WIFI",
    }


def test_update_boards(session_fx, mocker, pytestconfig):
    """
    load the boards from the zip to the database
    """
    metadata = {"boards_version": "v0.0.0"}
    # mock old  metadata
    mocker.patch("mpflash.db.loader.get_metadata", return_value=metadata)
    mocker.patch("mpflash.db.loader.set_metadata_value", autospec=True)
    update_boards()


def test_load_jsonl_to_db(session_fx, mocker, pytestconfig):
    """
    Load a JSONL file into the database
    """
    jsonl_file = pytestconfig.rootpath / "tests/data/firmware.jsonl"
    assert jsonl_file.exists()
    c_loaded = load_jsonl_to_db(jsonl_file)
    assert c_loaded > 0
