"""Hardware-in-the-loop test for the serial-side filesystem erase.

Run with the ``--HIL <port>`` option, e.g.::

    uv run pytest --HIL COM31 tests/hw/test_hw_erase.py

The erase uses ``machine.reset()`` (not ``machine.bootloader()``), so the board
reboots into MicroPython with a fresh, empty filesystem and stays usable - no
firmware flash is needed to recover, which keeps this test self-contained.
"""

from __future__ import annotations

import pytest

from mpflash.flash.builtins.uf2.erase import SUPPORTED_PORTS, erase_filesystem
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = pytest.mark.hardware


def _listdir(mcu: MPRemoteBoard) -> str:
    """Return the current working directory listing reported by the board."""
    rc, out = mcu.run_command(["exec", "import os; print(os.listdir())"], resume=False)
    for line in out:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return stripped
    return ""


@pytest.mark.hw_uf2
def test_erase_filesystem_wipes_and_reconnects(hw_uf2_port, mpflash_db):
    """Seed a file, erase over serial, and confirm it is gone after reboot."""
    mcu = MPRemoteBoard(hw_uf2_port, update=False)
    mcu.get_mcu_info(timeout=15)
    assert mcu.port in SUPPORTED_PORTS, f"unsupported port for erase: {mcu.port}"

    # Seed a marker file on the board filesystem (in the current directory).
    mcu.run_command(
        ["exec", "f=open('hil_marker.txt','w'); f.write('erase me'); f.close()"],
        resume=False,
    )
    before = _listdir(mcu)
    assert "hil_marker.txt" in before, f"seed file missing before erase: {before}"

    # Erase the filesystem over serial; the board reboots into MicroPython.
    assert erase_filesystem(mcu) is True

    # The marker file must be gone from the fresh filesystem.
    after = _listdir(mcu)
    assert "hil_marker.txt" not in after, f"file survived erase: {after}"
