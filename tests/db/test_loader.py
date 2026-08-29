from mpflash.db.loader import get_boards_hash, load_data_from_zip, load_jsonl_to_db, update_boards


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


def test_update_boards(session_fx, mocker, pytestconfig):
    """
    load the boards from the zip to the database
    """
    metadata = {"boards_version": "v1.30.0-preview"}
    mocker.patch("mpflash.db.loader.get_metadata", return_value=metadata)
    mocker.patch("mpflash.db.loader.get_boards_hash", return_value="new-hash")
    mock_load = mocker.patch("mpflash.db.loader.load_data_from_zip", return_value=1)
    mock_set = mocker.patch("mpflash.db.loader.set_metadata_value", autospec=True)
    mock_delete = mocker.patch("mpflash.db.loader.delete_metadata_value", autospec=True)

    update_boards()

    mock_load.assert_called_once()
    mock_set.assert_called_once_with("boards_hash", "new-hash")
    mock_delete.assert_called_once_with("boards_version")


def test_update_boards_skips_matching_hash(mocker):
    """Do not reload board data when the bundled content is unchanged."""
    mocker.patch("mpflash.db.loader.get_metadata", return_value={"boards_hash": "same-hash"})
    mocker.patch("mpflash.db.loader.get_boards_hash", return_value="same-hash")
    mock_load = mocker.patch("mpflash.db.loader.load_data_from_zip")
    mock_set = mocker.patch("mpflash.db.loader.set_metadata_value")
    mock_delete = mocker.patch("mpflash.db.loader.delete_metadata_value")

    update_boards()

    mock_load.assert_not_called()
    mock_set.assert_not_called()
    mock_delete.assert_called_once_with("boards_version")


def test_get_boards_hash(tmp_path, mocker):
    """Read and trim the generated board content hash."""
    mocker.patch("mpflash.db.loader.HERE", tmp_path)
    (tmp_path / "boards_hash.txt").write_text("abc123\n", encoding="utf-8")

    assert get_boards_hash() == "abc123"


def test_load_jsonl_to_db(session_fx, mocker, pytestconfig):
    """
    Load a JSONL file into the database
    """
    jsonl_file = pytestconfig.rootpath / "tests/data/firmware.jsonl"
    assert jsonl_file.exists()
    c_loaded = load_jsonl_to_db(jsonl_file)
    assert c_loaded > 0
