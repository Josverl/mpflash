"""STM32 DFU flash backend (pydfu)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Tuple

from mpflash.common import BootloaderMethod
from mpflash.errors import MPFlashError
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register
from mpflash.logger import log

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard


class DFUBackend(FlashBackend):
    """Bootloader + USB DFU backend for STM32 firmware."""

    name = "dfu"
    supported_ports = frozenset({"stm32"})
    supported_formats = (".dfu", ".bin")
    supported_platforms = frozenset(
        {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
    )
    requires_bootloader = True
    priority = 10

    preferred_bootloaders: Tuple[str, ...] = ("touch1200", "mpy", "manual")

    def is_board_ready(self, mcu: "MPRemoteBoard") -> bool:
        import time
        if _is_windows():
            driver_installed, status = _check_for_stm32_bootloader_device()
            if not driver_installed:
                log.warning("STM32  BOOTLOADER device not found.")
                return False
            if status != "OK":
                log.warning(f"STM32 BOOTLOADER device found, Device status: {status}")
                log.error(
                    "Please use Zadig to install a WinUSB (libusb)  driver.\n"
                    "https://github.com/pbatard/libwdi/wiki/Zadig"
                )
                return False
        # Poll for DFU device for up to 3 seconds
        max_wait = 3.0
        poll_interval = 0.25
        waited = 0.0
        while waited < max_wait:
            if _check_dfu_devices():
                return True
            time.sleep(poll_interval)
            waited += poll_interval
        return False

    def flash(self, ctx: FlashContext) -> FlashResult:
        from mpflash.flash.builtins.dfu import flash_stm32

        services = ctx.services
        if services is None:
            raise MPFlashError("DFU backend requires FlashContext.services")

        bootloader = ctx.bootloader or BootloaderMethod.AUTO
        if not services.enter_bootloader(ctx.mcu, bootloader, backend=self):
            return FlashResult(
                success=False,
                backend=self.name,
                message=(
                    f"Failed to enter bootloader for {ctx.mcu.board} on "
                    f"{ctx.mcu.serialport}"
                ),
            )

        updated = flash_stm32(ctx.mcu, ctx.fw_file, erase=ctx.erase)
        return FlashResult(
            success=updated is not None,
            mcu=updated,
            backend=self.name,
        )


def _is_windows() -> bool:
    """Return True when running on Windows."""
    return os.name == "nt"


def _check_dfu_devices() -> bool:
    """Check if there are any DFU devices connected."""
    # JIT import
    from mpflash.flash.builtins.dfu.stm32_dfu import dfu_init
    from mpflash.vendor.pydfu import get_dfu_devices

    backend = dfu_init()
    kwargs = {}
    if backend is not None:
        kwargs["backend"] = backend
    devices = get_dfu_devices(**kwargs)
    return len(devices) > 0


def _check_for_stm32_bootloader_device():
    import win32com.client

    wmi = win32com.client.GetObject("winmgmts:")
    for usb_device in wmi.InstancesOf("Win32_PnPEntity"):
        try:
            if str(usb_device.Name).strip() in {
                "STM32  BOOTLOADER",
                "STM BOOTLOADER",
            }:
                return True, usb_device.Status
        except Exception:
            pass
    return False, "Not found."


register(DFUBackend())
