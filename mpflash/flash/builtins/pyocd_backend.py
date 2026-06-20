"""pyOCD SWD/JTAG flash backend.

Optional — only loads when the ``pyocd`` extra is installed. Selection
priority is negative so :func:`mpflash.flash.registry.select_backend` only
chooses pyOCD when the user explicitly passes ``--method pyocd``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform, Reason
from mpflash.flash.registry import register

# The pyOCD backend is *always* imported by ``builtins/__init__.py``; the
# heavy / optional pyOCD imports happen inside ``flash()`` and
# ``is_available()`` so a system without the extra still loads ``mpflash``
# without errors.


class PyOCDBackend(FlashBackend):
    """SWD / JTAG programming via pyOCD."""

    name = "pyocd"
    # No fixed port set — pyOCD's CMSIS-pack catalog decides; we delegate
    # final say to ``mpflash.flash.pyocd_core.is_pyocd_supported``.
    supported_ports: frozenset = frozenset()
    supported_formats = (".bin", ".hex", ".elf", ".axf")
    supported_platforms = frozenset(
        {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
    )
    requires_bootloader = False
    # Negative so auto-select never picks pyOCD; users opt in with --method pyocd.
    priority = -10

    def is_available(self) -> bool:
        try:
            from mpflash.flash.builtins.pyocd.core import is_pyocd_available
        except ImportError:
            return False
        return bool(is_pyocd_available())

    def supports(self, mcu, fw_file: Path, platform: Platform) -> Optional[Reason]:
        # Skip the default port check (we don't declare a port set); still do
        # format / platform / dependency checks.
        suffix = fw_file.suffix.lower()
        if suffix not in self.supported_formats:
            return Reason(
                "format",
                f"pyocd does not handle {suffix or '<none>'!s} files "
                f"(supports: {list(self.supported_formats)})",
            )
        if platform not in self.supported_platforms:
            return Reason(
                "platform", f"pyocd does not run on {platform.value}"
            )
        if not self.is_available():
            return Reason(
                "dependency",
                "pyOCD is not installed (install with: uv sync --extra pyocd)",
            )
        from mpflash.flash.builtins.pyocd.core import is_pyocd_supported

        if not is_pyocd_supported(mcu):
            return Reason(
                "probe",
                f"pyOCD does not have a target definition for "
                f"{mcu.board_id or mcu.cpu or mcu.port!r}",
            )
        return None

    def flash(self, ctx: FlashContext) -> FlashResult:
        from mpflash.flash.builtins.pyocd.flash import flash_pyocd

        passthrough = {
            k: ctx.options[k]
            for k in ("probe_id", "auto_install_packs")
            if k in ctx.options
        }
        ok = flash_pyocd(ctx.mcu, fw_file=ctx.fw_file, erase=ctx.erase, **passthrough)
        return FlashResult(
            success=bool(ok),
            mcu=ctx.mcu if ok else None,
            backend=self.name,
        )


register(PyOCDBackend())
