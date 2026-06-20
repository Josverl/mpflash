"""Public flash dispatcher.

This module is now a thin façade over the pluggable backend registry. It
keeps the historical entry points (:func:`flash_tasks`, :func:`flash_mcu`) so
existing callers continue to work, but all method-selection logic now lives
in :mod:`mpflash.flash.registry`.

The auxiliary re-exports (``flash_pyocd``, ``pyocd_info``) are still emitted
here for backwards compatibility; new code should consume backends through
the registry.
"""

from __future__ import annotations

from pathlib import Path

from mpflash.common import BootloaderMethod, FlashMethod
from mpflash.config import config
from mpflash.errors import MPFlashError
from mpflash.logger import log

from .context import FlashContext, FlashResult, Platform
from .registry import get_backend, get_backends, select_backend
from .services import default_services
from .worklist import FlashTaskList

# Legacy re-exports — keep the old import paths working.
from .pyocd_flash import flash_pyocd, pyocd_info  # noqa: F401


# Map between the user-facing ``--method`` enum and the backend ``name``.
_METHOD_NAME_MAP = {
    FlashMethod.PYOCD: "pyocd",
    FlashMethod.UF2: "uf2",
    FlashMethod.DFU: "dfu",
    FlashMethod.ESPTOOL: "esptool",
}


def _resolve_backend_name(method: FlashMethod) -> str | None:
    """Translate a :class:`FlashMethod` to a backend name (or ``None`` for AUTO/SERIAL)."""
    if method in (FlashMethod.AUTO, FlashMethod.SERIAL):
        return None
    return _METHOD_NAME_MAP.get(method)


def flash_tasks(
    tasks: FlashTaskList,
    erase: bool,
    bootloader: BootloaderMethod,
    method: FlashMethod = FlashMethod.AUTO,
    **kwargs,
):
    """Flash every entry in ``tasks`` and return the updated boards."""
    flashed = []
    for task in tasks:
        mcu = task.board
        fw_info = task.firmware
        if not fw_info:
            log.error(f"Firmware not found for {mcu.board} on {mcu.serialport}, skipping")
            continue
        fw_file = config.firmware_folder / fw_info.firmware_file
        if not fw_file.exists():
            log.error(f"File {fw_file} does not exist, skipping {mcu.board} on {mcu.serialport}")
            continue
        log.info(f"Updating {mcu.board} on {mcu.serialport} to {fw_info.version}")
        try:
            updated = flash_mcu(
                mcu,
                fw_file=fw_file,
                erase=erase,
                bootloader=bootloader,
                method=method,
                **kwargs,
            )
        except MPFlashError as e:
            log.error(f"Failed to flash {mcu.board} on {mcu.serialport}: {e}")
            continue
        if updated:
            if fw_info.custom:
                mcu.get_board_info_toml()
                if fw_info.description:
                    mcu.toml["description"] = fw_info.description
                mcu.toml.setdefault("mpflash", {})
                mcu.toml["mpflash"]["board_id"] = fw_info.board_id
                mcu.toml["mpflash"]["custom_id"] = fw_info.custom_id
                mcu.set_board_info_toml()
            flashed.append(updated)
        else:
            log.error(f"Failed to flash {mcu.board} on {mcu.serialport}")
    return flashed


def flash_mcu(
    mcu,
    *,
    fw_file: Path,
    erase: bool = False,
    bootloader: BootloaderMethod = BootloaderMethod.AUTO,
    method: FlashMethod = FlashMethod.AUTO,
    **kwargs,
):
    """Flash a single MCU using the appropriate registered backend.

    ``method`` may be :class:`FlashMethod.AUTO` (let the registry pick),
    :class:`FlashMethod.SERIAL` (alias for auto, kept for backwards
    compatibility) or any concrete method. Any extra ``kwargs`` flow into
    :attr:`FlashContext.options` for the backend to consume.
    """
    requested = _resolve_backend_name(method)
    try:
        backend = select_backend(mcu, fw_file, requested_name=requested)
    except MPFlashError:
        raise
    except Exception as e:  # noqa: BLE001 - selection should never crash callers
        raise MPFlashError(f"Failed to select flash backend: {e}") from e

    log.debug(f"Using flash backend: {backend.name} for {mcu.board_id}")

    ctx = FlashContext(
        mcu=mcu,
        fw_file=fw_file,
        erase=erase,
        bootloader=bootloader,
        options=dict(kwargs),
        services=default_services,
    )

    try:
        result: FlashResult = backend.flash(ctx)
    except MPFlashError:
        raise
    except Exception as e:  # noqa: BLE001 - normalize for callers
        log.exception(f"Unexpected error while flashing {mcu.board} on {mcu.serialport}")
        raise MPFlashError(
            f"Failed to flash {mcu.board} on {mcu.serialport}: {e}"
        ) from e

    if not result.success and result.message:
        raise MPFlashError(result.message)
    return result.mcu


__all__ = [
    "FlashContext",
    "FlashResult",
    "Platform",
    "flash_mcu",
    "flash_tasks",
    "get_backend",
    "get_backends",
    "select_backend",
    # Legacy re-exports
    "flash_pyocd",
    "pyocd_info",
]
