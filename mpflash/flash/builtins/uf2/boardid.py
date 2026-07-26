from pathlib import Path
from typing import Optional

from loguru import logger as log


def get_board_id(path: Path):
    # Option : read Board-ID from INFO_UF2.TXT
    board_id = "Unknown"
    with open(path / "INFO_UF2.TXT") as f:
        data = f.readlines()
    for line in data:
        if line.startswith("Board-ID"):
            board_id = line[9:].strip()
    log.debug(f"INFO_UF2.TXT Board-ID={board_id}")
    return board_id


def get_softdevice(path: Path) -> Optional[str]:
    """Read the SoftDevice description from INFO_UF2.TXT.

    Nordic nRF5x bootloaders report the installed SoftDevice (e.g. "S140 7.3.0"),
    other UF2 bootloaders (rp2, samd) do not. Returns the description when present,
    otherwise None. Never raises, so it is safe to call for informational logging.
    """
    try:
        with open(path / "INFO_UF2.TXT") as f:
            data = f.readlines()
    except OSError:
        return None
    for line in data:
        if line.startswith("SoftDevice:"):
            softdevice = line.split(":", 1)[1].strip()
            log.debug(f"INFO_UF2.TXT SoftDevice={softdevice}")
            return softdevice or None
    return None
