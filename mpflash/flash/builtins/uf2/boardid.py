import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger as log


@dataclass(frozen=True)
class Uf2BoardInfo:
    """Metadata reported by an UF2 bootloader."""

    board_id: str = "Unknown"
    bootloader_version: str = ""
    model: str = ""
    softdevice: Optional[str] = None


_BOOTLOADER_VERSION_RE = re.compile(r"^UF2 Bootloader\s+([^\s]+)", re.IGNORECASE)
_SOFTDEVICE_RE = re.compile(r"^(S\d+)(?:\s+version)?\s+(\d+(?:\.\d+)+)$", re.IGNORECASE)


def normalize_softdevice(value: str) -> str:
    """Normalize UF2 SoftDevice labels such as ``S140 version 6.1.1``."""
    stripped = value.strip()
    match = _SOFTDEVICE_RE.match(stripped)
    if not match:
        return stripped
    return f"{match.group(1).upper()} {match.group(2)}"


def read_uf2_board_info(path: Path, *, missing_ok: bool = True) -> Uf2BoardInfo:
    """Read all supported metadata from ``INFO_UF2.TXT``."""
    try:
        data = (path / "INFO_UF2.TXT").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        if missing_ok:
            return Uf2BoardInfo()
        raise

    board_id = "Unknown"
    bootloader_version = ""
    model = ""
    softdevice: Optional[str] = None
    for line in data:
        if match := _BOOTLOADER_VERSION_RE.match(line):
            bootloader_version = match.group(1)
        elif line.startswith("Board-ID:"):
            board_id = line.split(":", 1)[1].strip() or "Unknown"
        elif line.startswith("Model:"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("SoftDevice:"):
            value = line.split(":", 1)[1].strip()
            softdevice = normalize_softdevice(value) if value else None
    return Uf2BoardInfo(
        board_id=board_id,
        bootloader_version=bootloader_version,
        model=model,
        softdevice=softdevice,
    )


def get_board_id(path: Path) -> str:
    """Read the UF2 Board-ID."""
    board_id = read_uf2_board_info(path, missing_ok=False).board_id
    log.debug(f"INFO_UF2.TXT Board-ID={board_id}")
    return board_id


def get_softdevice(path: Path) -> Optional[str]:
    """Read the SoftDevice description from INFO_UF2.TXT.

    Nordic nRF5x bootloaders report the installed SoftDevice (e.g. "S140 7.3.0"),
    other UF2 bootloaders (rp2, samd) do not. Returns the description when present,
    otherwise None. Never raises, so it is safe to call for informational logging.
    """
    softdevice = read_uf2_board_info(path).softdevice
    if softdevice:
        log.debug(f"INFO_UF2.TXT SoftDevice={softdevice}")
    return softdevice
