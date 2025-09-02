from pathlib import Path
from unittest import mock

import pytest

from mpflash.flash.uf2 import flash_uf2
from mpflash.mpremoteboard import MPRemoteBoard


@pytest.fixture
def mock_mcu():
    mcu = mock.Mock(spec=MPRemoteBoard)
    mcu.port = "rp2"
    mcu.board = "test_board"
    mcu.serialport = "COM3"
    mcu.run_command = mock.Mock()  # Add run_command method
    mcu.wait_for_restart = mock.Mock()  # Add wait_for_restart method
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
    # Mock the path operation (destination / "INFO_UF2.TXT").exists()
    info_file = mock.Mock()
    info_file.exists.return_value = True
    destination.__truediv__ = mock.Mock(return_value=info_file)
    return destination


def test_flash_uf2_unsupported_port(mock_mcu, mock_fw_file):
    mock_mcu.port = "unsupported_port"
    with pytest.raises(KeyError):
        flash_uf2(mock_mcu, mock_fw_file, erase=False)


def test_flash_uf2_board_not_in_bootloader(mock_mcu, mock_fw_file):
    with mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=None):
        result = flash_uf2(mock_mcu, mock_fw_file, erase=False)
        assert result is None


# TODO: Need better mocking of the destination

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


def test_flash_uf2_erase_fallback_samd(mock_mcu, mock_fw_file, mock_destination):
    """Test that SAMD port uses mpremote rm -r :/ for erase after flashing"""
    mock_mcu.port = "samd"
    mock_mcu.run_command.return_value = (0, [""])  # Successful erase

    with (
        mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=mock_destination),
        mock.patch("mpflash.flash.uf2.copy_firmware_to_uf2"),
        mock.patch("mpflash.flash.uf2.dismount_uf2_linux"),
        mock.patch("mpflash.flash.uf2.get_board_id", return_value="test_board_id"),
    ):
        result = flash_uf2(mock_mcu, mock_fw_file, erase=True)

        # Verify that run_command was called with rm -r :/ after flashing
        mock_mcu.run_command.assert_called_with(["rm", "-r", ":/"], timeout=30, resume=True)
        assert result == mock_mcu


def test_flash_uf2_erase_fallback_failed(mock_mcu, mock_fw_file, mock_destination):
    """Test that failed mpremote erase is logged but doesn't stop flashing"""
    mock_mcu.port = "samd"
    mock_mcu.run_command.return_value = (1, ["Error message"])  # Failed erase

    with (
        mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=mock_destination),
        mock.patch("mpflash.flash.uf2.copy_firmware_to_uf2"),
        mock.patch("mpflash.flash.uf2.dismount_uf2_linux"),
        mock.patch("mpflash.flash.uf2.get_board_id", return_value="test_board_id"),
    ):
        result = flash_uf2(mock_mcu, mock_fw_file, erase=True)

        # Verify that run_command was called with rm -r :/ after flashing
        mock_mcu.run_command.assert_called_with(["rm", "-r", ":/"], timeout=30, resume=True)
        # Should still complete flashing even if erase failed
        assert result == mock_mcu


def test_flash_uf2_erase_not_supported(mock_mcu, mock_fw_file):
    mock_mcu.port = "unsupported_erase_port"
    with mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=None):
        with pytest.raises(KeyError):
            result = flash_uf2(mock_mcu, mock_fw_file, erase=True)
            assert result is None


def test_flash_uf2_no_erase_command_when_erase_false(mock_mcu, mock_fw_file, mock_destination):
    """Test that mpremote rm command is not called when erase=False"""
    mock_mcu.port = "samd"
    mock_mcu.run_command = mock.Mock()

    with (
        mock.patch("mpflash.flash.uf2.waitfor_uf2", return_value=mock_destination),
        mock.patch("mpflash.flash.uf2.copy_firmware_to_uf2"),
        mock.patch("mpflash.flash.uf2.dismount_uf2_linux"),
        mock.patch("mpflash.flash.uf2.get_board_id", return_value="test_board_id"),
    ):
        result = flash_uf2(mock_mcu, mock_fw_file, erase=False)

        # Verify that run_command was NOT called
        mock_mcu.run_command.assert_not_called()
        assert result == mock_mcu
