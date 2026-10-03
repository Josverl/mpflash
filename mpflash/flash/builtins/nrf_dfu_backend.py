"""Composite Serial-DFU plus UF2 backend for allowlisted nRF migrations."""

from __future__ import annotations

from typing import Optional, cast

from mpflash.errors import MPFlashError
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform, Reason
from mpflash.flash.registry import register


class NrfDfuBackend(FlashBackend):
    """Replace an allowlisted SoftDevice+bootloader, then flash its application."""

    name = "nrf-dfu"
    supported_ports = frozenset({"nrf"})
    supported_formats = (".uf2",)
    supported_platforms = frozenset({Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2})
    requires_bootloader = False
    priority = -20

    def is_available(self) -> bool:
        from mpflash.flash.builtins.nrf_dfu.transport import is_nrfutil_available

        return is_nrfutil_available()

    def supports(self, mcu, fw_file, platform: Platform) -> Optional[Reason]:
        reason = super().supports(mcu, fw_file, platform)
        if reason is not None and reason.kind == "dependency":
            return Reason("dependency", "install the nRF migration dependency with: uv sync --extra nrf")
        return reason

    def flash(self, ctx: FlashContext) -> FlashResult:
        from mpflash.flash.builtins.nrf_dfu.migration import migrate_nrf
        from mpflash.flash.builtins.nrf_dfu.profiles import get_profile

        target_name = ctx.options.get("softdevice_target")
        if not isinstance(target_name, str) or not target_name:
            raise MPFlashError("The nrf-dfu backend requires an explicit --softdevice target")
        confirm = ctx.options.get("confirm_migration")
        if not callable(confirm):
            raise MPFlashError("The nrf-dfu backend requires an explicit destructive confirmation policy")
        bootloader_port = ctx.options.get("nrf_dfu_port", "")
        if not isinstance(bootloader_port, str):
            raise MPFlashError("The nrf-dfu backend received an invalid bootloader CDC port")
        force_repair = ctx.options.get("force_softdevice_repair", False)
        if not isinstance(force_repair, bool):
            raise MPFlashError("The nrf-dfu backend received an invalid SoftDevice repair policy")

        from mpflash.flash.builtins.nrf_dfu.migration import ConfirmMigration

        profile = get_profile(target_name)
        updated = migrate_nrf(
            ctx.mcu,
            ctx.fw_file,
            profile,
            confirm=cast(ConfirmMigration, confirm),
            bootloader_port=bootloader_port,
            force_repair=force_repair,
        )
        return FlashResult(success=True, mcu=updated, backend=self.name)


register(NrfDfuBackend())
