"""Tests for the independently importable board API."""

import subprocess
import sys
from importlib.metadata import requires

import mpremoteboard
import pytest
from packaging.requirements import Requirement


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
assert "sqlite3" not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


def test_package_metadata_has_only_core_dependencies():
    dependency_names = {Requirement(requirement).name for requirement in requires("mpremoteboard") or []}

    assert dependency_names == {"mpremote", "pyserial", "tomli", "tomli-w"}
    assert "mpflash" not in dependency_names


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

    def fail_on_local_file_access(*args, **kwargs):
        raise AssertionError(f"unexpected local file access: {args!r} {kwargs!r}")

    monkeypatch.setattr(board, "_run", fake_run)
    monkeypatch.setattr("builtins.open", fail_on_local_file_access)
    board.get_mcu_info()

    assert board.board_id == "RPI_PICO"
    assert board.port == "rp2"
    assert len(commands) == 2
    assert all("soft-reset" not in command and "resume" not in command for command in commands)


@pytest.mark.parametrize("soft_reset", [False, True])
def test_raw_command_resets_only_when_requested(soft_reset: bool, monkeypatch: pytest.MonkeyPatch):
    board = mpremoteboard.MPRemoteBoard("COM42")
    commands: list[list[str]] = []

    def fake_run(command: list[str], timeout: int, log_errors: bool, no_info: bool, **kwargs) -> tuple[int, list[str]]:
        commands.append(command)
        return 0, []

    monkeypatch.setattr(board, "_run", fake_run)
    board.run_command(["exec", "pass"], soft_reset=soft_reset)

    assert ("soft-reset" in commands[0]) is soft_reset
    assert "resume" not in commands[0]
