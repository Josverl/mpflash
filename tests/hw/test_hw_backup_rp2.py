"""Hardware-in-the-loop raw flash backup and restore round trip for an RP2040 board.

DESTRUCTIVE: sectors of the board's flash are rewritten (from its own backup). Use a disposable board:

    $env:MPFLASH_HW_UF2_PORT = "COM62"
    uv run pytest tests/hw/test_hw_backup_rp2.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mpflash.backup.bundle import read_bundle
from mpflash.backup.devicefs import open_device_fs
from mpflash.backup.models import ComponentKind
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = [pytest.mark.hardware, pytest.mark.hw_uf2]

MARKER = "/mpflash_hil_marker.txt"


def remove_marker(port: str) -> None:
    """Delete the marker file if present.

    A leftover from an aborted run would be captured by the 'original' backup and make the final
    comparison meaningless, so it is removed before the test and again afterwards.
    """
    with open_device_fs(port) as fs:
        if MARKER.lstrip("/") in [entry.name for entry in fs.listdir("/")]:
            fs.remove_file(MARKER)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flash_backup(mcu: MPRemoteBoard, out: Path) -> Path:
    return run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), out)


def test_rp2_flash_backup_survives_damage_and_restores_byte_for_byte(hw_uf2_port, mpflash_db, tmp_path):
    mcu = MPRemoteBoard(hw_uf2_port, update=False)
    mcu.get_mcu_info(timeout=15)
    assert mcu.port == "rp2" and mcu.cpu.upper() == "RP2040"

    remove_marker(mcu.serialport)
    try:
        original = flash_backup(mcu, tmp_path / "original")
        bundle = read_bundle(original)
        bundle.verify()
        (artifact,) = bundle.manifest.artifacts
        assert artifact.address == 0x10000000 and artifact.length == artifact.size > 0

        # Damage the board: write a file into its filesystem, which lives inside the flash image.
        with open_device_fs(mcu.serialport) as fs:
            fs.write_file(MARKER, b"this file is not in the backup")

        plan = plan_restore(bundle, mcu)
        assert any("flash sectors of 4 KiB" in line for line in plan.lines), plan.lines
        run_restore(plan, mcu)

        with open_device_fs(mcu.serialport, soft_reset=False) as fs:
            assert MARKER.lstrip("/") not in [entry.name for entry in fs.listdir("/")]
        after = flash_backup(mcu, tmp_path / "after")
        assert sha256(after / "artifacts" / "flash.bin") == sha256(original / "artifacts" / "flash.bin")
    finally:
        remove_marker(mcu.serialport)
