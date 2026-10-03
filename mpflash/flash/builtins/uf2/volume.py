"""Platform-aware UF2 volume helpers.

Backends call into this module instead of importing
``linux.wait_for_UF2_linux`` / ``windows.wait_for_UF2_windows`` etc. directly.
The right helper is chosen at call time from ``services.current_platform()``
so adding a new host platform is one ``elif`` here, not a new registry.

Also resolves an *explicit* volume (``--volume D:\\`` or ``/mnt/d``) — under
WSL2 we translate Windows drive letters into ``/mnt/<letter>`` so users can
share a single command line between PowerShell and a WSL shell.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable, Optional, Set

from loguru import logger as log

from mpflash.errors import MPFlashError
from mpflash.flash.context import Platform
from mpflash.flash.services import default_services


_WIN_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/]*$")


def _platform() -> Platform:
    return default_services.current_platform()


def translate_volume_path(raw: str) -> str:
    """Translate a user-supplied volume path for the current host.

    On WSL2, accept Windows-style drive roots (``D:\\``, ``D:/``) and rewrite
    them to ``/mnt/d``. On all other platforms the string is returned
    unchanged.
    """
    if not raw:
        return raw
    if _platform() is Platform.WSL2:
        m = _WIN_DRIVE_RE.match(raw)
        if m:
            return f"/mnt/{m.group(1).lower()}"
    return raw


def wait_for_volume(board_id: str, timeout: int = 10) -> Optional[Path]:
    """Block until the UF2 volume for ``board_id`` appears, then return it."""
    platform = _platform()
    if platform is Platform.LINUX:
        from .linux import wait_for_UF2_linux

        destination = wait_for_UF2_linux(board_id=board_id, s_max=timeout)
        return destination if isinstance(destination, Path) else None
    if platform is Platform.WINDOWS:
        from .windows import wait_for_UF2_windows

        return wait_for_UF2_windows(board_id=board_id, s_max=timeout)
    if platform is Platform.MACOS:
        from .macos import wait_for_UF2_macos

        return wait_for_UF2_macos(board_id=board_id, s_max=timeout)
    if platform is Platform.WSL2:
        from .wsl2 import wait_for_UF2_wsl2

        return wait_for_UF2_wsl2(board_id=board_id, s_max=timeout)
    log.warning(f"UF2 detection not implemented for {platform.value}")
    return None


def mounted_uf2_volumes() -> Set[Path]:
    """Return the currently mounted filesystems containing INFO_UF2.TXT."""
    import psutil

    try:
        partitions = psutil.disk_partitions(all=True)
    except OSError:
        return set()

    volumes: Set[Path] = set()
    for partition in partitions:
        mountpoint = Path(partition.mountpoint)
        try:
            if (mountpoint / "INFO_UF2.TXT").is_file():
                volumes.add(mountpoint)
        except OSError:
            continue
    return volumes


def wait_for_new_volume(
    previous: Iterable[Path],
    timeout: int = 10,
    *,
    poll_interval: float = 0.25,
) -> Optional[Path]:
    """Wait for exactly one UF2 volume not present in ``previous``."""
    previous_keys = {str(path).casefold() for path in previous}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        added = {path for path in mounted_uf2_volumes() if str(path).casefold() not in previous_keys}
        if len(added) == 1:
            return added.pop()
        if len(added) > 1:
            paths = ", ".join(sorted(str(path) for path in added))
            raise MPFlashError(f"Multiple new UF2 volumes appeared: {paths}")
        time.sleep(poll_interval)
    return None


def resolve_explicit_volume(raw: str) -> Optional[Path]:
    """Return ``Path(raw)`` only if it is an existing UF2 mount point.

    Returns ``None`` (and warns) if the path is not a directory or does not
    contain ``INFO_UF2.TXT`` — letting callers fall back to auto-detection.
    """
    if not raw:
        return None
    translated = translate_volume_path(raw)
    candidate = Path(translated)
    if candidate.is_dir() and (candidate / "INFO_UF2.TXT").exists():
        log.info(f"Using UF2 volume at {candidate}")
        return candidate
    log.warning(f"No UF2 board detected at {candidate} — falling back to auto-detection")
    return None


def dismount(volume: Optional[Path] = None) -> None:
    """Best-effort unmount after the UF2 copy finished (Linux + WSL2 only)."""
    platform = _platform()
    if platform is Platform.LINUX:
        from .linux import dismount_uf2_linux

        dismount_uf2_linux()
    elif platform is Platform.WSL2:
        from .wsl2 import dismount_uf2_wsl2

        dismount_uf2_wsl2()
    # Windows + macOS: nothing to do.
