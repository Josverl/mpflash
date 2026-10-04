"""Hardware-in-the-loop STM32 DfuSe raw-flash backup and restore round trip.

This rewrites the captured main-flash image and is destructive if interrupted. Use a disposable
STM32 board with ``dfu-util`` installed and its DFU USB driver configured.
"""

from __future__ import annotations

import hashlib

import pytest

from mpflash.backup.bundle import read_bundle
from mpflash.backup.models import ComponentKind
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = [pytest.mark.hardware, pytest.mark.hw_dfu]


@pytest.mark.usefixtures("mpflash_db")
def test_stm32_raw_flash_backup_and_restore_round_trip(hw_dfu_port, tmp_path):
    mcu = MPRemoteBoard(hw_dfu_port, update=False)
    mcu.get_mcu_info(timeout=15)

    original = run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), tmp_path / "original")
    original_image = original / "artifacts" / "flash.bin"
    expected_hash = hashlib.sha256(original_image.read_bytes()).hexdigest()

    plan = plan_restore(read_bundle(original), mcu)
    run_restore(plan, mcu)

    restored = run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), tmp_path / "restored")
    restored_image = restored / "artifacts" / "flash.bin"
    assert hashlib.sha256(restored_image.read_bytes()).hexdigest() == expected_hash
