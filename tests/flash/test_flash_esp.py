from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from mpflash.flash.esp import flash_esp
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

def test_flash_esp_unsupported_mcu(mock_mcu):
    mock_mcu.port = "unsupported"
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"))
    assert result is None

def test_flash_esp_unsupported_board(mock_mcu):
    mock_mcu.board = "ARDUINO_UNO"
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"))
    assert result is None

@pytest.mark.parametrize("cpu, chip, start_addr, baud_rate", [
    ("ESP32", "esp32", "0x1000", "921600"),
    ("ESP32C2", "esp32c2", "0x1000", "921600"),
    ("ESP32S2", "esp32s2", "0x1000", "460800"),
    ("ESP32S3", "esp32s3", "0x0", "921600"),
    ("ESP32C3", "esp32c3", "0x0", "921600"),
    ("ESP32C6", "esp32c6", "0x0", "460800"),
])
@patch("esptool.main")
def test_flash_esp_different_chips(mock_esptool, mock_mcu, cpu, chip, start_addr, baud_rate):
    mock_mcu.cpu = cpu
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"))
    assert result == mock_mcu
    expected_cmd = f"esptool --chip {chip} --port {mock_mcu.serialport} -b {baud_rate} write_flash --flash_mode keep --flash_size detect --compress {start_addr} {Path('/path/to/firmware.bin')}".split()
    mock_esptool.assert_called_with(expected_cmd[1:])

@patch("esptool.main")
def test_flash_esp_erase(mock_esptool, mock_mcu):
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=True)
    assert result == mock_mcu
    assert mock_esptool.call_count == 2  # erase_flash and write_flash

@patch("esptool.main")
def test_flash_esp_no_erase(mock_esptool, mock_mcu):
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)
    assert result == mock_mcu
    assert mock_esptool.call_count == 1  # only write_flash

@patch("esptool.main")
def test_flash_esp_exception(mock_esptool, mock_mcu):
    mock_esptool.side_effect = Exception("Flashing error")
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"))
    assert result is None