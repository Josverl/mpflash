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
