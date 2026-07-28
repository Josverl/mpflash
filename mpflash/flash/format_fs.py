"""Reformat the internal MicroPython filesystem of a connected board.

Runs :mod:`mpflash.mpremoteboard.format_bdev` on the board via ``mpremote run``.
That script locates the port's filesystem block device (the same one
``_boot.py`` mounts), recreates an empty filesystem of the same type
(``VfsLfs2`` or ``VfsFat``) and remounts it, leaving the board on MicroPython.
"""

from __future__ import annotations

from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpremoteboard import HERE, MPRemoteBoard

FORMAT_SCRIPT = HERE / "format_bdev.py"

# Ports for which the internal-flash block device is known.
SUPPORTED_FORMAT_PORTS = frozenset({"rp2", "esp32", "esp8266", "samd", "stm32", "nrf"})

_OK_MARKER = "FORMAT: done"


def format_filesystem(mcu: MPRemoteBoard, *, timeout: int = 60) -> bool:
    """Reformat the internal filesystem of a connected board.

    Recreates an empty filesystem using the same filesystem type the board
    currently uses. The board must be connected and running MicroPython.

    Returns:
        True if the filesystem was reformatted.

    Raises:
        MPFlashError: If the port is unsupported or formatting fails.
    """
    if mcu.port not in SUPPORTED_FORMAT_PORTS:
        raise MPFlashError(
            f"--format is not supported for port {mcu.port!r} "
            f"(supported: {', '.join(sorted(SUPPORTED_FORMAT_PORTS))})"
        )
    log.info(f"Formatting filesystem on {mcu.board} on {mcu.serialport}")
    try:
        rc, output = mcu.run_command(
            ["run", str(FORMAT_SCRIPT)],
            timeout=timeout,
            resume=False,
            log_errors=True,
        )
    except Exception as e:  # noqa: BLE001 - normalize for callers
        raise MPFlashError(f"Failed to format filesystem on {mcu.serialport}: {e}") from e

    text = "".join(output)
    if _OK_MARKER not in text:
        raise MPFlashError(f"Failed to format filesystem on {mcu.serialport}: {text.strip() or 'unknown error'}")
    log.success(f"Formatted filesystem on {mcu.board} on {mcu.serialport}")
    return True
