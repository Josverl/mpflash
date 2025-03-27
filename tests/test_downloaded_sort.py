from pathlib import Path

import pytest

from mpflash.config import config
from mpflash.downloaded import downloaded, find_downloaded_firmware

pytestmark = [pytest.mark.mpflash]

def test_load(tmp_path: Path, test_fw_path: Path):
    all_stuff = downloaded(test_fw_path / "mpflash.db")
    assert len(all_stuff) > 0
