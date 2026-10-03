"""Hardware-in-the-loop VFS backup and restore round trip.

Run against any MicroPython board (this test only changes files it creates, then restores
the filesystem to match its own backup):

    uv run pytest --HIL COM31 tests/hw/test_hw_backup_vfs.py
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from mpflash.backup.bundle import read_bundle
from mpflash.backup.devicefs import open_device_fs
from mpflash.backup.models import ComponentKind
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = [pytest.mark.hardware, pytest.mark.hw_mpremote]

# Random-looking but deterministic, so a transfer error cannot cancel itself out.
PAYLOAD = bytes((i * 31 + 7) % 256 for i in range(6000))


def inventory_entries(bundle_root: Path) -> list:
    return json.loads((bundle_root / "artifacts" / "vfs-inventory.json").read_text(encoding="utf-8"))["entries"]


def writable_root(mcu: MPRemoteBoard) -> str:
    with open_device_fs(mcu.serialport, soft_reset=False) as fs:
        mounts = [m.path for m in fs.mounts() if "Rom" not in m.fstype and not m.path.startswith("/sd")]
    assert mounts, "board has no writable filesystem"
    return mounts[0].rstrip("/")


def test_vfs_backup_survives_damage_and_restores_exactly(hw_mpremote_port, mpflash_db, tmp_path):
    mcu = MPRemoteBoard(hw_mpremote_port, update=False)
    mcu.get_mcu_info(timeout=15)
    root = writable_root(mcu)

    # Give the filesystem some known content (including a binary file), then back it up.
    with open_device_fs(mcu.serialport) as fs:
        fs.write_file(f"{root}/mpflash_hil_binary.bin", PAYLOAD)
    bundle_root = run_backup(mcu, plan_backup(mcu, [ComponentKind.VFS]), tmp_path / "backups")
    before = inventory_entries(bundle_root)
    with zipfile.ZipFile(bundle_root / "artifacts" / "vfs.zip") as archive:
        assert archive.read(f"{root}/mpflash_hil_binary.bin".lstrip("/")) == PAYLOAD

    # Damage it: remove the binary, change nothing else, add a file and a directory tree.
    with open_device_fs(mcu.serialport) as fs:
        fs.remove_file(f"{root}/mpflash_hil_binary.bin")
        fs.mkdir(f"{root}/mpflash_hil_junk")
        fs.write_file(f"{root}/mpflash_hil_junk/extra.txt", b"extra")

    bundle = read_bundle(bundle_root)
    plan = plan_restore(bundle, mcu)
    assert any("DELETE 1 files and 1 directories" in line for line in plan.lines)
    run_restore(plan, mcu)

    # A fresh backup must describe exactly the same filesystem as the original one.
    after_root = run_backup(mcu, plan_backup(mcu, [ComponentKind.VFS]), tmp_path / "after")
    assert inventory_entries(after_root) == before

    # Leave the board as we found it.
    with open_device_fs(mcu.serialport) as fs:
        fs.remove_file(f"{root}/mpflash_hil_binary.bin")
