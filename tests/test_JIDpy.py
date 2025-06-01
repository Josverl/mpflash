from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from mpflash import mpremoteboard
from mpflash.db.models import Firmware
from mpflash.download.jid import ensure_firmware_downloaded
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


# @pytest.mark.parametrize("already_downloaded", [True, False])
# def test_ensure_firmware_downloaded_downloads_missing(dummy_worklist, patched_dependencies, already_downloaded):
#     """Test that ensure_firmware_downloaded downloads missing firmware and updates the worklist."""
#     find_fw, download_fn, alt_names = patched_dependencies

#     # Simulate firmware found or not found for first mcu
#     def find_fw_side_effect(board_id, version, port):
#         fw1 = Firmware(firmware_file="fw1", board_id="ESP32_ESP32_GENERIC", version=version)
#         fw2 = Firmware(firmware_file="fw2", board_id="ESP32_ESP32_GENERIC", version=version)
#         if board_id.startswith("COM101"):
#             return [fw1] if already_downloaded else []
#         if board_id.startswith("COM102"):
#             return [fw2]
#         return []

#     find_fw.side_effect = find_fw_side_effect
#     alt_names.side_effect = lambda board, port: [board]

#     # If not already downloaded, simulate download will make it available
#     if not already_downloaded:

#         def find_fw_after_download(board_id, version, port):
#             fw1 = Firmware(firmware_file="fw1", board_id="ESP32_ESP32_GENERIC", version=version)
#             fw2 = Firmware(firmware_file="fw2", board_id="ESP32_ESP32_GENERIC", version=version)
#             if board_id.startswith("COM101"):
#                 return [fw1]
#             if board_id.startswith("COM102"):
#                 return [fw2]
#             return []

#         find_fw.side_effect = [[], ["fw1"], ["fw2"]]

#     worklist = dummy_worklist.copy()
#     ensure_firmware_downloaded(worklist, "v1.23.0")

#     # Both entries should now have firmware
#     for mcu, firmware in worklist:
#         assert firmware is not None

#     # download should be called only if not already downloaded
#     if already_downloaded:
#         download_fn.assert_not_called()
#     else:
#         download_fn.assert_called_once()


def test_ensure_firmware_downloaded_raises_on_failure(dummy_worklist, patched_dependencies):
    """Test that ensure_firmware_downloaded raises MPFlashError if download fails."""
    find_fw, download_fn, alt_names = patched_dependencies
    # Simulate firmware never found
    find_fw.return_value = []
    alt_names.side_effect = lambda board, port: [board]
    download_fn.return_value = None

    worklist = dummy_worklist.copy()
    with pytest.raises(MPFlashError):
        ensure_firmware_downloaded(worklist, "v1.23.0", False)


def test_ensure_firmware_downloaded_preserves_existing_firmware(dummy_worklist, patched_dependencies):
    """Test that ensure_firmware_downloaded does not overwrite existing firmware."""
    find_fw, download_fn, alt_names = patched_dependencies
    fw1 = Firmware(firmware_file="new_firmware.bin", board_id="ESP32_ESP32_GENERIC", version="v1.23.0")
    # Simulate firmware found for both
    find_fw.return_value = [fw1]
    alt_names.side_effect = lambda board, port: [board]

    worklist = dummy_worklist.copy()
    ensure_firmware_downloaded(worklist, "v1.23.0", False)
    # Second entry should remain unchanged
    assert worklist[1][1].firmware_file == "firmware.bin"
