"""Shared services available to every flash backend.

Backends call into these helpers instead of importing
``mpflash.bootloader.activate``, ``MPRemoteBoard.wait_for_restart``, etc.
directly. This keeps every backend (in-tree or plugin) loosely coupled to
``mpflash`` internals and makes them easy to test by injecting a fake
``FlashServices``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mpflash.flash.context import Platform
from mpflash.logger import log as _log

if TYPE_CHECKING:
    from mpflash.common import BootloaderMethod
    from mpflash.mpremoteboard import MPRemoteBoard


def _detect_current_platform() -> Platform:
    """Detect the host platform, including WSL2.

    Uses the existing ``ON_WSL2`` flag from ``mpflash.mpremoteboard`` rather
    than re-implementing the ``/proc/version`` probe.
    """
    # JIT import — keeps ``mpremoteboard`` from being eagerly loaded just to
    # decide the platform name (e.g. for ``mpflash plugins``).
    from mpflash.mpremoteboard import ON_WSL2

    if sys.platform == "win32":
        return Platform.WINDOWS
    if sys.platform == "darwin":
        return Platform.MACOS
    if sys.platform == "linux":
        return Platform.WSL2 if ON_WSL2 else Platform.LINUX
    # Unknown — fall back to Linux for closest match.
    return Platform.LINUX


@dataclass
class FlashServices:
    """Bundle of helpers handed to every backend through ``FlashContext``.

    Default-constructed instances delegate to the real ``mpflash`` modules;
    tests can subclass or monkey-patch fields.
    """

    log = _log  # type: ignore[assignment]

    def current_platform(self) -> Platform:
        return _detect_current_platform()

    def enter_bootloader(
        self,
        mcu: "MPRemoteBoard",
        method: "BootloaderMethod",
        timeout: int = 10,
        wait_after: int = 2,
    ) -> bool:
        """Put the board into bootloader mode using the requested method."""
        # JIT import — bootloader pulls in serial + win32 helpers.
        from mpflash.bootloader.activate import enter_bootloader

        return enter_bootloader(mcu, method=method, timeout=timeout, wait_after=wait_after)

    def wait_for_restart(self, mcu: "MPRemoteBoard", timeout: int = 10) -> None:
        mcu.wait_for_restart(timeout=timeout)

    def reenumerate(self, mcu: "MPRemoteBoard") -> None:
        """Refresh USB enumeration for the board after a flash + restart."""
        try:
            mcu.get_mcu_info()
        except Exception as exc:  # noqa: BLE001 - best-effort refresh
            self.log.debug(f"reenumerate: get_mcu_info failed: {exc}")


# A module-level default instance is convenient for the dispatcher.
default_services = FlashServices()
