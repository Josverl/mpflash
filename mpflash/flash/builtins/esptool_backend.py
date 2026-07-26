"""ESP32 / ESP8266 esptool flash backend."""

from __future__ import annotations

from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register


class EsptoolBackend(FlashBackend):
    """esptool.py backend for ESP32 / ESP8266 ``.bin`` firmware.

    esptool drives the ROM bootloader directly over the serial port; no
    separate bootloader-entry step is needed.
    """

    name = "esptool"
    supported_ports = frozenset({"esp32", "esp8266"})
    supported_formats = (".bin",)
    supported_platforms = frozenset(
        {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
    )
    requires_bootloader = False
    priority = 10

    def flash(self, ctx: FlashContext) -> FlashResult:
        from mpflash.flash.builtins.esp import flash_esp

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
