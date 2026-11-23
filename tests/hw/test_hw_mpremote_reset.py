"""Hardware-in-the-loop coverage for mpremote v1.30 reset behavior.

Run against any serial MicroPython board with:

    uv run pytest --HIL COM31 tests/hw/test_hw_mpremote_reset.py
"""

from __future__ import annotations

import pytest

from mpflash.mpremoteboard import OK, MPRemoteBoard

pytestmark = [pytest.mark.hardware, pytest.mark.hw_mpremote]

_SENTINEL = "_mpflash_reset_sentinel"


def _sentinel_exists(board: MPRemoteBoard, *, soft_reset: bool = False) -> bool:
    rc, output = board.run_command(
        ["exec", f"print('SENTINEL:', '{_SENTINEL}' in globals())"],
        soft_reset=soft_reset,
    )
    assert rc == OK, output
    return any(line.strip() == "SENTINEL: True" for line in output)


def test_default_preserves_state_and_soft_reset_clears_it(hw_mpremote_port):
    board = MPRemoteBoard(hw_mpremote_port, update=False)

    rc, output = board.run_command(["exec", f"{_SENTINEL} = object()"])
    assert rc == OK, output
    assert _sentinel_exists(board)
    assert not _sentinel_exists(board, soft_reset=True)


def test_get_mcu_info_starts_from_clean_interpreter(hw_mpremote_port, mpflash_db):
    board = MPRemoteBoard(hw_mpremote_port, update=False)
    rc, output = board.run_command(["exec", f"{_SENTINEL} = object()"])
    assert rc == OK, output

    board.get_mcu_info(timeout=15)

    assert board.connected
    assert not _sentinel_exists(board)


def test_reset_reconnects_without_polling_reset_loop(hw_mpremote_port, mpflash_db):
    board = MPRemoteBoard(hw_mpremote_port, update=False)
    board.get_mcu_info(timeout=15)

    board.run_command("reset", timeout=10, log_errors=False)
    board.connected = False

    assert board.wait_for_restart(timeout=20)
    assert board.connected
