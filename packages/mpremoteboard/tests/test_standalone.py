"""Tests for the independently importable board API."""

import subprocess
import sys

import mpremoteboard
import pytest


def test_package_import_does_not_import_mpflash():
    script = """
import importlib.abc
import sys

class BlockMPFlash(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mpflash" or fullname.startswith("mpflash."):
            raise AssertionError(f"unexpected MPFlash import: {fullname}")
        return None

sys.meta_path.insert(0, BlockMPFlash())
import mpremoteboard
assert not any(name == "mpflash" or name.startswith("mpflash.") for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


def test_raw_probe_keeps_reset_opt_in(monkeypatch: pytest.MonkeyPatch):
    board = mpremoteboard.MPRemoteBoard("COM42")
    commands: list[list[str]] = []
    raw_info = (
        "{'family': 'micropython', 'version': '1.27.0', 'build': '', 'port': 'rp2', "
        "'cpu': 'RP2040', 'arch': 'armv6m', 'mpy': 'v6.3', 'board': 'RPI_PICO', "
        "'board_id': '', 'variant': '', 'description': 'Raspberry Pi Pico'}"
    )

    def fake_run(command: list[str], timeout: int, log_errors: bool, no_info: bool, **kwargs) -> tuple[int, list[str]]:
        commands.append(command)
        if command[-1].endswith("mpy_fw_info.py"):
            return 0, [raw_info]
        return 1, []

    monkeypatch.setattr(board, "_run", fake_run)
    board.get_mcu_info()

    assert board.board_id == "RPI_PICO"
    assert board.port == "rp2"
    assert len(commands) == 2
    assert all("soft-reset" not in command for command in commands)
