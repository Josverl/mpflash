import pytest
from unittest import mock
from pathlib import Path
from mpflash.mpremoteboard import MPRemoteBoard
from mpflash.flash.uf2 import flash_uf2

@pytest.fixture
def mock_mcu():
    mcu = mock.Mock(spec=MPRemoteBoard)
    mcu.port = "rp2"
    mcu.board = "test_board"
    mcu.serialport = "COM3"
    return mcu

@pytest.fixture
def mock_fw_file():
    return Path("/path/to/firmware.uf2")

@pytest.fixture
def mock_erase_file():
    return Path("/path/to/universal_flash_nuke.uf2")

@pytest.fixture
def mock_destination():
    destination = mock.Mock(spec=Path)
    destination.exists.return_value = True
    # (destination / "INFO_UF2.TXT").exists.return_value = True
    return destination

def test_flash_uf2_unsupported_port(mock_mcu, mock_fw_file):
    mock_mcu.port = "unsupported_port"
    with pytest.raises(KeyError):
        flash_uf2(mock_mcu, mock_fw_file, erase=False)

def test_flash_uf2_board_not_in_bootloader(mock_mcu, mock_fw_file):
    with mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=None):
        result = flash_uf2(mock_mcu, mock_fw_file, erase=False)
        assert result is None

#TODO: Need better mocking of the destination

# def test_flash_uf2_successful_flash(mock_mcu, mock_fw_file, mock_destination):
#     with mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=mock_destination), \
#          mock.patch("mpflash.flash.uf2.copy_firmware_to_uf2"), \
#          mock.patch("mpflash.flash.uf2.dismount_uf2_linux"), \
#          mock.patch("mpflash.flash.uf2.get_board_id", return_value="test_board_id"):
#         result = flash_uf2(mock_mcu, mock_fw_file, erase=False)
#         assert result == mock_mcu

# def test_flash_uf2_successful_flash_with_erase(mock_mcu, mock_fw_file, mock_destination, mock_erase_file):
#     with mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=mock_destination), \
#          mock.patch("mpflash.flash.uf2.copy_firmware_to_uf2"), \
#          mock.patch("mpflash.flash.uf2.dismount_uf2_linux"), \
#          mock.patch("mpflash.flash.uf2.get_board_id", return_value="test_board_id"), \
#          mock.patch("pathlib.Path.resolve", return_value=mock_erase_file):
#         result = flash_uf2(mock_mcu, mock_fw_file, erase=True)
#         assert result == mock_mcu

def test_flash_uf2_erase_not_supported(mock_mcu, mock_fw_file):
    mock_mcu.port = "unsupported_erase_port"
    with mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=None):
        with pytest.raises(KeyError):
            result = flash_uf2(mock_mcu, mock_fw_file, erase=True)
            assert result is None
