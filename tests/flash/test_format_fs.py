"""Tests for the ``--format`` filesystem reformat feature."""

import ast

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.format_fs import (
    FORMAT_SCRIPT,
    SUPPORTED_FORMAT_PORTS,
    format_filesystem,
)
from mpflash.mpremoteboard import MPRemoteBoard

pytestmark = pytest.mark.mpflash


def test_format_bdev_device_script_is_valid_python():
    """The on-device format script must be valid Python."""
    source = FORMAT_SCRIPT.read_text(encoding="utf-8")
    ast.parse(source)
    assert "mkfs" in source


def _load_format_bdev_namespace():
    """Exec the on-device format script without running its trailing main()."""
    source = FORMAT_SCRIPT.read_text(encoding="utf-8")
    idx = source.rfind("\nmain()")
    if idx != -1:
        source = source[:idx]
    namespace: dict = {}
    exec(compile(source, str(FORMAT_SCRIPT), "exec"), namespace)
    return namespace


class _FakeLfs2:
    """Stand-in VfsLfs2 whose constructor succeeds (fs already littlefs2)."""

    def __init__(self, bdev, **kwargs):
        pass


class _FailingLfs2:
    def __init__(self, bdev, **kwargs):
        raise OSError("not littlefs")


class _FakeFat:
    def __init__(self, bdev, **kwargs):
        pass


def test_detect_fs_without_vfsfat_does_not_crash():
    """_detect_fs must not raise AttributeError when VfsFat is missing (nrf)."""

    class _VfsNoFat:  # a vfs module lacking VfsFat, as on some nrf builds
        VfsLfs2 = _FakeLfs2

    detect = _load_format_bdev_namespace()["_detect_fs"]
    assert detect(_VfsNoFat(), object()) is _FakeLfs2


def test_detect_fs_falls_back_to_fat_when_present():
    """When the device holds a FAT filesystem, VfsFat is detected."""

    class _VfsBoth:
        VfsLfs2 = _FailingLfs2
        VfsFat = _FakeFat

    detect = _load_format_bdev_namespace()["_detect_fs"]
    assert detect(_VfsBoth(), object()) is _FakeFat


def _fakeboard(port="rp2", serialport="COM42"):
    board = MPRemoteBoard(serialport)
    board.connected = True
    board.port = port
    board.board_id = "RPI_PICO"
    return board


def test_format_filesystem_rejects_unsupported_port():
    board = _fakeboard(port="webassembly")
    with pytest.raises(MPFlashError, match="not supported"):
        format_filesystem(board)


def test_format_filesystem_success(mocker):
    board = _fakeboard(port="rp2")
    m_run = mocker.patch.object(board, "run_command", return_value=(0, ["FORMAT: done\n"]))

    assert format_filesystem(board) is True
    m_run.assert_called_once()
    # the board runs the device-side format script
    cmd = m_run.call_args.args[0]
    assert cmd[0] == "run"
    assert cmd[1].endswith("format_bdev.py")


def test_format_filesystem_device_error_raises(mocker):
    board = _fakeboard(port="rp2")
    mocker.patch.object(board, "run_command", return_value=(0, ["FORMAT: no filesystem block device found\n"]))

    with pytest.raises(MPFlashError, match="Failed to format"):
        format_filesystem(board)
