"""UF2 flash implementation for rp2 / samd / nrf boards.

This is the internal implementation behind
:class:`mpflash.flash.builtins.uf2_backend.UF2Backend`. Public callers should
invoke :func:`mpflash.flash.flash_mcu` with ``method=FlashMethod.UF2`` rather
than importing from here directly.
"""

import shutil
import sys
from pathlib import Path
from typing import Optional

from loguru import logger as log

from mpflash.common import PORT_FWTYPES
from mpflash.mpremoteboard import MPRemoteBoard

from .boardid import get_board_id, get_softdevice
from .linux import dismount_uf2_linux, wait_for_UF2_linux
from .macos import wait_for_UF2_macos
from .windows import wait_for_UF2_windows


def _is_volume_pattern(s: str) -> bool:
    """Return True when s looks like a drive/mount path by string pattern alone."""
    if not s:
        return False
    if sys.platform == "win32":
        # Drive root: D:\ D:/ D: — drive letter + colon, optional slash
        p = Path(s)
        return bool(p.drive) and len(s.rstrip("/\\")) <= 2
    else:
        return s.startswith("/Volumes/") or s.startswith("/media/")


def _is_volume_path(serialport: str) -> bool:
    """Return True when serialport is a filesystem path rather than a real serial port."""
    if not serialport:
        return False
    # Use pattern first (works even after board reboots and drive disappears)
    if _is_volume_pattern(serialport):
        return True
    p = Path(serialport)
    return p.is_dir()


def _resolve_uf2_destination(mcu: MPRemoteBoard, s_max: int = 10) -> Optional[Path]:
    """Use explicit mount path when provided, otherwise auto-detect UF2 mount.

    If a volume path is given (e.g. D:\\ or /Volumes/RPI-RP2) and INFO_UF2.TXT
    is already present there, use it directly. Otherwise log a warning and fall
    back to auto-detection so the board is still found even if mounted elsewhere.
    ``s_max`` bounds how long auto-detection waits for the volume to appear.
    """
    serialport = getattr(mcu, "serialport", "")
    mcu_path = getattr(mcu, "path", None)

    for candidate_str in filter(None, [str(mcu_path) if mcu_path else None, serialport]):
        if _is_volume_pattern(candidate_str):
            explicit = Path(candidate_str)
            if explicit.exists() and explicit.is_dir() and (explicit / "INFO_UF2.TXT").exists():
                log.info(f"Using UF2 volume at {explicit}")
                return explicit
            log.warning(
                f"No UF2 board detected at {explicit} — "
                "falling back to auto-detection across all drives"
            )
            break  # fall through to auto-detect below

    # No explicit volume found (or not specified) — auto-detect by board_id
    destination = waitfor_uf2(board_id=mcu.port.upper(), s_max=s_max)
    return destination if isinstance(destination, Path) else None


def flash_uf2(mcu: MPRemoteBoard, fw_file: Path) -> Optional[MPRemoteBoard]:
    """
    Flash .UF2 devices via bootloader and filecopy
    - mpremote bootloader
    - Wait for the device to mount as a drive (up to 5s)
    - detect new drive with INFO_UF2.TXT
    - copy the firmware file to the drive
    - wait for the device to restart (5s)

    for Linux - to support headless operation ( GH Actions ) :
        pmount and pumount are used to mount and unmount the drive
        as this is not done automatically by the OS in headless mode.
    """
    if ".uf2" not in PORT_FWTYPES[mcu.port]:
        display_port = Path(mcu.serialport).as_posix() if Path(mcu.serialport).is_absolute() or Path(mcu.serialport).drive else mcu.serialport
        log.error(f"UF2 not supported on {mcu.board} on {display_port}")
        return None

    destination = _resolve_uf2_destination(mcu)

    if not destination or not destination.exists() or not (destination / "INFO_UF2.TXT").exists():
        log.error("Board is not in bootloader mode")
        return None

    log.info("Board is in bootloader mode")
    board_id = get_board_id(destination)  # type: ignore
    log.info(f"Board ID: {board_id}")
    if softdevice := get_softdevice(destination):  # type: ignore
        log.info(f"SoftDevice: {softdevice}")
    try:
        copy_firmware_to_uf2(fw_file, destination)
        log.success("Done copying, resetting the board.")
    except OSError as error:
        log.error(f"Failed to copy the firmware file to the board: {error}")
        return None

    if sys.platform in ["linux"]:
        dismount_uf2_linux()

    # If the board was flashed via a volume path (boot mode), switch to 'auto'
    # so that wait_for_restart and subsequent mpremote calls reach the real serial port.
    serialport = getattr(mcu, "serialport", "")
    if _is_volume_path(serialport):
        # Display path with forward slashes for cleaner logs
        display_path = Path(serialport).as_posix()
        log.debug(f"Switching serialport from volume path {Path(display_path)} to 'auto' for reconnection")
        mcu.serialport = "auto"

    if mcu.wait_for_restart() is False:
        log.error(f"Board did not reconnect on {mcu.serialport} after flashing")
        return None

    return mcu


def waitfor_uf2(board_id: str, s_max: int = 10):
    """
    Wait up to ``s_max`` seconds for the UF2 drive to mount
    """
    if sys.platform == "linux":
        return wait_for_UF2_linux(board_id=board_id, s_max=s_max)
    elif sys.platform == "win32":
        return wait_for_UF2_windows(board_id=board_id, s_max=s_max)
    elif sys.platform == "darwin":
        return wait_for_UF2_macos(board_id=board_id, s_max=s_max)
    else:
        log.warning(f"OS {sys.platform} not tested/supported")
        return None


def copy_firmware_to_uf2(fw_file: Path, destination: Path):
    """
    Copy firmware data to the destination without preserving metadata.

    UF2 volumes may disappear as soon as the data is consumed, so metadata
    operations after the copy can report a false failure. A failed copy is not
    retried against the same mount path because the board may have reset.
    """
    log.trace(f"Firmware: {fw_file}")
    log.info(f"Copying {fw_file.name} to {destination}.")
    return shutil.copyfile(fw_file, destination / fw_file.name)
