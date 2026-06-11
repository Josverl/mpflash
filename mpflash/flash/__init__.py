"""Public flash dispatcher.

This module is  a thin façade over the pluggable backend registry.
All method-selection logic lives in :mod:`mpflash.flash.registry`.

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


# Map between the user-facing ``--method`` enum and the backend ``name``.
_METHOD_NAME_MAP = {
    FlashMethod.PYOCD: "pyocd",
    FlashMethod.UF2: "uf2",
    FlashMethod.DFU: "dfu",
    FlashMethod.ESPTOOL: "esptool",
}


def _normalize_firmware_file(firmware_file: str) -> str:
    """Normalize legacy path separators in firmware DB entries."""
    normalized = (firmware_file or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _resolve_firmware_path(firmware_file: str) -> Path:
    """Resolve a firmware DB entry to an on-disk path."""
    normalized = _normalize_firmware_file(firmware_file)
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate
    return config.firmware_folder / normalized


def _resolve_backend_name(method: FlashMethod) -> str | None:
    """Translate a :class:`FlashMethod` to a backend name (or ``None`` for AUTO)."""
    if method == FlashMethod.AUTO:
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

    attempted_backend_downloads: set[tuple[str, str, str, str, bool]] = set()

    def _pick_backend_compatible_firmware(task, fw_info):
        """Pick a firmware image matching the explicit backend's supported formats."""
        if fw_info is None:
            return None

        fw_info.firmware_file = _normalize_firmware_file(fw_info.firmware_file)

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
        selected_path = _resolve_firmware_path(fw_info.firmware_file)
        for suffix in backend.supported_formats:
            sibling = selected_path.with_suffix(suffix)
            if sibling.exists():
                try:
                    rel = sibling.relative_to(config.firmware_folder).as_posix()
                except ValueError:
                    rel = str(sibling)
                log.info(
                    f"Using {requested_name} compatible sibling firmware {rel} "
                    f"instead of {fw_info.firmware_file} for {task.board.board} on {task.board.serialport}"
                )
                fw_info.firmware_file = rel
                return fw_info

        board = task.board
        detected_board_id = f"{board.board}-{board.variant}" if board.variant else board.board
        board_ids = [getattr(fw_info, "board_id", ""), detected_board_id]

        def _find_supported_candidate():
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

            compatible = []
            for idx, cand in enumerate(candidates):
                cand.firmware_file = _normalize_firmware_file(cand.firmware_file)
                if Path(cand.firmware_file).suffix.lower() not in backend.supported_formats:
                    continue
                rank = (
                    int(_resolve_firmware_path(cand.firmware_file).exists()),
                    int((cand.source or "").lower() == "mpbuild"),
                    int(bool(cand.custom)),
                    int(getattr(cand, "build", 0) or 0),
                    idx,
                )
                compatible.append((rank, cand))
            if compatible:
                return max(compatible, key=lambda item: item[0])[1]
            return None

        if candidate := _find_supported_candidate():
            log.info(
                f"Using {requested_name} compatible firmware {candidate.firmware_file} "
                f"instead of {fw_info.firmware_file} for {board.board} on {board.serialport}"
            )
            return candidate

        # No local firmware matches backend-supported file types; try one
        # targeted download refresh before handing off to backend selection.
        download_key = (
            requested_name,
            detected_board_id,
            fw_info.version,
            board.port or "",
            bool(fw_info.custom),
        )
        if download_key not in attempted_backend_downloads:
            attempted_backend_downloads.add(download_key)
            try:
                from mpflash.download import download
                from mpflash.mpboard_id.alternate import alternate_board_names

                log.info(
                    f"No local {requested_name} firmware with suffix in "
                    f"{list(backend.supported_formats)} for {board.board} on {board.serialport}; "
                    "trying firmware download refresh"
                )
                download(
                    ports=[board.port] if board.port else [],
                    boards=alternate_board_names(detected_board_id, board.port),
                    versions=[fw_info.version],
                    force=True,
                    clean=True,
                )
            except Exception as exc:  # noqa: BLE001 - fallback to original firmware below
                log.debug(f"Backend-compatible firmware refresh failed for {detected_board_id} {fw_info.version}: {exc}")

            if candidate := _find_supported_candidate():
                log.info(
                    f"Using downloaded {requested_name} compatible firmware {candidate.firmware_file} "
                    f"instead of {fw_info.firmware_file} for {board.board} on {board.serialport}"
                )
                return candidate

        raise MPFlashError(
            f"No firmware matching backend {requested_name!r} for "
            f"{detected_board_id!r} {fw_info.version}. "
            f"Selected firmware is {fw_info.firmware_file!r} ({current_suffix or '<none>'}), "
            f"but {requested_name} supports {list(backend.supported_formats)}. "
            "A download refresh was attempted but no compatible firmware was found."
        )

        return fw_info

    flashed = []
    for task in tasks:
        mcu = task.board
        fw_info = _pick_backend_compatible_firmware(task, task.firmware)
        if not fw_info:
            log.error(f"Firmware not found for {mcu.board} on {mcu.serialport}, skipping")
            continue
        fw_info.firmware_file = _normalize_firmware_file(fw_info.firmware_file)
        fw_file = _resolve_firmware_path(fw_info.firmware_file)
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
                if fw_info.custom_id:
                    mcu.toml["mpflash"]["custom_id"] = fw_info.custom_id
                else:
                    mcu.toml["mpflash"].pop("custom_id", None)
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

    ``method`` may be :class:`FlashMethod.AUTO` (let the registry pick) or
    any concrete method. Any extra ``kwargs`` flow into
    :attr:`FlashContext.options` for the backend to consume.
    """
    requested = _resolve_backend_name(method)
    target_override = kwargs.get("target_override")

    # When the user explicitly provides a pyOCD target override, skip
    # capability probing that depends on MCU metadata-derived target matching.
    if requested == "pyocd" and target_override:
        backend = get_backend("pyocd")
        if backend is None:
            raise MPFlashError("Unknown flash method 'pyocd'.")
        platform = default_services.current_platform()
        suffix = fw_file.suffix.lower()
        if backend.supported_formats and suffix not in backend.supported_formats:
            raise MPFlashError(f"Backend 'pyocd' cannot flash {fw_file.name}: unsupported format {suffix or '<none>'}.")
        if backend.supported_platforms and platform not in backend.supported_platforms:
            raise MPFlashError(f"Backend 'pyocd' does not run on {platform.value}.")
        if not backend.is_available():
            raise MPFlashError("pyOCD is not installed (install with: uv sync --extra pyocd).")
        log.info(f"Using explicit pyOCD target override '{target_override}' for {mcu.board_id or mcu.board}")
    else:
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
        raise MPFlashError(f"Failed to flash {mcu.board} on {mcu.serialport}: {e}") from e

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
]
