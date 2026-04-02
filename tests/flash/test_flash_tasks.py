from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mpflash.common import BootloaderMethod, FlashMethod
from mpflash.db.models import Firmware
from mpflash.download.jid import ensure_firmware_downloaded_tasks
from mpflash.errors import MPFlashError
from mpflash.flash import _auto_select_flash_method, _select_flash_method, _select_serial_method, flash_mcu, flash_tasks
from mpflash.flash.worklist import FlashTask, FlashTaskList
from mpflash.mpremoteboard import MPRemoteBoard


def test_flash_task_properties():
    board = MPRemoteBoard("COMX")
    board.board_id = "ESP32_GENERIC"
    fw = Firmware(board_id="ESP32_GENERIC", version="1.23.0", port="esp32")
    task = FlashTask(board=board, firmware=fw)
    assert task.is_valid
    assert task.board_id == "ESP32_GENERIC"
    assert task.firmware_version == "1.23.0"


def test_flash_task_properties_no_fw():
    board = MPRemoteBoard("COMY")
    board.board_id = "ESP32_GENERIC"
    task = FlashTask(board=board, firmware=None)
    assert not task.is_valid
    assert task.firmware_version == "unknown"


@patch("mpflash.download.jid.find_downloaded_firmware")
@patch("mpflash.download.jid.download")
@patch("mpflash.download.jid.alternate_board_names")
def test_ensure_firmware_downloaded_tasks_download(mock_alt, mock_dl, mock_find):
    board = MPRemoteBoard("COMZ")
    board.board_id = "ESP32_GENERIC"
    board.port = "esp32"
    task = FlashTask(board=board, firmware=None)
    # first call returns none, after download returns one firmware
    mock_find.side_effect = [[], [Firmware(board_id="ESP32_GENERIC", version="1.24.0", port="esp32")]]
    mock_alt.return_value = ["ESP32_GENERIC"]

    ensure_firmware_downloaded_tasks([task], version="1.24.0", force=False)
    assert task.firmware is not None
    assert task.firmware.version == "1.24.0"


@patch("mpflash.download.jid.find_downloaded_firmware")
@patch("mpflash.download.jid.download")
@patch("mpflash.download.jid.alternate_board_names")
def test_ensure_firmware_downloaded_tasks_force(mock_alt, mock_dl, mock_find):
    board = MPRemoteBoard("COMA")
    board.board_id = "ESP32_GENERIC"
    board.port = "esp32"
    fw_existing = Firmware(board_id="ESP32_GENERIC", version="1.25.0", port="esp32")
    task = FlashTask(board=board, firmware=fw_existing)
    # When force=True, find_downloaded_firmware is only called after download
    # So we only need one return value
    mock_find.return_value = [Firmware(board_id="ESP32_GENERIC", version="1.25.0", port="esp32")]
    mock_alt.return_value = ["ESP32_GENERIC"]

    ensure_firmware_downloaded_tasks([task], version="1.25.0", force=True)
    assert task.firmware is not None
    # Verify download was called because force=True
    mock_dl.assert_called_once()


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_success(mock_config, mock_flash_mcu):
    """Test successful flashing of tasks."""
    mock_config.firmware_folder = Path("/test/firmware")
    mock_flash_mcu.return_value = MagicMock()  # successful flash returns updated board

    board = MPRemoteBoard("COM1")
    board.board_id = "ESP32_GENERIC"
    board.serialport = "COM1"
    fw = Firmware(board_id="ESP32_GENERIC", version="1.23.0", port="esp32", firmware_file="test.bin")
    task = FlashTask(board=board, firmware=fw)

    with patch("pathlib.Path.exists", return_value=True):
        result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 1
    mock_flash_mcu.assert_called_once()


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_no_firmware(mock_config, mock_flash_mcu):
    """Test skipping tasks with no firmware."""
    board = MPRemoteBoard("COM1")
    board.board_id = "ESP32_GENERIC"
    board.serialport = "COM1"
    task = FlashTask(board=board, firmware=None)

    result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 0
    mock_flash_mcu.assert_not_called()


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_file_not_exists(mock_config, mock_flash_mcu):
    """Test skipping tasks when firmware file doesn't exist."""
    mock_config.firmware_folder = Path("/test/firmware")

    board = MPRemoteBoard("COM1")
    board.board_id = "ESP32_GENERIC"
    board.serialport = "COM1"
    fw = Firmware(board_id="ESP32_GENERIC", version="1.23.0", port="esp32", firmware_file="missing.bin")
    task = FlashTask(board=board, firmware=fw)

    with patch("pathlib.Path.exists", return_value=False):
        result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 0
    mock_flash_mcu.assert_not_called()


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_flash_error(mock_config, mock_flash_mcu):
    """Test handling flash errors."""
    mock_config.firmware_folder = Path("/test/firmware")
    mock_flash_mcu.side_effect = MPFlashError("Flash failed")

    board = MPRemoteBoard("COM1")
    board.board_id = "ESP32_GENERIC"
    board.serialport = "COM1"
    fw = Firmware(board_id="ESP32_GENERIC", version="1.23.0", port="esp32", firmware_file="test.bin")
    task = FlashTask(board=board, firmware=fw)

    with patch("pathlib.Path.exists", return_value=True):
        result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 0
    mock_flash_mcu.assert_called_once()


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_flash_failed(mock_config, mock_flash_mcu):
    """Test handling when flash_mcu returns None (failure)."""
    mock_config.firmware_folder = Path("/test/firmware")
    mock_flash_mcu.return_value = None  # flash failed

    board = MPRemoteBoard("COM1")
    board.board_id = "ESP32_GENERIC"
    board.serialport = "COM1"
    fw = Firmware(board_id="ESP32_GENERIC", version="1.23.0", port="esp32", firmware_file="test.bin")
    task = FlashTask(board=board, firmware=fw)

    with patch("pathlib.Path.exists", return_value=True):
        result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 0
    mock_flash_mcu.assert_called_once()


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_custom_firmware(mock_config, mock_flash_mcu):
    """Test flashing custom firmware with TOML updates."""
    mock_config.firmware_folder = Path("/test/firmware")
    updated_board = MagicMock()
    mock_flash_mcu.return_value = updated_board

    board = MPRemoteBoard("COM1")
    board.board_id = "ESP32_GENERIC"
    board.serialport = "COM1"
    board.get_board_info_toml = MagicMock()
    board.set_board_info_toml = MagicMock()
    board.toml = {}

    fw = Firmware(
        board_id="ESP32_GENERIC",
        version="1.23.0",
        port="esp32",
        firmware_file="custom.bin",
        custom=True,
        description="Custom firmware",
        custom_id="custom_123",
    )
    task = FlashTask(board=board, firmware=fw)

    with patch("pathlib.Path.exists", return_value=True):
        result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 1
    board.get_board_info_toml.assert_called_once()
    board.set_board_info_toml.assert_called_once()
    assert board.toml["description"] == "Custom firmware"
    assert board.toml["mpflash"]["board_id"] == "ESP32_GENERIC"
    assert board.toml["mpflash"]["custom_id"] == "custom_123"


# ---------------------------------------------------------------------------
# Tests for flash_mcu (covers lines 130-154 in flash/__init__.py)
# ---------------------------------------------------------------------------


def _make_mcu(port: str = "esp32", board: str = "ESP32_GENERIC", serialport: str = "COM1"):
    mcu = MagicMock()
    mcu.port = port
    mcu.board = board
    mcu.serialport = serialport
    mcu.board_id = board
    mcu.cpu = "ESP32"
    return mcu


@patch("mpflash.flash._select_flash_method")
@patch("mpflash.flash.flash_esp")
@patch("mpflash.flash.enter_bootloader", create=True)
def test_flash_mcu_esptool(mock_bootloader, mock_flash_esp, mock_select_method):
    """Test flash_mcu routes to flash_esp for ESPTOOL method."""
    mock_select_method.return_value = FlashMethod.ESPTOOL
    expected = MagicMock()
    mock_flash_esp.return_value = expected

    mcu = _make_mcu(port="esp32")
    fw_file = Path("fw.bin")

    result = flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)

    assert result is expected
    mock_flash_esp.assert_called_once_with(mcu, fw_file=fw_file, erase=False)


@patch("mpflash.flash._select_flash_method")
@patch("mpflash.flash.flash_uf2")
@patch("mpflash.flash.enter_bootloader", create=True)
def test_flash_mcu_uf2(mock_enter_bl, mock_flash_uf2, mock_select_method):
    """Test flash_mcu routes to flash_uf2 for UF2 method."""
    mock_select_method.return_value = FlashMethod.UF2
    mock_enter_bl.return_value = True
    expected = MagicMock()
    mock_flash_uf2.return_value = expected

    mcu = _make_mcu(port="rp2")
    fw_file = Path("fw.uf2")

    with patch("mpflash.bootloader.activate.enter_bootloader", return_value=True):
        result = flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)

    assert result is expected


@patch("mpflash.flash._select_flash_method")
@patch("mpflash.flash.flash_stm32")
@patch("mpflash.flash.enter_bootloader", create=True)
def test_flash_mcu_dfu(mock_enter_bl, mock_flash_stm32, mock_select_method):
    """Test flash_mcu routes to flash_stm32 for DFU method."""
    mock_select_method.return_value = FlashMethod.DFU
    mock_enter_bl.return_value = True
    expected = MagicMock()
    mock_flash_stm32.return_value = expected

    mcu = _make_mcu(port="stm32")
    fw_file = Path("fw.dfu")

    with patch("mpflash.bootloader.activate.enter_bootloader", return_value=True):
        result = flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)

    assert result is expected


@patch("mpflash.flash._select_flash_method")
@patch("mpflash.flash.is_debug_programming_available")
@patch("mpflash.flash.flash_pyocd")
def test_flash_mcu_pyocd(mock_flash_pyocd, mock_is_available, mock_select_method):
    """Test flash_mcu routes to flash_pyocd for PYOCD method."""
    mock_select_method.return_value = FlashMethod.PYOCD
    mock_is_available.return_value = True
    expected = MagicMock()
    mock_flash_pyocd.return_value = expected

    mcu = _make_mcu(port="stm32")
    fw_file = Path("fw.hex")

    result = flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)

    assert result is expected
    mock_flash_pyocd.assert_called_once()


@patch("mpflash.flash._select_flash_method")
@patch("mpflash.flash.is_debug_programming_available")
def test_flash_mcu_pyocd_not_available(mock_is_available, mock_select_method):
    """Test flash_mcu raises MPFlashError when pyocd not available."""
    mock_select_method.return_value = FlashMethod.PYOCD
    mock_is_available.return_value = False

    mcu = _make_mcu(port="stm32")
    fw_file = Path("fw.hex")

    with pytest.raises(MPFlashError):
        flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)


@patch("mpflash.flash._select_flash_method")
def test_flash_mcu_unsupported_method(mock_select_method):
    """Test flash_mcu raises MPFlashError for unsupported method."""
    # Return a method value not in the if/elif chain
    mock_select_method.return_value = FlashMethod.SERIAL

    mcu = _make_mcu()
    fw_file = Path("fw.bin")

    with pytest.raises(MPFlashError):
        flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)


@patch("mpflash.flash._select_flash_method")
@patch("mpflash.flash.flash_esp")
def test_flash_mcu_wraps_exception(mock_flash_esp, mock_select_method):
    """Test flash_mcu wraps unexpected exceptions in MPFlashError."""
    mock_select_method.return_value = FlashMethod.ESPTOOL
    mock_flash_esp.side_effect = RuntimeError("unexpected error")

    mcu = _make_mcu()
    fw_file = Path("fw.bin")

    with pytest.raises(MPFlashError, match="Failed to flash"):
        flash_mcu(mcu, fw_file=fw_file, erase=False, bootloader=BootloaderMethod.AUTO)


# ---------------------------------------------------------------------------
# Tests for _select_flash_method (covers lines 180-193 in flash/__init__.py)
# ---------------------------------------------------------------------------


@patch("mpflash.flash.is_debug_programming_available")
@patch("mpflash.flash.is_pyocd_supported_from_mcu")
def test_select_flash_method_pyocd_valid(mock_is_supported, mock_is_available):
    """Test _select_flash_method returns PYOCD when explicitly requested and supported."""
    mock_is_available.return_value = True
    mock_is_supported.return_value = True

    mcu = _make_mcu(port="stm32")
    result = _select_flash_method(mcu, FlashMethod.PYOCD, Path("fw.hex"))

    assert result == FlashMethod.PYOCD


@patch("mpflash.flash.is_debug_programming_available")
def test_select_flash_method_pyocd_not_available(mock_is_available):
    """Test _select_flash_method raises when pyocd not available (lines 181-182)."""
    mock_is_available.return_value = False

    mcu = _make_mcu(port="stm32")
    with pytest.raises(MPFlashError, match="Debug probe"):
        _select_flash_method(mcu, FlashMethod.PYOCD, Path("fw.hex"))


@patch("mpflash.flash.is_debug_programming_available")
@patch("mpflash.flash.is_pyocd_supported_from_mcu")
def test_select_flash_method_pyocd_unsupported_target(mock_is_supported, mock_is_available):
    """Test _select_flash_method raises when target not supported (line 184-185)."""
    mock_is_available.return_value = True
    mock_is_supported.return_value = False

    mcu = _make_mcu(port="stm32")
    mcu.cpu = "UNKNOWN_CPU"
    with pytest.raises(MPFlashError, match="pyOCD does not support"):
        _select_flash_method(mcu, FlashMethod.PYOCD, Path("fw.hex"))


def test_select_flash_method_uf2_valid():
    """Test _select_flash_method returns UF2 for rp2 with .uf2 file."""
    mcu = _make_mcu(port="rp2")
    result = _select_flash_method(mcu, FlashMethod.UF2, Path("fw.uf2"))
    assert result == FlashMethod.UF2


def test_select_flash_method_uf2_invalid_port():
    """Test _select_flash_method raises for UF2 with wrong port (line 187)."""
    mcu = _make_mcu(port="esp32")
    with pytest.raises(MPFlashError, match="UF2 method not suitable"):
        _select_flash_method(mcu, FlashMethod.UF2, Path("fw.uf2"))


def test_select_flash_method_dfu_valid():
    """Test _select_flash_method returns DFU for stm32 (line 190)."""
    mcu = _make_mcu(port="stm32")
    result = _select_flash_method(mcu, FlashMethod.DFU, Path("fw.dfu"))
    assert result == FlashMethod.DFU


def test_select_flash_method_dfu_invalid_port():
    """Test _select_flash_method raises DFU with non-stm32 (line 191-192)."""
    mcu = _make_mcu(port="esp32")
    with pytest.raises(MPFlashError, match="DFU method not suitable"):
        _select_flash_method(mcu, FlashMethod.DFU, Path("fw.dfu"))


def test_select_flash_method_esptool_valid():
    """Test _select_flash_method returns ESPTOOL for esp32 (line 194)."""
    mcu = _make_mcu(port="esp32")
    result = _select_flash_method(mcu, FlashMethod.ESPTOOL, Path("fw.bin"))
    assert result == FlashMethod.ESPTOOL


def test_select_flash_method_esptool_invalid_port():
    """Test _select_flash_method raises ESPTOOL with non-esp port (lines 195-196)."""
    mcu = _make_mcu(port="stm32")
    with pytest.raises(MPFlashError, match="esptool method not suitable"):
        _select_flash_method(mcu, FlashMethod.ESPTOOL, Path("fw.bin"))


@patch("mpflash.flash._select_serial_method")
def test_select_flash_method_serial_delegates(mock_serial):
    """Test _select_flash_method with SERIAL delegates to _select_serial_method (line 198)."""
    mock_serial.return_value = FlashMethod.ESPTOOL
    mcu = _make_mcu(port="esp32")
    result = _select_flash_method(mcu, FlashMethod.SERIAL, Path("fw.bin"))
    assert result == FlashMethod.ESPTOOL
    mock_serial.assert_called_once_with(mcu, Path("fw.bin"))


def test_select_flash_method_auto_delegates_to_auto():
    """Test _select_flash_method AUTO mode returns auto selection."""
    mcu = _make_mcu(port="esp32")
    result = _select_flash_method(mcu, FlashMethod.AUTO, Path("fw.bin"))
    assert result == FlashMethod.ESPTOOL


# ---------------------------------------------------------------------------
# Tests for _auto_select_flash_method and _select_serial_method
# ---------------------------------------------------------------------------


def test_auto_select_uf2_for_rp2():
    mcu = _make_mcu(port="rp2")
    result = _auto_select_flash_method(mcu, Path("fw.uf2"))
    assert result == FlashMethod.UF2


def test_auto_select_dfu_for_stm32():
    mcu = _make_mcu(port="stm32")
    result = _auto_select_flash_method(mcu, Path("fw.dfu"))
    assert result == FlashMethod.DFU


def test_auto_select_esptool_for_esp32():
    mcu = _make_mcu(port="esp32")
    result = _auto_select_flash_method(mcu, Path("fw.bin"))
    assert result == FlashMethod.ESPTOOL


def test_auto_select_esptool_for_esp8266():
    mcu = _make_mcu(port="esp8266")
    result = _auto_select_flash_method(mcu, Path("fw.bin"))
    assert result == FlashMethod.ESPTOOL


def test_select_serial_method_unknown_raises():
    """Test _select_serial_method raises for unknown platform."""
    mcu = _make_mcu(port="unknown_port")
    with pytest.raises(MPFlashError, match="Don't know how to flash"):
        _select_serial_method(mcu, Path("fw.bin"))


@patch("mpflash.download.jid.find_downloaded_firmware")
@patch("mpflash.download.jid.download")
@patch("mpflash.download.jid.alternate_board_names")
def test_ensure_firmware_downloaded_tasks_error(mock_alt, mock_dl, mock_find):
    """Test error handling when download fails."""
    board = MPRemoteBoard("COMZ")
    board.board_id = "ESP32_GENERIC"
    board.port = "esp32"
    board.serialport = "COMZ"
    task = FlashTask(board=board, firmware=None)

    # Both calls return empty (download failed)
    mock_find.return_value = []
    mock_alt.return_value = ["ESP32_GENERIC"]

    with pytest.raises(MPFlashError, match="Failed to download"):
        ensure_firmware_downloaded_tasks([task], version="1.24.0", force=False)
