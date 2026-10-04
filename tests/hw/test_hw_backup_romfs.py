"""Hardware-in-the-loop ROMFS backup and restore round trip.

Needs a MicroPython 1.25+ board that has a ROMFS partition with an image deployed (it is skipped
otherwise). The test deploys a different image with ``mpremote romfs deploy``, restores the backup and
checks that the image is byte-identical again:

    uv run pytest --HIL COM18 tests/hw/test_hw_backup_romfs.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from mpflash.backup.bundle import read_bundle
from mpflash.backup.models import ComponentKind
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = [pytest.mark.hardware, pytest.mark.hw_mpremote]


def image_sha(bundle_root: Path) -> str:
    return hashlib.sha256((bundle_root / "artifacts" / "romfs.img").read_bytes()).hexdigest()


def deploy_other_image(port: str, folder: Path) -> None:
    folder.mkdir()
    (folder / "mpflash_hil.txt").write_text("a different ROMFS", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "mpremote", "connect", port, "romfs", "deploy", str(folder)], check=True, timeout=120)


def test_romfs_backup_survives_damage_and_restores_byte_for_byte(hw_mpremote_port, mpflash_db, tmp_path):
    mcu = MPRemoteBoard(hw_mpremote_port, update=False)
    mcu.get_mcu_info(timeout=15)
    try:
        plan = plan_backup(mcu, [ComponentKind.ROMFS])
    except MPFlashError as error:
        pytest.skip(f"The board has no ROMFS image to back up: {error}")

    original = run_backup(mcu, plan, tmp_path / "original")
    bundle = read_bundle(original)
    bundle.verify()
    (artifact,) = bundle.manifest.artifacts
    assert artifact.component is ComponentKind.ROMFS and artifact.length == artifact.size > 0

    deploy_other_image(mcu.serialport, tmp_path / "other")
    mcu.get_mcu_info(timeout=15)
    damaged = run_backup(mcu, plan_backup(mcu, [ComponentKind.ROMFS]), tmp_path / "damaged")
    assert image_sha(damaged) != image_sha(original)

    restore = plan_restore(bundle, mcu)
    assert any("ROMFS" in line for line in restore.lines)
    run_restore(restore, mcu)

    after = run_backup(mcu, plan_backup(mcu, [ComponentKind.ROMFS]), tmp_path / "after")
    assert image_sha(after) == image_sha(original)
