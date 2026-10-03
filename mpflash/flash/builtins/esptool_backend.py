"""ESP32 / ESP8266 esptool flash backend."""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from mpflash.common import BootloaderMethod
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register
from mpflash.flash.services import default_services


_ESPRESSIF_USB_VID = 0x303A
_USB_ID = Tuple[Optional[int], Optional[int], Optional[str]]


def _serial_devices() -> Dict[str, _USB_ID]:
    from serial.tools.list_ports import comports

    return {port.device.casefold(): (port.vid, port.pid, port.serial_number) for port in comports()}


def _wait_for_native_usb_bootloader(previous: Dict[str, _USB_ID], timeout: float = 10) -> Optional[str]:
    """Return the single Espressif port added or changed after bootloader entry."""
    from serial.tools.list_ports import comports

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = [
            port.device
            for port in comports()
            if port.vid == _ESPRESSIF_USB_VID and previous.get(port.device.casefold()) != (port.vid, port.pid, port.serial_number)
        ]
        if len(candidates) == 1:
            return candidates[0]
        time.sleep(0.2)
    return None


class EsptoolBackend(FlashBackend):
    """esptool.py backend for ESP32 / ESP8266 ``.bin`` firmware.

    UART bridges use esptool's automatic reset. Espressif native USB devices
    first enter the ROM bootloader through MicroPython and re-enumerate.
    """

    name = "esptool"
    supported_ports = frozenset({"esp32", "esp8266"})
    supported_formats = (".bin",)
    supported_platforms = frozenset({Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2})
    requires_bootloader = False
    priority = 10

    def flash(self, ctx: FlashContext) -> FlashResult:
        from mpflash.flash.builtins.esp import flash_esp

        if getattr(ctx.mcu, "vid", 0) == _ESPRESSIF_USB_VID:
            services = ctx.services or default_services
            previous = _serial_devices()
            bootloader = ctx.bootloader or BootloaderMethod.AUTO
            if not services.enter_bootloader(
                ctx.mcu,
                bootloader,
                wait_after=0,
                backend=self,
            ):
                return FlashResult(
                    success=False,
                    backend=self.name,
                    message=f"Failed to enter the ROM bootloader on {ctx.mcu.serialport}",
                )
            bootloader_port = _wait_for_native_usb_bootloader(previous)
            if bootloader_port is None:
                return FlashResult(
                    success=False,
                    backend=self.name,
                    message="Could not identify the re-enumerated Espressif USB bootloader",
                )
            ctx.mcu.serialport = bootloader_port

        # Pull only the keys the esp backend understands from options to avoid
        # smuggling unrelated kwargs through.
        passthrough = {
            k: ctx.options[k]
            for k in (
                "flash_mode",
                "flash_size",
                "retry_on_error",
                "retry_baud",
                "retry_flash_mode",
            )
            if k in ctx.options
        }
        updated = flash_esp(ctx.mcu, fw_file=ctx.fw_file, erase=ctx.erase, **passthrough)
        return FlashResult(
            success=updated is not None,
            mcu=updated,
            backend=self.name,
        )


register(EsptoolBackend())
