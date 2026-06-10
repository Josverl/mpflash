"""Drive a board into bootloader mode using pluggable activators.

The orchestration walks the ordered list of activators returned by
:func:`mpflash.bootloader.registry.resolve_methods`, calling each in turn
and confirming with :func:`mpflash.bootloader.detect.in_bootloader` (which
delegates to the flash backend's ``is_board_ready`` when one is supplied).

Built-in activators register themselves on import; flash plugins can
contribute additional activators by calling
:func:`mpflash.bootloader.registry.register`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from mpflash.bootloader.detect import backend_for_port, in_bootloader
from mpflash.bootloader.registry import get_activator, resolve_methods
from mpflash.common import BootloaderMethod
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpremoteboard import MPRemoteBoard

# Re-exported for backward compatibility with callers/tests that imported
# the free functions from this module before the registry refactor.
from mpflash.bootloader.builtins.manual import enter_bootloader_manual  # noqa: F401
from mpflash.bootloader.builtins.mpy import enter_bootloader_mpy  # noqa: F401
from mpflash.bootloader.builtins.touch1200 import enter_bootloader_touch_1200bps  # noqa: F401

if TYPE_CHECKING:
    from mpflash.flash.base import FlashBackend


def enter_bootloader(
    mcu: MPRemoteBoard,
    method: BootloaderMethod = BootloaderMethod.MPY,
    timeout: int = 10,
    wait_after: int = 2,
    *,
    backend: Optional["FlashBackend"] = None,
) -> bool:
    """Put the board into bootloader mode.

    Args:
        mcu: The target board.
        method: Which BootloaderMethod to try first. AUTO walks the
            backend's preferred order. NONE skips activation entirely.
        timeout: Per-attempt timeout in seconds.
        wait_after: Seconds to wait between an activator call and the
            readiness check.
        backend: Optional flash backend used to look up the preferred
            activator order and to confirm readiness via
            ``backend.is_board_ready``. When omitted, the flash registry is
            consulted for a backend matching ``mcu.port``.

    Returns:
        True when the board is reported in bootloader mode, False if every
        attempted activator failed.
    """
    if method == BootloaderMethod.NONE:
        # No bootloader requested — assume it is OK to flash.
        return True

    if backend is None:
        backend = backend_for_port(mcu.port)
    preferred = list(backend.get_preferred_bootloaders(mcu)) if backend else []
    method_list = resolve_methods(method.value, preferred)
    if not method_list:
        log.debug(
            f"No bootloader activators resolved for {mcu.port} (method={method.value})"
        )
        return True

    log.info(
        f"Entering bootloader on {mcu.serialport} using methods {method_list}"
    )

    result = False
    for name in method_list:
        activator = get_activator(name)
        if activator is None:
            log.debug(f"Unknown bootloader activator {name!r}; skipping")
            continue
        try:
            result = bool(activator.activate(mcu, timeout=timeout))
        except MPFlashError as e:
            log.warning(
                f"Failed to enter bootloader on {mcu.serialport} using {name}"
            )
            log.exception(e)
            result = False
        if not result:
            continue

        # todo - check every second or so for up to max wait time
        time.sleep(wait_after)
        if in_bootloader(mcu, backend=backend):
            return True

    return result
