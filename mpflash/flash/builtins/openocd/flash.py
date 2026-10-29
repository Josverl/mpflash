"""Flash a board from a MicroPython release package with Infineon OpenOCD.

The package from micropython.org is a ``.zip`` holding the firmware ``.hex``, a flash loader
(``.FLM``, e.g. ``PSE84_SMIF.FLM`` for PSOC Edge) and a ``.cfg`` with the external memory layout.
The chip description (``target/infineon/*.cfg``) and the KitProg3 probe configuration come
from the OpenOCD installation itself. Boards are listed in :mod:`.targets`.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, List, Optional

from mpflash.errors import MPFlashError
from mpflash.logger import log

from .download import ensure_openocd
from .runner import run_openocd, scripts_dir
from .targets import PORT_TARGETS, target_for_board

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard

ADAPTER_SPEED_KHZ = 12000
_SERIAL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class FirmwarePackage:
    """Files extracted from a firmware release package."""

    hex_file: Path
    flm_file: Path
    cfg_dir: Path


@contextmanager
def extracted_package(zip_path: Path) -> Iterator[FirmwarePackage]:
    """Extract the ``.hex``, ``.FLM`` and ``.cfg`` files of ``zip_path`` into a temporary directory."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise MPFlashError(f"{zip_path.name} is not a valid firmware package: {error}") from error

    with zf, tempfile.TemporaryDirectory(prefix="mpflash-openocd-") as tmp:
        dest = Path(tmp)
        found: dict[str, List[Path]] = {".hex": [], ".flm": [], ".cfg": []}
        for info in zf.infolist():
            name = Path(info.filename).name  # flatten: never trust archive paths
            suffix = Path(name).suffix.lower()
            if info.is_dir() or suffix not in found:
                continue
            target = dest / name
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
            found[suffix].append(target)

        if len(found[".hex"]) != 1 or len(found[".flm"]) != 1 or not found[".cfg"]:
            raise MPFlashError(
                f"{zip_path.name} must contain one .hex, one .FLM and at least one .cfg file "
                f"(found {len(found['.hex'])} .hex, {len(found['.flm'])} .FLM, {len(found['.cfg'])} .cfg)"
            )
        yield FirmwarePackage(found[".hex"][0], found[".flm"][0], dest)


def _tcl_path(path: Path) -> str:
    text = path.as_posix()
    if any(ch in text for ch in "{}"):
        raise MPFlashError(f"Unsupported character in path: {text}")
    return "{" + text + "}"


def build_args(
    package: FirmwarePackage,
    target_cfg: str,
    *,
    scripts: Optional[Path] = None,
    serial: Optional[str] = None,
) -> List[str]:
    """Build the OpenOCD argument list that programs, verifies and resets the board."""
    if serial and not _SERIAL_RE.match(serial):
        raise MPFlashError(f"Invalid probe serial number: {serial!r}")

    commands = [
        f"set QSPI_FLASHLOADER {_tcl_path(package.flm_file)}",
        "source [find interface/kitprog3.cfg]",
        *([f"adapter serial {serial}"] if serial else []),
        "transport select swd",
        f"source [find target/infineon/{target_cfg}]",
        "init",
        "reset init",
        f"adapter speed {ADAPTER_SPEED_KHZ}",
        f"flash write_image erase {_tcl_path(package.hex_file)}",
        f"verify_image {_tcl_path(package.hex_file)}",
        "reset run",
        "shutdown",
    ]
    args: List[str] = []
    if scripts:
        args += ["-s", str(scripts)]
    args += ["-s", str(package.cfg_dir)]
    for command in commands:
        args += ["-c", command]
    return args


def flash_openocd(
    mcu: "MPRemoteBoard",
    *,
    fw_file: Path,
    probe_id: Optional[str] = None,
    assume_yes: bool = False,
    erase: bool = False,
    timeout: int = 180,
) -> None:
    """Flash ``fw_file`` (a release ``.zip``) to a board with OpenOCD.

    ``probe_id`` selects the KitProg3 probe; it defaults to the board's USB serial number.
    ``erase`` wipes the filesystem over serial, only after every other check has passed.

    Raises:
        MPFlashError: unknown board, bad package, no OpenOCD, or OpenOCD failure.
    """
    board_id = getattr(mcu, "board_id", "") or mcu.board or ""
    target_cfg = target_for_board(mcu.port, board_id)
    if target_cfg is None:
        supported = ", ".join(sorted(PORT_TARGETS.get(mcu.port, {}))) or "none"
        raise MPFlashError(f"No OpenOCD target known for {board_id or 'unknown board'} on port {mcu.port!r} (supported: {supported})")

    openocd = ensure_openocd(assume_yes=assume_yes)
    serial = probe_id or getattr(mcu, "usb_serial_number", "") or None

    log.info(f"Flashing {fw_file.name} to {mcu.board} on {mcu.serialport} using {openocd}")
    with extracted_package(fw_file) as package:
        args = build_args(package, target_cfg, scripts=scripts_dir(openocd), serial=serial)
        # Last step before programming: the erase is destructive and every check above can fail.
        if erase:
            from mpflash.flash.builtins.uf2.erase import erase_filesystem

            if not erase_filesystem(mcu):
                log.warning(f"Could not erase the filesystem on {mcu.serialport} over serial; continuing without erase")
        run_openocd(openocd, args, timeout=timeout)
    log.info("Done flashing, board has been reset ...")
