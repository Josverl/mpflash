import pytest
from pathlib import Path
from mpflash.flash.uf2.boardid import get_board_id

# filepath: d:\mypython\mpflash\mpflash\flash\uf2\test_boardid.py

pytestmark = [pytest.mark.mpflash]

def test_get_board_id_valid(tmp_path: Path):
    info_file = tmp_path / "INFO_UF2.TXT"
    info_file.write_text("Board-ID: TEST_BOARD\nOther-Info: XYZ\n")
    assert get_board_id(tmp_path) == "TEST_BOARD"

def test_get_board_id_missing_board_id(tmp_path: Path):
    info_file = tmp_path / "INFO_UF2.TXT"
    info_file.write_text("Other-Info: XYZ\n")
    assert get_board_id(tmp_path) == "Unknown"

def test_get_board_id_empty_file(tmp_path: Path):
    info_file = tmp_path / "INFO_UF2.TXT"
    info_file.write_text("")
    assert get_board_id(tmp_path) == "Unknown"

def test_get_board_id_no_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        get_board_id(tmp_path)