# sourcery skip: snake-case-functions
"""Flash a MCU with a UF2 bootloader on Windows"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import psutil
from rich.progress import track

from .boardid import get_board_id


def wait_for_UF2_windows(board_id: str, s_max: int = 10) -> Optional[Path]:
    """Wait for the MCU to mount as a drive"""

    if s_max < 1:
        s_max = 10
    # Poll twice per second so a short mount window is not missed.
    steps = s_max * 2
    destination = None
    for _ in track(
        range(steps),
        description=f"Waiting for mcu to mount as a drive ({s_max}s)",
        transient=True,
        show_speed=False,
        refresh_per_second=2,
        total=steps,
    ):
        # all=True includes removable volumes that Windows is still enumerating;
        # the default (all=False) can filter out a freshly-mounted UF2 drive.
        try:
            drives = [drive.device for drive in psutil.disk_partitions(all=True)]
        except OSError:
            drives = []
        for drive in drives:
            try:
                if Path(drive, "INFO_UF2.TXT").exists():
                    this_board_id = get_board_id(Path(drive))
                    if not board_id or board_id.upper() in this_board_id.upper():
                        # is it the correct board?
                        destination = Path(drive)
                        break
                    continue
            except OSError:
                pass
        if destination:
            break
        time.sleep(0.5)
    return destination
