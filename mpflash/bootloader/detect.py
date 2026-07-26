"""Detect whether a board is in bootloader mode.

This module is a thin compatibility wrapper around
:meth:`FlashBackend.is_board_ready`. When the caller supplies the active
backend, we use its readiness probe; otherwise we look one up by port from
the flash registry. ESP ports have no separate bootloader state, so they
always return True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from mpflash.logger import log
from mpflash.mpremoteboard import MPRemoteBoard

if TYPE_CHECKING:
    from mpflash.flash.base import FlashBackend


def in_bootloader(
    mcu: MPRemoteBoard, *, backend: Optional["FlashBackend"] = None
) -> bool:
    """Return ``True`` when ``mcu`` is in a state the backend can flash.

    If ``backend`` is omitted, the flash registry is consulted for a backend
    matching ``mcu.port``. ESP ports never need a separate bootloader, so
    they short-circuit to ``True``.
    """
    if mcu.port in {"esp32", "esp8266"}:
        log.debug(
            "esp32/esp8266 does not have a bootloader mode, Assume OK to flash"
        )
        return True

    if backend is None:
        backend = backend_for_port(mcu.port)

    if backend is None:
        log.error(
            f"Bootloader mode not supported on {mcu.board} on {mcu.serialport}"
        )
        return False

    return bool(backend.is_board_ready(mcu))


def backend_for_port(port: str) -> Optional["FlashBackend"]:
    """Best-effort lookup of a flash backend that handles ``port``.

    Used by callers that need a backend's bootloader preferences or
    readiness probe but don't have one in hand. Returns ``None`` when no
    registered backend matches.
    """
    if not port:
        return None
    # JIT import — the flash registry pulls in the built-in backends.
    from mpflash.flash.registry import get_backends

    candidates = [
        b for b in get_backends() if not b.supported_ports or port in b.supported_ports
    ]
    if not candidates:
        return None
    # Prefer bootloader-requiring backends with the highest priority — those
    # are the ones that actually have a meaningful readiness probe.
    candidates.sort(
        key=lambda b: (b.requires_bootloader, b.priority), reverse=True
    )
    return candidates[0]
