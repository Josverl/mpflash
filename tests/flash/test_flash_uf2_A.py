from pathlib import Path
from unittest import mock

import pytest

from mpflash.flash.builtins.uf2 import copy_firmware_to_uf2, flash_uf2
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
def mock_destination():
    destination = mock.Mock(spec=Path)
    destination.exists.return_value = True
    # Mock the path operation (destination / "INFO_UF2.TXT").exists()
    info_file = mock.Mock()
    info_file.exists.return_value = True
    destination.__truediv__ = mock.Mock(return_value=info_file)
    return destination


def test_copy_firmware_to_uf2_copies_data_without_metadata(mocker):
    """Avoid metadata writes after a UF2 volume consumes the firmware."""
    firmware = Path("firmware.uf2")
    destination = Path("E:/")
    copyfile = mocker.patch(
        "mpflash.flash.builtins.uf2.shutil.copyfile",
        return_value=destination / firmware.name,
    )

    result = copy_firmware_to_uf2(firmware, destination)

    assert result == destination / firmware.name
    copyfile.assert_called_once_with(firmware, destination / firmware.name)


def test_copy_firmware_to_uf2_does_not_retry_write_failure(mocker):
    """Do not write repeatedly after a UF2 volume may have reset."""
    firmware = Path("firmware.uf2")
    destination = Path("E:/")
    copyfile = mocker.patch(
        "mpflash.flash.builtins.uf2.shutil.copyfile",
        side_effect=OSError("device disappeared"),
    )

    with pytest.raises(OSError, match="device disappeared"):
        copy_firmware_to_uf2(firmware, destination)

    copyfile.assert_called_once_with(firmware, destination / firmware.name)


def test_flash_uf2_unsupported_port(mock_mcu, mock_fw_file):
    mock_mcu.port = "unsupported_port"
    with pytest.raises(KeyError):
        flash_uf2(mock_mcu, mock_fw_file)


def test_flash_uf2_board_not_in_bootloader(mock_mcu, mock_fw_file):
    with mock.patch("mpflash.flash.builtins.uf2.waitfor_uf2", return_value=None):
        result = flash_uf2(mock_mcu, mock_fw_file)
        assert result is None


def test_flash_uf2_fails_when_board_does_not_restart(mocker, mock_mcu, mock_fw_file, mock_destination):
    """Do not report a successful flash when the board never reconnects."""
    mocker.patch(
        "mpflash.flash.builtins.uf2._resolve_uf2_destination",
        return_value=mock_destination,
    )
    mocker.patch("mpflash.flash.builtins.uf2.copy_firmware_to_uf2")
    mocker.patch("mpflash.flash.builtins.uf2.get_board_id", return_value="RP2350")
    mock_mcu.wait_for_restart.return_value = False

    result = flash_uf2(mock_mcu, mock_fw_file)

    assert result is None


# TODO: Need better mocking of the destination

# def test_flash_uf2_successful_flash(mock_mcu, mock_fw_file, mock_destination):
#     with mock.patch("mpflash.flash.builtins.uf2.waitfor_uf2", return_value=mock_destination), \
#          mock.patch("mpflash.flash.builtins.uf2.copy_firmware_to_uf2"), \
#          mock.patch("mpflash.flash.builtins.uf2.dismount_uf2_linux"), \
#          mock.patch("mpflash.flash.builtins.uf2.get_board_id", return_value="test_board_id"):
#         result = flash_uf2(mock_mcu, mock_fw_file, erase=False)
#         assert result == mock_mcu

# def test_flash_uf2_successful_flash_with_erase(mock_mcu, mock_fw_file, mock_destination, mock_erase_file):
#     with mock.patch("mpflash.flash.builtins.uf2.waitfor_uf2", return_value=mock_destination), \
#          mock.patch("mpflash.flash.builtins.uf2.copy_firmware_to_uf2"), \
#          mock.patch("mpflash.flash.builtins.uf2.dismount_uf2_linux"), \
#          mock.patch("mpflash.flash.builtins.uf2.get_board_id", return_value="test_board_id"), \
#          mock.patch("pathlib.Path.resolve", return_value=mock_erase_file):
#         result = flash_uf2(mock_mcu, mock_fw_file, erase=True)
#         assert result == mock_mcu


def test_flash_uf2_uses_explicit_volume_path(tmp_path, mock_mcu, mock_fw_file):
    """Use mounted UF2 volume directly when serialport points to a valid UF2 drive.

    This also checks the explicit-path wait path via _waitfor_uf2_at_path by
    patching _is_volume_pattern to accept tmp_path.
    """
    info = tmp_path / "INFO_UF2.TXT"
    info.write_text("Board-ID: RPI-RP2\n")
    mock_mcu.serialport = str(tmp_path)

    with (
        mock.patch("mpflash.flash.builtins.uf2._is_volume_pattern", return_value=True),
        mock.patch("mpflash.flash.builtins.uf2.waitfor_uf2") as m_waitfor,
        mock.patch("mpflash.flash.builtins.uf2.copy_firmware_to_uf2") as m_copy,
        mock.patch("mpflash.flash.builtins.uf2.get_board_id", return_value="RPI-RP2"),
    ):
        result = flash_uf2(mock_mcu, mock_fw_file)

    assert result == mock_mcu
    m_waitfor.assert_not_called()
    m_copy.assert_called_once()
    # serialport must be switched to 'auto' so reconnection uses mpremote auto-detect
    assert mock_mcu.serialport == "auto"


def test_flash_uf2_explicit_volume_not_found_falls_back_to_autodetect(tmp_path, mock_mcu, mock_fw_file, mock_destination):
    """When --volume points to a path with no INFO_UF2.TXT, log a warning and
    fall back to auto-detection so the board is still found if mounted elsewhere."""
    # tmp_path is a real directory but has no INFO_UF2.TXT
    mock_mcu.serialport = str(tmp_path)

    with (
        mock.patch("mpflash.flash.builtins.uf2._is_volume_pattern", return_value=True),
        mock.patch("mpflash.flash.builtins.uf2.waitfor_uf2", return_value=mock_destination) as m_waitfor,
        mock.patch("mpflash.flash.builtins.uf2.copy_firmware_to_uf2"),
        mock.patch("mpflash.flash.builtins.uf2.get_board_id", return_value="RPI-RP2"),
    ):
        result = flash_uf2(mock_mcu, mock_fw_file)

    assert result == mock_mcu
    m_waitfor.assert_called_once()  # fell back to scanning all drives
