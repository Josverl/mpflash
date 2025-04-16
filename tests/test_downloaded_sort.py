from pathlib import Path

import pytest

from mpflash.downloaded import downloaded, find_downloaded_firmware

pytestmark = [pytest.mark.mpflash]

def test_load(tmp_path: Path, test_fw_path: Path):
    all_stuff = downloaded(test_fw_path / "mpflash.db")
    assert len(all_stuff) > 0


def test_find(test_fw_path: Path):
    fws = find_downloaded_firmware(
        fw_folder=test_fw_path, port="samd", board_id="SEEED_WIO_TERMINAL", version="preview"
    )
    assert len(fws) > 0
    assert fws[0].board == "SEEED_WIO_TERMINAL"
    assert int(fws[-1].build) > 0
