from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mpflash.common import BootloaderMethod
from mpflash.common import FlashMethod
from mpflash.db.models import Firmware
from mpflash.download.jid import ensure_firmware_downloaded_tasks
from mpflash.errors import MPFlashError
from mpflash.flash import flash_tasks
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
def test_flash_tasks_normalizes_legacy_backslash_paths(mock_flash_mcu, tmp_path, monkeypatch):
    """Legacy Windows-style firmware paths should resolve on POSIX hosts."""
    monkeypatch.setattr("mpflash.flash.config._firmware_folder", tmp_path)
    mock_flash_mcu.return_value = MagicMock()

    board = MPRemoteBoard("/dev/ttyUSB0")
    board.board_id = "ESP8266_GENERIC"
    board.board = "ESP8266_GENERIC"
    board.serialport = "/dev/ttyUSB0"

    fw_file = tmp_path / "esp8266" / "ESP8266_GENERIC-v1.28.0.bin"
    fw_file.parent.mkdir(parents=True, exist_ok=True)
    fw_file.write_bytes(b"bin")

    fw = Firmware(
        board_id="ESP8266_GENERIC",
        version="1.28.0",
        port="esp8266",
        firmware_file="esp8266\\ESP8266_GENERIC-v1.28.0.bin",
    )
    task = FlashTask(board=board, firmware=fw)

    result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 1
    _, kwargs = mock_flash_mcu.call_args
    assert kwargs["fw_file"] == fw_file


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


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_custom_firmware_without_custom_id(mock_config, mock_flash_mcu):
    """None custom_id should not be written to TOML metadata."""
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
        custom_id=None,
    )
    task = FlashTask(board=board, firmware=fw)

    with patch("pathlib.Path.exists", return_value=True):
        result = flash_tasks([task], erase=False, bootloader=BootloaderMethod.AUTO)

    assert len(result) == 1
    board.get_board_info_toml.assert_called_once()
    board.set_board_info_toml.assert_called_once()
    assert board.toml["description"] == "Custom firmware"
    assert board.toml["mpflash"]["board_id"] == "ESP32_GENERIC"
    assert "custom_id" not in board.toml["mpflash"]


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_downloads_backend_compatible_firmware_before_flash(
    mock_config,
    mock_flash_mcu,
):
    """If firmware suffix is incompatible, refresh downloads before backend handoff."""
    mock_config.firmware_folder = Path("/test/firmware")
    mock_flash_mcu.return_value = MagicMock()

    board = MPRemoteBoard("COM1")
    board.board = "RPI_PICO"
    board.board_id = "RPI_PICO"
    board.port = "rp2"
    board.serialport = "COM1"

    fw_uf2 = Firmware(
        board_id="RPI_PICO",
        version="1.28.0",
        port="rp2",
        firmware_file="rp2/RPI_PICO-v1.28.0-main.uf2",
    )
    task = FlashTask(board=board, firmware=fw_uf2)

    backend = MagicMock()
    backend.supported_formats = (".bin", ".hex", ".elf", ".axf")

    fw_elf = Firmware(
        board_id="RPI_PICO",
        version="1.28.0",
        port="rp2",
        firmware_file="rp2/RPI_PICO-v1.28.0.elf",
    )

    find_calls = {"count": 0}

    def fake_find_downloaded_firmware(*args, **kwargs):
        # First lookup pass returns no compatible files; second pass (after
        # download refresh) returns an .elf candidate.
        find_calls["count"] += 1
        if find_calls["count"] <= 4:
            return []
        return [fw_elf]

    def fake_exists(path_obj: Path):
        path_str = str(path_obj)
        # Block sibling fast-path files derived from the initially selected UF2.
        if "RPI_PICO-v1.28.0-main" in path_str:
            return False
        return True

    with (
        patch("mpflash.flash.get_backend", return_value=backend),
        patch(
            "mpflash.flash.find_downloaded_firmware",
            side_effect=fake_find_downloaded_firmware,
        ),
        patch("mpflash.download.download", return_value=1) as mock_download,
        patch("pathlib.Path.exists", autospec=True, side_effect=fake_exists),
    ):
        result = flash_tasks(
            [task],
            erase=False,
            bootloader=BootloaderMethod.AUTO,
            method=FlashMethod.PYOCD,
        )

    assert len(result) == 1
    mock_download.assert_called_once()
    _, kwargs = mock_flash_mcu.call_args
    assert kwargs["fw_file"].name.endswith(".elf")


@patch("mpflash.flash.flash_mcu")
@patch("mpflash.flash.config")
def test_flash_tasks_raises_when_backend_has_no_compatible_firmware(
    mock_config,
    mock_flash_mcu,
):
    """Explicit backend should fail before handoff if no compatible firmware exists."""
    mock_config.firmware_folder = Path("/test/firmware")

    board = MPRemoteBoard("COM1")
    board.board = "RPI_PICO"
    board.board_id = "RPI_PICO"
    board.port = "rp2"
    board.serialport = "COM1"

    fw_uf2 = Firmware(
        board_id="RPI_PICO",
        version="1.28.0",
        port="rp2",
        firmware_file="rp2/RPI_PICO-v1.28.0.uf2",
    )
    task = FlashTask(board=board, firmware=fw_uf2)

    backend = MagicMock()
    backend.supported_formats = (".bin", ".hex", ".elf", ".axf")

    with (
        patch("mpflash.flash.get_backend", return_value=backend),
        patch("mpflash.flash.find_downloaded_firmware", return_value=[]),
        patch("mpflash.download.download", return_value=1),
    ):
        with pytest.raises(MPFlashError, match="No firmware matching backend"):
            flash_tasks(
                [task],
                erase=False,
                bootloader=BootloaderMethod.AUTO,
                method=FlashMethod.PYOCD,
            )

    mock_flash_mcu.assert_not_called()


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
