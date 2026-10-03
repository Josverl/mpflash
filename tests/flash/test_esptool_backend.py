from pathlib import Path
from types import SimpleNamespace

from mpflash.common import BootloaderMethod
from mpflash.flash.builtins.esptool_backend import (
    EsptoolBackend,
    _serial_devices,
    _wait_for_native_usb_bootloader,
)
from mpflash.flash.context import FlashContext


def _mcu(*, serialport: str, vid: int):
    return SimpleNamespace(
        board="ESP32_GENERIC_S2",
        cpu="ESP32S2",
        pid=0x4001,
        port="esp32",
        serialport=serialport,
        vid=vid,
    )


def _context(mcu, services, tmp_path: Path) -> FlashContext:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"firmware")
    return FlashContext(
        mcu=mcu,
        fw_file=firmware,
        bootloader=BootloaderMethod.AUTO,
        services=services,
    )


def test_serial_devices_snapshots_usb_identity(mocker):
    port = SimpleNamespace(
        device="COM25",
        pid=0x4001,
        serial_number="F412FA813B8C0000",
        vid=0x303A,
    )
    mocker.patch("serial.tools.list_ports.comports", return_value=[port])

    assert _serial_devices() == {"com25": (0x303A, 0x4001, "F412FA813B8C0000")}


def test_wait_for_native_usb_bootloader_selects_changed_espressif_port(mocker):
    bootloader = SimpleNamespace(
        device="COM61",
        pid=0x0002,
        serial_number="0",
        vid=0x303A,
    )
    mocker.patch("serial.tools.list_ports.comports", return_value=[bootloader])

    port = _wait_for_native_usb_bootloader({"com17": (0x303A, 0x4001, "7CDFA11AB25E0000")})

    assert port == "COM61"


def test_wait_for_native_usb_bootloader_refuses_ambiguous_ports(mocker):
    ports = [
        SimpleNamespace(device="COM61", pid=0x0002, serial_number="0", vid=0x303A),
        SimpleNamespace(device="COM62", pid=0x0002, serial_number="0", vid=0x303A),
    ]
    mocker.patch("serial.tools.list_ports.comports", return_value=ports)
    mocker.patch(
        "mpflash.flash.builtins.esptool_backend.time.monotonic",
        side_effect=[0.0, 0.0, 1.0],
    )
    mocker.patch("mpflash.flash.builtins.esptool_backend.time.sleep")

    assert _wait_for_native_usb_bootloader({}, timeout=0.5) is None


def test_native_usb_flash_enters_bootloader_and_uses_new_port(mocker, tmp_path):
    backend = EsptoolBackend()
    mcu = _mcu(serialport="COM17", vid=0x303A)
    services = mocker.Mock()
    services.enter_bootloader.return_value = True
    mocker.patch(
        "mpflash.flash.builtins.esptool_backend._serial_devices",
        return_value={"com17": (0x303A, 0x4001, "7CDFA11AB25E0000")},
    )
    mocker.patch(
        "mpflash.flash.builtins.esptool_backend._wait_for_native_usb_bootloader",
        return_value="COM61",
    )
    flash_esp = mocker.patch(
        "mpflash.flash.builtins.esp.flash_esp",
        return_value=mcu,
    )

    result = backend.flash(_context(mcu, services, tmp_path))

    assert result.success is True
    assert mcu.serialport == "COM61"
    services.enter_bootloader.assert_called_once_with(
        mcu,
        BootloaderMethod.AUTO,
        wait_after=0,
        backend=backend,
    )
    flash_esp.assert_called_once()


def test_native_usb_flash_stops_when_bootloader_entry_fails(mocker, tmp_path):
    backend = EsptoolBackend()
    mcu = _mcu(serialport="COM17", vid=0x303A)
    services = mocker.Mock()
    services.enter_bootloader.return_value = False
    mocker.patch(
        "mpflash.flash.builtins.esptool_backend._serial_devices",
        return_value={"com17": (0x303A, 0x4001, "7CDFA11AB25E0000")},
    )
    flash_esp = mocker.patch("mpflash.flash.builtins.esp.flash_esp")

    result = backend.flash(_context(mcu, services, tmp_path))

    assert result.success is False
    assert "Failed to enter" in result.message
    flash_esp.assert_not_called()


def test_native_usb_flash_stops_when_bootloader_port_is_not_found(mocker, tmp_path):
    backend = EsptoolBackend()
    mcu = _mcu(serialport="COM25", vid=0x303A)
    services = mocker.Mock()
    services.enter_bootloader.return_value = True
    mocker.patch(
        "mpflash.flash.builtins.esptool_backend._serial_devices",
        return_value={"com25": (0x303A, 0x4001, "F412FA813B8C0000")},
    )
    mocker.patch(
        "mpflash.flash.builtins.esptool_backend._wait_for_native_usb_bootloader",
        return_value=None,
    )
    flash_esp = mocker.patch("mpflash.flash.builtins.esp.flash_esp")

    result = backend.flash(_context(mcu, services, tmp_path))

    assert result.success is False
    assert "Could not identify" in result.message
    flash_esp.assert_not_called()


def test_uart_flash_keeps_esptool_auto_reset(mocker, tmp_path):
    backend = EsptoolBackend()
    mcu = _mcu(serialport="COM27", vid=0x10C4)
    services = mocker.Mock()
    serial_devices = mocker.patch("mpflash.flash.builtins.esptool_backend._serial_devices")
    flash_esp = mocker.patch(
        "mpflash.flash.builtins.esp.flash_esp",
        return_value=mcu,
    )

    result = backend.flash(_context(mcu, services, tmp_path))

    assert result.success is True
    assert mcu.serialport == "COM27"
    services.enter_bootloader.assert_not_called()
    serial_devices.assert_not_called()
    flash_esp.assert_called_once()
