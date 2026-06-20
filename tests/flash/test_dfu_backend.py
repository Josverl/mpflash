from pathlib import Path
import types

import pytest

from mpflash.common import BootloaderMethod
from mpflash.errors import MPFlashError
from mpflash.flash.builtins.dfu_backend import DFUBackend, _check_dfu_devices
from mpflash.flash.context import FlashContext
from mpflash.mpremoteboard import MPRemoteBoard


def _mcu(port="COM1"):
    mcu = MPRemoteBoard(port)
    mcu.port = "stm32"
    mcu.board = "PYBV11"
    mcu.serialport = port
    return mcu


def test_is_board_ready_windows_driver_missing(mocker):
    backend = DFUBackend()
    mocker.patch("mpflash.flash.builtins.dfu_backend._is_windows", return_value=True)
    mocker.patch("mpflash.flash.builtins.dfu_backend._check_for_stm32_bootloader_device", return_value=(False, "Not found"))
    assert backend.is_board_ready(_mcu()) is False


def test_is_board_ready_windows_driver_wrong_status(mocker):
    backend = DFUBackend()
    mocker.patch("mpflash.flash.builtins.dfu_backend._is_windows", return_value=True)
    mocker.patch("mpflash.flash.builtins.dfu_backend._check_for_stm32_bootloader_device", return_value=(True, "Error"))
    assert backend.is_board_ready(_mcu()) is False


def test_is_board_ready_polls_until_detected(mocker):
    backend = DFUBackend()
    mocker.patch("mpflash.flash.builtins.dfu_backend._is_windows", return_value=False)
    m_check = mocker.patch("mpflash.flash.builtins.dfu_backend._check_dfu_devices", side_effect=[False, False, True])
    m_sleep = mocker.patch("time.sleep")

    assert backend.is_board_ready(_mcu()) is True
    assert m_check.call_count == 3
    assert m_sleep.call_count == 2


def test_flash_requires_services(tmp_path):
    backend = DFUBackend()
    fw = tmp_path / "firmware.dfu"
    fw.write_bytes(b"x")
    ctx = FlashContext(mcu=_mcu(), fw_file=fw, erase=False, bootloader=BootloaderMethod.AUTO, options={}, services=None)

    with pytest.raises(MPFlashError, match="requires FlashContext.services"):
        backend.flash(ctx)


def test_flash_returns_failure_if_bootloader_not_entered(mocker, tmp_path):
    backend = DFUBackend()
    fw = tmp_path / "firmware.dfu"
    fw.write_bytes(b"x")

    services = mocker.Mock()
    services.enter_bootloader.return_value = False
    ctx = FlashContext(mcu=_mcu(), fw_file=fw, erase=False, bootloader=BootloaderMethod.AUTO, options={}, services=services)

    result = backend.flash(ctx)

    assert result.success is False
    assert result.backend == "dfu"


def test_flash_success_path(mocker, tmp_path):
    backend = DFUBackend()
    fw = tmp_path / "firmware.dfu"
    fw.write_bytes(b"x")

    services = mocker.Mock()
    services.enter_bootloader.return_value = True

    updated = _mcu("COM9")
    mocker.patch("mpflash.flash.builtins.dfu.flash_stm32", return_value=updated)

    ctx = FlashContext(mcu=_mcu(), fw_file=fw, erase=True, bootloader=BootloaderMethod.AUTO, options={}, services=services)
    result = backend.flash(ctx)

    assert result.success is True
    assert result.mcu is updated


def test_check_dfu_devices_handles_backend(mocker):
    mocker.patch("mpflash.flash.builtins.dfu.stm32_dfu.dfu_init", return_value="backend")
    m_get = mocker.patch("mpflash.vendor.pydfu.get_dfu_devices", return_value=[object()])

    assert _check_dfu_devices() is True
    m_get.assert_called_once_with(backend="backend")


def test_check_dfu_devices_without_backend(mocker):
    mocker.patch("mpflash.flash.builtins.dfu.stm32_dfu.dfu_init", return_value=None)
    m_get = mocker.patch("mpflash.vendor.pydfu.get_dfu_devices", return_value=[])

    assert _check_dfu_devices() is False
    m_get.assert_called_once_with()


def test_check_for_stm32_bootloader_device(mocker):
    device = type("D", (), {"Name": "STM32  BOOTLOADER", "Status": "OK"})
    wmi = mocker.Mock()
    wmi.InstancesOf.return_value = [device]
    client = types.SimpleNamespace(GetObject=lambda _: wmi)
    win32com = types.SimpleNamespace(client=client)
    mocker.patch.dict("sys.modules", {"win32com": win32com, "win32com.client": client})

    from mpflash.flash.builtins.dfu_backend import _check_for_stm32_bootloader_device

    found, status = _check_for_stm32_bootloader_device()
    assert found is True
    assert status == "OK"
