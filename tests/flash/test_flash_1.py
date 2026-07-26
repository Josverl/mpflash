from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mpflash.bootloader.activate import enter_bootloader
from mpflash.common import BootloaderMethod
from mpflash.db.models import Firmware
from mpflash.flash import flash_tasks
from mpflash.flash.worklist import FlashTask, FlashTaskList
from mpflash.mpboard_id import board_id
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = [pytest.mark.mpflash]


@pytest.mark.parametrize("bl_method", iter(BootloaderMethod))
def test_enter_bootloader(mocker: MockerFixture, bl_method):
    # test if each of the bootloaders can be called
    # test enter_bootloader
    board = MPRemoteBoard("COM1")
    board.port = "stm32"
    m_bl_mpy = mocker.patch("mpflash.bootloader.builtins.mpy.enter_bootloader_mpy", return_value=True)
    m_bl_man = mocker.patch("mpflash.bootloader.builtins.manual.enter_bootloader_manual", return_value=True)
    m_bl_tch = mocker.patch("mpflash.bootloader.builtins.touch1200.enter_bootloader_touch_1200bps", return_value=True)

    m_in_bl = mocker.patch("mpflash.bootloader.activate.in_bootloader", return_value=True)  # type: ignore

    m_sleep = mocker.patch("mpflash.bootloader.activate.time.sleep")
    enter_bootloader(board, method=bl_method)

    all_calls = m_bl_mpy.call_count + m_bl_man.call_count + m_bl_tch.call_count
    if bl_method == BootloaderMethod.NONE:
        # Nothing called , no wait
        assert all_calls == 0
    else:
        assert all_calls == 1
        m_sleep.assert_called_once_with(2)


def test_enter_bootloader_auto(mocker: MockerFixture):
    # test if each of the bootloaders is called as retry
    board = MPRemoteBoard("COM1")
    board.port = "stm32"
    # first 2 will fail
    m_bl_tch = mocker.patch("mpflash.bootloader.builtins.touch1200.enter_bootloader_touch_1200bps", return_value=False)
    m_bl_mpy = mocker.patch("mpflash.bootloader.builtins.mpy.enter_bootloader_mpy", return_value=False)
    m_bl_man = mocker.patch("mpflash.bootloader.builtins.manual.enter_bootloader_manual", return_value=True)

    m_in_bl = mocker.patch("mpflash.bootloader.activate.in_bootloader", return_value=True)  # type: ignore

    m_sleep = mocker.patch("mpflash.bootloader.activate.time.sleep")
    enter_bootloader(board, method=BootloaderMethod.AUTO)

    # ? All retries are called
    assert m_bl_tch.call_count == 1
    assert m_bl_mpy.call_count == 1
    assert m_bl_man.call_count == 1

    m_sleep.assert_called_once_with(2)


@pytest.mark.parametrize("bootloader", [BootloaderMethod.NONE, BootloaderMethod.MPY])
@pytest.mark.parametrize("port", ["esp32", "esp8266", "rp2", "stm32", "samd"])
def test_flash_tasks(mocker: MockerFixture, test_fw_path: Path, bootloader, port):
    m_flash_uf2 = mocker.patch("mpflash.flash.builtins.uf2.flash_uf2")
    m_flash_stm32 = mocker.patch("mpflash.flash.builtins.dfu.flash_stm32")
    m_flash_esp = mocker.patch("mpflash.flash.builtins.esp.flash_esp")
    m_mpr_run = mocker.patch("mpflash.bootloader.builtins.mpy.MPRemoteBoard.run_command")  # type: ignore
    m_bootloader = mocker.patch("mpflash.bootloader.activate.enter_bootloader")
    # use
    mocker.patch("mpflash.flash.config._firmware_folder", test_fw_path)
    board = MPRemoteBoard("COM1")
    board.port = "esp32"

    # Pick a firmware path with the right extension for the port so the
    # pluggable registry can route to the correct backend.
    port_fw = {
        "esp32": ("esp32", "ESP32_GENERIC-v1.22.2.bin"),
        "esp8266": ("esp32", "ESP32_GENERIC-v1.22.2.bin"),
        "rp2": ("rp2", "RPI_PICO_W-v1.22.2.uf2"),
        "samd": ("samd", "SEEED_WIO_TERMINAL-v1.22.2.uf2"),
        "stm32": ("stm32", "PYBV11-v1.22.2.dfu"),
    }
    fw_subdir, fw_name = port_fw[port]
    fw_full = test_fw_path / fw_subdir / fw_name
    fw_full.parent.mkdir(parents=True, exist_ok=True)
    if not fw_full.exists():
        fw_full.write_bytes(b"\x00")

    # Create FlashTask instead of WorkList tuple
    task = FlashTask(
        board=board,
        firmware=Firmware(
            board_id="ESP32_GENERIC",
            port="esp32",
            version="1.22.2",
            build="0",
            firmware_file=f"{fw_subdir}/{fw_name}",
        ),
    )
    tasks: FlashTaskList = [task]

    # test flash_tasks
    board.port = port
    result = flash_tasks(tasks, erase=False, bootloader=bootloader)
    assert result
    assert len(result) == 1
    if port in ["esp32", "esp8266"]:
        m_flash_esp.assert_called_once()
    else:
        m_flash_esp.assert_not_called()
    if port in ("rp2", "samd", "nrf"):
        m_flash_uf2.assert_called_once()
    else:
        m_flash_uf2.assert_not_called()
    if port == "stm32":
        m_flash_stm32.assert_called_once()
    else:
        m_flash_stm32.assert_not_called()

    if port in ["esp32", "esp8266"]:
        return
    # bootloader is always called - but not for esp32/esp8266
    m_bootloader.assert_called_once()
