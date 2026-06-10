"""STM32 DFU flash backend (pydfu)."""

from __future__ import annotations

from mpflash.common import BootloaderMethod
from mpflash.errors import MPFlashError
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform
from mpflash.flash.registry import register


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

    def flash(self, ctx: FlashContext) -> FlashResult:
        from mpflash.flash.builtins.dfu import flash_stm32

        services = ctx.services
        if services is None:
            raise MPFlashError("DFU backend requires FlashContext.services")

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

        updated = flash_stm32(ctx.mcu, ctx.fw_file, erase=ctx.erase)
        return FlashResult(
            success=updated is not None,
            mcu=updated,
            backend=self.name,
        )


register(DFUBackend())
