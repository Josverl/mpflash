"""Ports and boards that can be flashed with OpenOCD, and the OpenOCD target file each one uses."""

from __future__ import annotations

PORT_TARGETS: dict[str, dict[str, str]] = {
    "psoc-edge": {"KIT_PSE84_AI": "pse84xgxs2.cfg"},
}
"""Port -> board id -> target file below ``target/infineon/`` in the OpenOCD scripts."""


def target_for_board(port: str, board_id: str) -> str | None:
    """Return the target file for ``board_id`` on ``port``, ignoring a ``-VARIANT`` suffix; None if unknown."""
    boards = PORT_TARGETS.get(port, {})
    if board_id in boards:
        return boards[board_id]
    # Longest key first so a board name that prefixes another cannot shadow it.
    for board in sorted(boards, key=len, reverse=True):
        if board_id.startswith(f"{board}-"):
            return boards[board]
    return None
