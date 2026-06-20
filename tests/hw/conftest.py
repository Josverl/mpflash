"""Shared fixtures and markers for hardware-in-the-loop flash backend tests.

Each marker (``hw_uf2``, ``hw_dfu``, ``hw_esptool``, ``hw_pyocd``) skips
unless its corresponding environment variable points at the connected board:

* ``MPFLASH_HW_UF2_PORT`` — serial port / volume of an RP2 or SAMD board.
* ``MPFLASH_HW_DFU_PORT`` — serial port of an STM32 board in DFU mode.
* ``MPFLASH_HW_ESP_PORT`` — serial port of an ESP32 / ESP8266 board.
* ``MPFLASH_HW_PYOCD_PROBE`` — unique-id of a CMSIS-DAP / J-Link probe.

Pair each with ``MPFLASH_HW_<MARKER>_FW`` to point at a firmware file on
disk. Tests are deliberately small (happy-path only) so a HW matrix run stays
fast.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest


def _env_port(name: str) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or None


def _env_fw(name: str) -> Optional[Path]:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    p = Path(value)
    if not p.exists():
        print(f"Warning: firmware file {p} does not exist")
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hw_uf2_port() -> str:
    port = _env_port("MPFLASH_HW_UF2_PORT")
    if not port:
        pytest.skip("Set MPFLASH_HW_UF2_PORT to run UF2 hardware tests")
    return port


@pytest.fixture
def hw_uf2_firmware() -> Path:
    fw = _env_fw("MPFLASH_HW_UF2_FW")
    if fw is None:
        pytest.skip("Set MPFLASH_HW_UF2_FW to a .uf2 firmware file")
    
    return fw


@pytest.fixture
def hw_dfu_port() -> str:
    port = _env_port("MPFLASH_HW_DFU_PORT")
    if not port:
        pytest.skip("Set MPFLASH_HW_DFU_PORT to run DFU hardware tests")
    return port


@pytest.fixture
def hw_dfu_firmware() -> Path:
    fw = _env_fw("MPFLASH_HW_DFU_FW")
    if fw is None:
        pytest.skip("Set MPFLASH_HW_DFU_FW to a .dfu or .bin firmware file")
    return fw


@pytest.fixture
def hw_esp_port() -> str:
    port = _env_port("MPFLASH_HW_ESP_PORT")
    if not port:
        pytest.skip("Set MPFLASH_HW_ESP_PORT to run esptool hardware tests")
    return port


@pytest.fixture
def hw_esp_firmware() -> Path:
    fw = _env_fw("MPFLASH_HW_ESP_FW")
    if fw is None:
        pytest.skip("Set MPFLASH_HW_ESP_FW to a .bin firmware file")
    return fw


@pytest.fixture
def hw_pyocd_probe() -> str:
    probe = _env_port("MPFLASH_HW_PYOCD_PROBE")
    if not probe:
        pytest.skip("Set MPFLASH_HW_PYOCD_PROBE to run pyOCD hardware tests")
    return probe


@pytest.fixture
def hw_pyocd_firmware() -> Path:
    fw = _env_fw("MPFLASH_HW_PYOCD_FW")
    if fw is None:
        pytest.skip("Set MPFLASH_HW_PYOCD_FW to a .bin / .hex / .elf firmware file")
    return fw


@pytest.fixture
def hw_board(request):
    """Construct an :class:`MPRemoteBoard` for the port fixture in this test.

    The actual port fixture is selected via ``request.getfixturevalue`` from
    the marker name, so individual tests do not need to wire it up.
    """
    from mpflash.mpremoteboard import MPRemoteBoard

    marker_to_fixture = {
        "hw_uf2": "hw_uf2_port",
        "hw_dfu": "hw_dfu_port",
        "hw_esptool": "hw_esp_port",
        "hw_pyocd": "hw_pyocd_probe",
    }
    for mark_name, fixture_name in marker_to_fixture.items():
        if request.node.get_closest_marker(mark_name):
            port = request.getfixturevalue(fixture_name)
            mcu = MPRemoteBoard(port, update=False)
            try:
                mcu.get_mcu_info()
            except Exception:
                pass
            return mcu
    pytest.skip("hw_board fixture requires a hw_* marker on the test")
