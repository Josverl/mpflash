"""Abstract base class for pluggable flash backends.

A backend declares which MicroPython ports it supports, which firmware file
formats it understands (in preference order), and which host OS platforms it
runs on. Backends are discovered either by being imported in
``mpflash.flash.builtins`` or via the ``mpflash.flash_plugins`` entry-point
group. Built-ins and third-party plugins use the same contract.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, FrozenSet, Optional, Tuple

from mpflash.flash.context import FlashContext, FlashResult, Platform, Reason

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard


class FlashBackend(ABC):
    """Contract every flash backend must implement.

    Subclasses are typically singletons; the registry instantiates each backend
    once. Class-level metadata (``supported_ports``, etc.) is read for
    selection without constructing the backend, so it must be defined as a
    class attribute (or property if it needs to be computed).
    """

    #: Short identifier used by the CLI (``--method <name>``) and the registry.
    name: str = ""

    #: MicroPython port names this backend can flash (e.g. ``{"rp2", "samd"}``).
    supported_ports: FrozenSet[str] = frozenset()

    #: Firmware file suffixes the backend understands, in preference order.
    supported_formats: Tuple[str, ...] = ()

    #: Host platforms this backend can run on.
    supported_platforms: FrozenSet[Platform] = frozenset(
        {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
    )

    #: Whether this backend needs the board to be in bootloader mode first.
    requires_bootloader: bool = False

    #: Used by ``select_backend`` to break ties when multiple backends match.
    #: Higher wins. Auto-selectable backends should use ``priority >= 0``;
    #: opt-in-only backends (e.g. pyOCD) should use a negative priority.
    priority: int = 0

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Runtime availability check (optional deps, drivers, permissions).

        Default returns ``True``. Backends with optional dependencies (pyOCD,
        DFU, …) should override.
        """
        return True

    def supports(
        self, mcu: "MPRemoteBoard", fw_file: Path, platform: Platform
    ) -> Optional[Reason]:
        """Return ``None`` if the backend can flash this combination.

        Otherwise return a :class:`Reason` describing why not. The default
        implementation checks ``supported_ports``, ``supported_formats``,
        ``supported_platforms`` and ``is_available()``. Backends with
        additional constraints (e.g. pyOCD needing a probe to be present)
        should override and call ``super().supports(...)`` first.
        """
        if mcu.port and self.supported_ports and mcu.port not in self.supported_ports:
            return Reason(
                "port",
                f"{self.name} does not support port {mcu.port!r} "
                f"(supports: {sorted(self.supported_ports)})",
            )
        suffix = fw_file.suffix.lower()
        if self.supported_formats and suffix not in self.supported_formats:
            return Reason(
                "format",
                f"{self.name} does not handle {suffix or '<none>'!s} files "
                f"(supports: {list(self.supported_formats)})",
            )
        if self.supported_platforms and platform not in self.supported_platforms:
            return Reason(
                "platform",
                f"{self.name} does not run on {platform.value} "
                f"(supports: {sorted(p.value for p in self.supported_platforms)})",
            )
        if not self.is_available():
            return Reason(
                "dependency",
                f"{self.name} backend is not available on this system "
                "(missing optional dependency or hardware)",
            )
        return None

    @abstractmethod
    def flash(self, ctx: FlashContext) -> FlashResult:
        """Perform the flash operation described by ``ctx``."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Dunders
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} name={self.name!r} "
            f"ports={sorted(self.supported_ports)} "
            f"formats={list(self.supported_formats)} "
            f"priority={self.priority}>"
        )
