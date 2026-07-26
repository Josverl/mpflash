"""Enter bootloader via ``mpremote bootloader`` (machine.bootloader())."""

from __future__ import annotations

from mpflash.bootloader.base import BootloaderActivator
from mpflash.bootloader.registry import register
from mpflash.logger import log
from mpflash.mpremoteboard import MPRemoteBoard


def enter_bootloader_mpy(mcu: MPRemoteBoard, timeout: int = 10):
    """Enter the bootloader mode for the board using mpremote and micropython on the board."""
    log.info(f"Attempting bootloader on {mcu.serialport} using 'mpremote bootloader'")
    mcu.run_command("bootloader", timeout=timeout)
    # todo: check if mpremote command was successful
    return True


class MicroPythonActivator(BootloaderActivator):
    """Send ``machine.bootloader()`` via mpremote."""

    name = "mpy"

    def activate(self, mcu: MPRemoteBoard, *, timeout: int = 10) -> bool:
        return enter_bootloader_mpy(mcu, timeout=timeout)


register(MicroPythonActivator())
