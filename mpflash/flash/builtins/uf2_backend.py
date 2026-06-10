"""UF2 flash backend (rp2 / samd / nrf).

Wraps :func:`mpflash.flash.builtins.uf2.flash_uf2`. Bootloader entry is performed
through ``ctx.services.enter_bootloader`` so a fake services bundle can
short-circuit it in tests.
"""

from __future__ import annotations

from mpflash.common import BootloaderMethod
from mpflash.errors import MPFlashError
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register


class UF2Backend(FlashBackend):
    """Bootloader + drive-copy backend for UF2 firmware."""

    name = "uf2"
    supported_ports = frozenset({"rp2", "samd", "nrf"})
    supported_formats = (".uf2",)
    supported_platforms = frozenset(
        {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
    )
    requires_bootloader = True
    priority = 10

    def flash(self, ctx: FlashContext) -> FlashResult:
        # Lazy import — keeps tenacity / psutil / blkinfo out of the startup path.
        from mpflash.flash.builtins.uf2 import flash_uf2

        services = ctx.services
        if services is None:
            raise MPFlashError("UF2 backend requires FlashContext.services")

        bootloader = ctx.bootloader or BootloaderMethod.AUTO
        if not services.enter_bootloader(ctx.mcu, bootloader):
            return FlashResult(
                success=False,
                backend=self.name,
                message=(
                    f"Failed to enter bootloader for {ctx.mcu.board} on "
                    f"{ctx.mcu.serialport}"
                ),
            )

        updated = flash_uf2(ctx.mcu, fw_file=ctx.fw_file, erase=ctx.erase)
        return FlashResult(
            success=updated is not None,
            mcu=updated,
            backend=self.name,
        )


register(UF2Backend())
