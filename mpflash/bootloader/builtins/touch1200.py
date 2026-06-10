"""Enter bootloader by opening the serial port at 1200 baud (Arduino-style)."""

from __future__ import annotations

import time

import serial

from mpflash.bootloader.base import BootloaderActivator
from mpflash.bootloader.registry import register
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpremoteboard import MPRemoteBoard


def enter_bootloader_touch_1200bps(mcu: MPRemoteBoard, timeout: int = 10):
    """Touch the serial port at 1200 baud to trigger the bootloader."""
    if not mcu.serialport:
        raise MPFlashError("No serial port specified")
    log.info(f"Attempting bootloader on {mcu.serialport} using 'Touch 1200Bd'")
    try:
        com = serial.Serial(mcu.serialport, 1200, dsrdtr=True)
        com.rts = False  # required
        com.dtr = False  # might as well
        time.sleep(0.2)
        com.close()

    except serial.SerialException as e:
        log.exception(e)
        raise MPFlashError(f"pySerial error: {str(e)}") from e
    except Exception as e:
        log.exception(e)
        raise MPFlashError(f"Error: {str(e)}") from e

    # be optimistic
    return True


class Touch1200Activator(BootloaderActivator):
    """Open the serial port at 1200 baud to enter the bootloader."""

    name = "touch1200"

    def activate(self, mcu: MPRemoteBoard, *, timeout: int = 10) -> bool:
        return enter_bootloader_touch_1200bps(mcu, timeout=timeout)


register(Touch1200Activator())
