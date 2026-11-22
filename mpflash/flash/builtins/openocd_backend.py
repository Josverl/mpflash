"""OpenOCD flash backend (Infineon).

Programs the board over SWD through its KitProg3 probe using the Infineon build
of OpenOCD. Firmware is the ``.zip`` package published on micropython.org.

Supported ports and boards are listed in ``openocd/targets.py``; stock OpenOCD is rejected.
"""

from __future__ import annotations

import os

from mpflash.flash.base import FlashBackend
from mpflash.flash.builtins.openocd.targets import PORT_TARGETS
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register
from mpflash.flash.services import default_services


class OpenOCDBackend(FlashBackend):
    """Infineon OpenOCD backend for MicroPython ``.zip`` firmware packages."""

    name = "openocd"
    supported_ports = frozenset(PORT_TARGETS)
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
        """Program the board over SWD (erasing the filesystem first if asked), then wait for it to restart."""
        from mpflash.flash.builtins.openocd.flash import flash_openocd

        services = ctx.services or default_services

        flash_openocd(
            ctx.mcu,
            fw_file=ctx.fw_file,
            probe_id=ctx.options.get("probe_id"),
            assume_yes=bool(ctx.options.get("assume_yes")),
            erase=ctx.erase,
        )
        services.wait_for_restart(ctx.mcu)
        return FlashResult(success=True, mcu=ctx.mcu, backend=self.name)


register(OpenOCDBackend())
