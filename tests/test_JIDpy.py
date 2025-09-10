from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from mpflash import mpremoteboard
from mpflash.db.models import Firmware
from mpflash.errors import MPFlashError
from mpflash.flash.worklist import WorkList
from mpflash.mpremoteboard import MPRemoteBoard

"""Tests for ensure_firmware_downloaded in mpflash.download.jid."""


@pytest.fixture
def dummy_worklist(mocker) -> WorkList:
    """Fixture for a dummy worklist."""

    mcu1 = MPRemoteBoard("COM101")
    mcu2 = MPRemoteBoard("COM102")

    return [
        (mcu1, None),
        (mcu2, Firmware(firmware_file="firmware.bin", board_id="ESP32_ESP32_GENERIC", version="v1.23.0")),
    ]


@pytest.fixture
def patched_dependencies():
    """Patch dependencies for ensure_firmware_downloaded."""
    with (
        patch("mpflash.download.jid.find_downloaded_firmware") as find_fw,
        patch("mpflash.download.jid.download") as download_fn,
        patch("mpflash.download.jid.alternate_board_names") as alt_names,
    ):
        yield find_fw, download_fn, alt_names


