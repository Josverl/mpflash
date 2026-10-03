"""Hardware-in-the-loop raw flash backup and restore round trip for ESP32/ESP8266.

DESTRUCTIVE: the whole flash of the board is rewritten (with its own backup). Use a disposable
board connected through a UART bridge (not native USB):

    $env:MPFLASH_HW_ESP_PORT = "COM10"
    uv run pytest tests/hw/test_hw_backup_esp.py
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

pytestmark = [pytest.mark.hardware, pytest.mark.hw_esptool]

MARKER = "/mpflash_hil_marker.txt"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flash_backup(mcu: MPRemoteBoard, out: Path) -> Path:
    return run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), out)


def test_raw_flash_backup_survives_damage_and_restores_byte_for_byte(hw_esp_port, mpflash_db, tmp_path):
    mcu = MPRemoteBoard(hw_esp_port, update=False)
    mcu.get_mcu_info(timeout=15)

    original = flash_backup(mcu, tmp_path / "original")
    bundle = read_bundle(original)
    bundle.verify()
    (artifact,) = bundle.manifest.artifacts
    assert artifact.address == 0 and artifact.length == artifact.size > 0

    # Damage the board: add a file to its filesystem, which lives inside the flash image.
    with open_device_fs(mcu.serialport) as fs:
        fs.write_file(MARKER, b"this file is not in the backup")
    assert flash_backup(mcu, tmp_path / "damaged") != original
    damaged_hash = sha256(next((tmp_path / "damaged").iterdir()) / "artifacts" / "flash.bin")
    assert damaged_hash != sha256(original / "artifacts" / "flash.bin")

    plan = plan_restore(bundle, mcu)
    assert any("ENTIRE flash" in line for line in plan.lines)
    run_restore(plan, mcu)

    # The marker is gone and the flash is identical to the original image.
    with open_device_fs(mcu.serialport, soft_reset=False) as fs:
        assert MARKER.lstrip("/") not in [entry.name for entry in fs.listdir("/")]
    after = flash_backup(mcu, tmp_path / "after")
    assert sha256(after / "artifacts" / "flash.bin") == sha256(original / "artifacts" / "flash.bin")
