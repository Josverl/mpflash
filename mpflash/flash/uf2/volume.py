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
from pathlib import Path
from typing import Optional

from loguru import logger as log

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

        return wait_for_UF2_linux(board_id=board_id, s_max=timeout)
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
    log.warning(
        f"No UF2 board detected at {candidate} — falling back to auto-detection"
    )
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
