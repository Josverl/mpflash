"""Shared data structures for the pluggable flash backend system.

These types are deliberately small and dependency-free so any backend (in-tree
or third-party plugin discovered via the ``mpflash.flash_plugins`` entry-point
group) can import them without pulling in optional dependencies like pyOCD or
esptool.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from mpflash.common import BootloaderMethod
    from mpflash.flash.services import FlashServices
    from mpflash.mpremoteboard import MPRemoteBoard


class Platform(str, Enum):
    """Host operating-system platforms recognised by the flash backends."""

    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    WSL2 = "wsl2"


@dataclass
class FlashContext:
    """Everything a backend needs to perform a flash operation.

    Backend-specific options (probe id, flash mode, retry baud, …) flow through
    the opaque ``options`` dict so the dispatcher does not need to know about
    them. The ``services`` handle gives the backend access to logging,
    bootloader entry, wait-for-restart and platform detection.
    """

    mcu: "MPRemoteBoard"
    fw_file: Path
    erase: bool = False
    bootloader: Optional["BootloaderMethod"] = None
    options: Dict[str, Any] = field(default_factory=dict)
    services: Optional["FlashServices"] = None


@dataclass
class FlashResult:
    """Uniform return value for ``FlashBackend.flash``.

    ``mcu`` is the (re-enumerated) board on success; ``None`` on failure.
    ``backend`` is the backend ``name`` that produced this result.
    """

    success: bool
    mcu: Optional["MPRemoteBoard"] = None
    backend: str = ""
    message: str = ""

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True)
class Reason:
    """Why a backend cannot handle the request, for clear user diagnostics."""

    kind: str  # one of: "port", "format", "platform", "dependency", "probe", "other"
    message: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.message}"
