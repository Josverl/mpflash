from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from esptool import FatalError

from mpflash.flash.esp import _chip_params, flash_esp
from mpflash.mpremoteboard import MPRemoteBoard


@pytest.fixture
def mock_mcu():
    mcu = MagicMock(spec=MPRemoteBoard)
    mcu.port = "esp32"
    mcu.board = "ESP32_DEV"
    mcu.serialport = "/dev/ttyUSB0"
    mcu.cpu = "ESP32"
    mcu.version = "v1.0"
    return mcu


@pytest.fixture
def mock_esptool(mocker):
    """Mock the esptool.cmds functions used by flash_esp."""
    mock_loader = MagicMock()
    mock_loader.change_baud = MagicMock()

    # detect_chip returns a context manager that yields mock_loader
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_loader)
    mock_cm.__exit__ = MagicMock(return_value=False)

    mocker.patch("mpflash.flash.esp.espcmds.detect_chip", return_value=mock_cm)
    mocker.patch("mpflash.flash.esp.espcmds.run_stub", return_value=mock_loader)
    mock_erase = mocker.patch("mpflash.flash.esp.espcmds.erase_flash")
    mock_write = mocker.patch("mpflash.flash.esp.espcmds.write_flash")

    return {"loader": mock_loader, "erase": mock_erase, "write": mock_write}


# ---------------------------------------------------------------------------
# _chip_params helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cpu, expected_chip, expected_addr, expected_baud",
    [
        ("ESP32", "esp32", "0x1000", 921_600),
        ("ESP32C2", "esp32c2", "0x0", 921_600),
        ("ESP32S2", "esp32s2", "0x1000", 460_800),
        ("ESP32S3", "esp32s3", "0x0", 921_600),
        ("ESP32C3", "esp32c3", "0x0", 921_600),
        ("ESP32C6", "esp32c6", "0x0", 460_800),
        ("ESP8266", "esp8266", "0x0", 460_800),
    ],
)
def test_chip_params(cpu, expected_chip, expected_addr, expected_baud):
    chip, addr, baud = _chip_params(cpu)
    assert chip == expected_chip
    assert addr == expected_addr
    assert baud == expected_baud


# ---------------------------------------------------------------------------
# Guard-rail tests (no hardware mocking needed)
# ---------------------------------------------------------------------------


def test_flash_esp_unsupported_mcu(mock_mcu):
    mock_mcu.port = "unsupported"
    assert flash_esp(mock_mcu, Path("/path/to/firmware.bin")) is None


def test_flash_esp_unsupported_board(mock_mcu):
    mock_mcu.board = "ARDUINO_UNO"
    assert flash_esp(mock_mcu, Path("/path/to/firmware.bin")) is None


# ---------------------------------------------------------------------------
# Chip-specific parameter tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "port, cpu, expected_addr, expected_baud",
    [
        ("esp32", "ESP32", "0x1000", 921_600),
        ("esp32", "ESP32C2", "0x0", 921_600),
        ("esp32", "ESP32S2", "0x1000", 460_800),
        ("esp32", "ESP32S3", "0x0", 921_600),
        ("esp32", "ESP32C3", "0x0", 921_600),
        ("esp32", "ESP32C6", "0x0", 460_800),
        ("esp8266", "ESP8266", "0x0", 460_800),
    ],
)
def test_flash_esp_chips(mock_mcu, mock_esptool, port, cpu, expected_addr, expected_baud):
    """All ESP32 variants and ESP8266 should use compress=True."""
    mock_mcu.port = port
    mock_mcu.cpu = cpu
    fw_path = Path("/path/to/firmware.bin")

    result = flash_esp(mock_mcu, fw_path, erase=False)

    assert result == mock_mcu
    mock_esptool["loader"].change_baud.assert_called_once_with(expected_baud)
    mock_esptool["write"].assert_called_once_with(
        mock_esptool["loader"],
        [(int(expected_addr, 16), str(fw_path))],
        flash_mode="keep",
        flash_size="detect",
        force=True,
        compress=True,
    )


# ---------------------------------------------------------------------------
# Erase flag
# ---------------------------------------------------------------------------


def test_flash_esp_erase(mock_mcu, mock_esptool):
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=True)
    assert result == mock_mcu
    mock_esptool["erase"].assert_called_once_with(mock_esptool["loader"])
    mock_esptool["write"].assert_called_once()


def test_flash_esp_no_erase(mock_mcu, mock_esptool):
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)
    assert result == mock_mcu
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_called_once()


# ---------------------------------------------------------------------------
# Compression fallback
# ---------------------------------------------------------------------------


def test_flash_esp_compress_fallback(mock_mcu, mock_esptool):
    """If compressed write raises FatalError, retry with no_compress=True."""
    mock_esptool["write"].side_effect = [FatalError("compressed upload failed"), None]

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)

    assert result == mock_mcu
    assert mock_esptool["write"].call_count == 2
    first_call, second_call = mock_esptool["write"].call_args_list
    assert first_call.kwargs.get("compress") is True
    assert first_call.kwargs.get("force") is True
    assert second_call.kwargs.get("no_compress") is True
    assert second_call.kwargs.get("force") is True


def test_flash_esp_compress_fallback_also_fails(mock_mcu, mock_esptool):
    """If both compressed and uncompressed writes fail, return None."""
    mock_esptool["write"].side_effect = [
        FatalError("compressed failed"),
        FatalError("uncompressed also failed"),
    ]

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)
    assert result is None


# ---------------------------------------------------------------------------
# General exception handling
# ---------------------------------------------------------------------------


def test_flash_esp_exception(mock_mcu, mock_esptool):
    mock_esptool["write"].side_effect = Exception("Flashing error")
    assert flash_esp(mock_mcu, Path("/path/to/firmware.bin")) is None
