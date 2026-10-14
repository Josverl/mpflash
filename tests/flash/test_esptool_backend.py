from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mpflash.common import BootloaderMethod
from mpflash.errors import MPFlashError
from mpflash.flash.builtins.esptool_backend import EsptoolBackend
from mpflash.flash.context import FlashContext
from mpflash.flash.services import FlashServices, default_services
from mpflash.mpremoteboard import MPRemoteBoard


@pytest.fixture(autouse=True)
def mock_serial_ports(mocker: MockerFixture) -> None:
    mocker.patch("serial.tools.list_ports.grep", return_value=[])
    mocker.patch("serial.tools.list_ports.comports", return_value=[])


def _mcu(*, board: str, cpu: str, port: str, vid: int, pid: int) -> MPRemoteBoard:
    mcu = MPRemoteBoard("COM17")
    mcu.board = board
    mcu.cpu = cpu
    mcu.port = port
    mcu.vid = vid
    mcu.pid = pid
    return mcu


def _context(
    mcu: MPRemoteBoard,
    services: FlashServices | None,
    tmp_path: Path,
    bootloader: BootloaderMethod | None = BootloaderMethod.AUTO,
) -> FlashContext:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"firmware")
    return FlashContext(mcu=mcu, fw_file=firmware, bootloader=bootloader, services=services)


@pytest.mark.parametrize(
    "board,cpu,port,vid,pid",
    [
        ("ESP32_GENERIC_C5", "ESP32-C5", "esp32", 0x303A, 0x1001),
        ("ESP32_GENERIC_S2", "ESP32S2", "esp32", 0x303A, 0x4001),
        ("ESP32_GENERIC_S3", "ESP32S3", "esp32", 0x303A, 0x1001),
        ("ESP32_GENERIC", "ESP32", "esp32", 0x10C4, 0xEA60),
        ("ESP8266_GENERIC", "ESP8266", "esp8266", 0x1A86, 0x7523),
    ],
)
@pytest.mark.parametrize("bootloader", [*BootloaderMethod, None])
@pytest.mark.parametrize("inject_services", [False, True])
def test_flash_delegates_bootloader_entry_to_esptool(
    mocker: MockerFixture,
    tmp_path: Path,
    board: str,
    cpu: str,
    port: str,
    vid: int,
    pid: int,
    bootloader: BootloaderMethod | None,
    inject_services: bool,
) -> None:
    mcu = _mcu(board=board, cpu=cpu, port=port, vid=vid, pid=pid)
    services = FlashServices() if inject_services else None
    enter_bootloader = mocker.patch.object(services or default_services, "enter_bootloader", return_value=False)
    serial_devices = mocker.patch("serial.tools.list_ports.comports", return_value=[])
    flash_esp = mocker.patch("mpflash.flash.builtins.esp.flash_esp", return_value=mcu)
    ctx = _context(mcu, services, tmp_path, bootloader)
    backend = EsptoolBackend()

    result = backend.flash(ctx)

    assert backend.requires_bootloader is False
    assert result.success is True
    assert result.mcu is mcu
    assert result.backend == "esptool"
    assert mcu.serialport == "COM17"
    enter_bootloader.assert_not_called()
    serial_devices.assert_not_called()
    flash_esp.assert_called_once_with(mcu, fw_file=ctx.fw_file, erase=False)


@pytest.mark.parametrize("erase", [False, True])
def test_flash_preserves_erase_and_supported_options(mocker: MockerFixture, tmp_path: Path, erase: bool) -> None:
    mcu = _mcu(board="ESP32_GENERIC_C5", cpu="ESP32-C5", port="esp32", vid=0x303A, pid=0x1001)
    mocker.patch.object(default_services, "enter_bootloader", return_value=False)
    flash_esp = mocker.patch("mpflash.flash.builtins.esp.flash_esp", return_value=mcu)
    ctx = _context(mcu, None, tmp_path)
    ctx.erase = erase
    supported_options = {
        "flash_mode": "dio",
        "flash_size": "4MB",
        "retry_on_error": False,
        "retry_baud": 115_200,
        "retry_flash_mode": "dout",
    }
    ctx.options = {**supported_options, "probe_id": "unrelated"}

    result = EsptoolBackend().flash(ctx)

    assert result.success is True
    flash_esp.assert_called_once_with(mcu, fw_file=ctx.fw_file, erase=erase, **supported_options)


def test_flash_reports_esptool_failure(mocker: MockerFixture, tmp_path: Path) -> None:
    mcu = _mcu(board="ESP32_GENERIC_C5", cpu="ESP32-C5", port="esp32", vid=0x303A, pid=0x1001)
    mocker.patch.object(default_services, "enter_bootloader", return_value=False)
    flash_esp = mocker.patch("mpflash.flash.builtins.esp.flash_esp", return_value=None)
    ctx = _context(mcu, None, tmp_path)

    result = EsptoolBackend().flash(ctx)

    assert result.success is False
    assert result.mcu is None
    assert result.backend == "esptool"
    flash_esp.assert_called_once_with(mcu, fw_file=ctx.fw_file, erase=False)


def test_flash_propagates_esptool_error(mocker: MockerFixture, tmp_path: Path) -> None:
    mcu = _mcu(board="ESP32_GENERIC_C5", cpu="ESP32-C5", port="esp32", vid=0x303A, pid=0x1001)
    mocker.patch.object(default_services, "enter_bootloader", return_value=False)
    mocker.patch("mpflash.flash.builtins.esp.flash_esp", side_effect=MPFlashError("Connection failed"))

    with pytest.raises(MPFlashError, match="Connection failed"):
        EsptoolBackend().flash(_context(mcu, None, tmp_path))
