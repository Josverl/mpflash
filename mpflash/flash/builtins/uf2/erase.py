"""Serial-side filesystem erase for UF2 boards (rp2 / samd / nrf).

Runs :mod:`mpflash.mpremoteboard.erase_bdev` on the board via ``mpremote run``.
That script erases the filesystem block device and calls ``machine.reset()``, so
the board reboots into MicroPython with a fresh, empty filesystem. Entering the
UF2 bootloader is a separate step, keeping erase and bootloader entry
independent, and this is the single erase mechanism for all UF2 ports.
"""

from __future__ import annotations

from loguru import logger as log

from mpflash.mpremoteboard import HERE, MPRemoteBoard

ERASE_SCRIPT = HERE / "erase_bdev.py"

# Ports whose filesystem bdev supports this flow.
SUPPORTED_PORTS = frozenset({"rp2", "samd", "nrf"})


def erase_filesystem(mcu: "MPRemoteBoard", *, timeout: int = 60) -> bool:
    """Erase the filesystem over serial, leaving the board on MicroPython.

    The board reboots via ``machine.reset()`` with a fresh empty filesystem and
    reconnects on the same serial port; the caller then enters the bootloader as
    usual. Returns True when the erase ran and the board reconnected, False if it
    could not be driven over serial (for example the board is already in the
    bootloader).
    """
    if mcu.port not in SUPPORTED_PORTS:
        return False
    if not mcu.serialport or mcu.serialport.lower() == "auto":
        return False

    # Only drive the erase when the board is actually present as a serial port
    # running MicroPython. If the port is gone the board may already be in the
    # bootloader, where the filesystem cannot be erased over serial.
    try:
        present = any(mcu.serialport.casefold() == port.casefold() for port in MPRemoteBoard.connected_comports())
    except OSError:
        present = True
    if not present:
        log.debug(f"{mcu.serialport} is not a live serial port; cannot erase over serial")
        return False

    log.info(f"Erasing filesystem on {mcu.serialport} via block device.")
    try:
        # machine.reset() reboots the board, so the serial connection drops
        # mid-command; a non-zero rc or error here is expected, not a failure.
        mcu.run_command(
            ["run", str(ERASE_SCRIPT)],
            timeout=timeout,
            resume=False,
            log_errors=False,
        )
    except Exception as error:
        log.debug(f"erase_bdev run ended (expected on reset): {error}")

    # The board reboots into MicroPython with a fresh filesystem; wait for it.
    if mcu.wait_for_restart():
        log.success("Filesystem erased; board reconnected")
        return True
    log.warning("Board did not reconnect after filesystem erase")
    return False
