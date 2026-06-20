"""Flash a UF2-based MCU under WSL2.

WSL2 sees Windows drives mounted at ``/mnt/<letter>/`` (e.g. ``/mnt/d``). The
drives are mounted automatically by ``drvfs`` so we do not need ``pmount`` /
``pumount`` like on bare Linux — we just scan for ``INFO_UF2.TXT``.
"""

from __future__ import annotations

import string
import time
from pathlib import Path
from typing import List, Optional

from loguru import logger as log
from rich.progress import track

from .boardid import get_board_id


def _candidate_mounts() -> List[Path]:
    """Return existing ``/mnt/<letter>`` paths on the WSL2 host."""
    base = Path("/mnt")
    if not base.is_dir():
        return []
    candidates: List[Path] = []
    for letter in string.ascii_lowercase:
        candidate = base / letter
        # ``is_dir`` follows drvfs mounts and returns False when the drive is
        # not present, which is exactly what we want.
        try:
            if candidate.is_dir():
                candidates.append(candidate)
        except OSError:
            continue
    return candidates


def wait_for_UF2_wsl2(board_id: str, s_max: int = 10) -> Optional[Path]:
    """Wait for the MCU to mount under ``/mnt/<letter>`` and return its path."""
    if s_max < 1:
        s_max = 10
    destination: Optional[Path] = None
    for _ in track(
        range(s_max),
        description=f"Waiting for mcu to mount under /mnt ({s_max}s)",
        transient=True,
        show_speed=False,
        refresh_per_second=1,
        total=s_max,
    ):
        for mount in _candidate_mounts():
            try:
                if (mount / "INFO_UF2.TXT").exists():
                    this_board_id = get_board_id(mount)
                    if not board_id or board_id.upper() in this_board_id.upper():
                        destination = mount
                        break
            except OSError as exc:
                log.trace(f"WSL2 UF2 probe error on {mount}: {exc}")
                continue
        if destination:
            break
        time.sleep(1)
    return destination


def dismount_uf2_wsl2() -> None:
    """No-op: drvfs handles UF2 volume lifecycle automatically."""
    return None
