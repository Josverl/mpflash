"""Smoke tests that exercise each flash backend against real hardware.

These tests are skipped unless the matching ``MPFLASH_HW_*`` environment
variables are set; see ``tests/hw/conftest.py``. Each test is intentionally
minimal — a single happy-path call into :func:`mpflash.flash.flash_mcu` — so
the HW matrix runs quickly and keeps regressions isolated to one backend.
"""

from __future__ import annotations

import pytest

from mpflash.common import BootloaderMethod, FlashMethod
from mpflash.flash import flash_mcu


pytestmark = pytest.mark.hardware


@pytest.mark.hw_uf2
def test_uf2_backend_flashes_board(hw_board, hw_uf2_firmware):
    """Flash a UF2-capable board (rp2 / samd / nrf) via the UF2 backend."""
    updated = flash_mcu(
        hw_board,
        fw_file=hw_uf2_firmware,
        erase=False,
        bootloader=BootloaderMethod.AUTO,
        method=FlashMethod.UF2,
    )
    assert updated is not None, "UF2 flash returned no updated board"


@pytest.mark.hw_dfu
def test_dfu_backend_flashes_board(hw_board, hw_dfu_firmware):
    """Flash an STM32 board via the DFU backend."""
    updated = flash_mcu(
        hw_board,
        fw_file=hw_dfu_firmware,
        erase=False,
        bootloader=BootloaderMethod.AUTO,
        method=FlashMethod.DFU,
    )
    assert updated is not None, "DFU flash returned no updated board"


@pytest.mark.hw_esptool
def test_esptool_backend_flashes_board(hw_board, hw_esp_firmware):
    """Flash an ESP32 / ESP8266 board via the esptool backend."""
    updated = flash_mcu(
        hw_board,
        fw_file=hw_esp_firmware,
        erase=False,
        method=FlashMethod.ESPTOOL,
    )
    assert updated is not None, "esptool flash returned no updated board"


@pytest.mark.hw_pyocd
def test_pyocd_backend_flashes_board(hw_board, hw_pyocd_firmware, hw_pyocd_probe):
    """Flash any Cortex-M board via pyOCD using the configured probe."""
    updated = flash_mcu(
        hw_board,
        fw_file=hw_pyocd_firmware,
        erase=False,
        method=FlashMethod.PYOCD,
        probe_id=hw_pyocd_probe,
    )
    assert updated is not None, "pyOCD flash returned no updated board"
