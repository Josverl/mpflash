"""OpenOCD flash backend (PSoC Edge).

Programs the board over SWD through its KitProg3 probe using the Infineon build
of OpenOCD. Firmware is the ``.zip`` package published on micropython.org.

Only the ``psoc-edge`` port is supported and it is tested only on Infineon
boards (``KIT_PSE84_AI``); stock OpenOCD is rejected.
"""

from __future__ import annotations

import os

from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register
from mpflash.flash.services import default_services
from mpflash.logger import log


class OpenOCDBackend(FlashBackend):
    """Infineon OpenOCD backend for PSoC Edge ``.zip`` firmware packages."""

    name = "openocd"
    supported_ports = frozenset({"psoc-edge"})
    supported_formats = (".zip",)
    supported_platforms = frozenset({Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2})
    requires_bootloader = False
    priority = 10

    def is_available(self) -> bool:
        """True if an Infineon OpenOCD is configured, on PATH, or can be downloaded for this host."""
        # Lazy import keeps subprocess/requests helpers off the startup path.
        from mpflash.flash.builtins.openocd.download import download_supported
        from mpflash.flash.builtins.openocd.runner import ENV_VAR, find_openocd

        # An explicit MPFLASH_OPENOCD is validated in flash() so the user gets the precise error.
        return bool(os.environ.get(ENV_VAR)) or download_supported() or find_openocd() is not None

    def flash(self, ctx: FlashContext) -> FlashResult:
        """Optionally erase the filesystem, program the board over SWD, then wait for it to restart."""
        from mpflash.flash.builtins.openocd.psoc_edge import flash_psoc_edge
        from mpflash.flash.builtins.uf2.erase import erase_filesystem

        services = ctx.services or default_services

        # Programming leaves the filesystem untouched, so --erase wipes it over serial first.
        if ctx.erase and not erase_filesystem(ctx.mcu):
            log.warning(f"Could not erase the filesystem on {ctx.mcu.serialport} over serial; continuing without erase")

        flash_psoc_edge(
            ctx.mcu,
            fw_file=ctx.fw_file,
            probe_id=ctx.options.get("probe_id"),
            assume_yes=bool(ctx.options.get("assume_yes")),
        )
        services.wait_for_restart(ctx.mcu)
        return FlashResult(success=True, mcu=ctx.mcu, backend=self.name)


register(OpenOCDBackend())
