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
from mpflash.downloaded import find_downloaded_firmware
from mpflash.errors import MPFlashError
from mpflash.logger import log

from .context import FlashContext, FlashResult, Platform
from .registry import get_backend, get_backends, select_backend
from .services import default_services
from .worklist import FlashTaskList

# Legacy re-exports — keep the old import paths working.
from .builtins.pyocd.flash import flash_pyocd, pyocd_info  # noqa: F401


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

    def _pick_backend_compatible_firmware(task, fw_info):
        """Pick a firmware image matching the explicit backend's supported formats."""
        if fw_info is None:
            return None

        requested_name = _resolve_backend_name(method)
        if not requested_name:
            return fw_info

        backend = get_backend(requested_name)
        if backend is None or not backend.supported_formats:
            return fw_info

        current_suffix = Path(fw_info.firmware_file).suffix.lower()
        if current_suffix in backend.supported_formats:
            return fw_info

        # Fast path: if a same-stem file with a backend-supported extension
        # exists next to the selected firmware, use it directly.
        selected_path = config.firmware_folder / fw_info.firmware_file
        for suffix in backend.supported_formats:
            sibling = selected_path.with_suffix(suffix)
            if sibling.exists():
                rel = sibling.relative_to(config.firmware_folder).as_posix()
                log.info(
                    f"Using {requested_name} compatible sibling firmware {rel} "
                    f"instead of {fw_info.firmware_file} for {task.board.board} on {task.board.serialport}"
                )
                fw_info.firmware_file = rel
                return fw_info

        board = task.board
        detected_board_id = f"{board.board}-{board.variant}" if board.variant else board.board
        board_ids = [getattr(fw_info, "board_id", ""), detected_board_id]

        candidates = []
        seen_files = set()
        for bid in board_ids:
            if not bid:
                continue
            # First prefer exact port match, then broaden to any port.
            for cand in find_downloaded_firmware(
                board_id=bid,
                version=fw_info.version,
                port=board.port,
                custom=bool(fw_info.custom),
            ) + find_downloaded_firmware(
                board_id=bid,
                version=fw_info.version,
                port="",
                custom=bool(fw_info.custom),
            ):
                if cand.firmware_file not in seen_files:
                    seen_files.add(cand.firmware_file)
                    candidates.append(cand)

        for cand in reversed(candidates):
            if Path(cand.firmware_file).suffix.lower() in backend.supported_formats:
                log.info(
                    f"Using {requested_name} compatible firmware {cand.firmware_file} "
                    f"instead of {fw_info.firmware_file} for {board.board} on {board.serialport}"
                )
                return cand
        return fw_info

    flashed = []
    for task in tasks:
        mcu = task.board
        fw_info = _pick_backend_compatible_firmware(task, task.firmware)
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
