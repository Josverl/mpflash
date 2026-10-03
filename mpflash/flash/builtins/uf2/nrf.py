"""nRF UF2 metadata probing and safe return-to-application support."""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from mpflash.errors import MPFlashError
from mpflash.logger import log

from .boardid import get_board_id, get_softdevice
from .volume import mounted_uf2_volumes, wait_for_new_volume

if TYPE_CHECKING:
    from mpflash.mpremoteboard import MPRemoteBoard


_UF2_MAGIC_START0 = 0x0A324655
_UF2_MAGIC_START1 = 0x9E5D5157
_UF2_MAGIC_END = 0x0AB16F30
_UF2_FLAG_FAMILY_ID = 0x00002000
_UF2_BOOTLOADER_FAMILY_ID = 0xD663823C
_NRF_UICR_BASE = 0x10001000
_NRF_POWER_GPREGRET = 0x4000051C
_DFU_MAGIC_UF2_RESET = 0x57
_RESET_FILENAME = "MPFLASH.UF2"


def build_nrf_reset_uf2() -> bytes:
    """Build a block that makes Adafruit nRF52 bootloaders abort and reset.

    The bootloader validates the intentionally empty UICR bootloader addresses
    before writing flash, marks the transfer aborted, and performs a system
    reset into the existing application.
    """
    block = bytearray(512)
    struct.pack_into(
        "<8I",
        block,
        0,
        _UF2_MAGIC_START0,
        _UF2_MAGIC_START1,
        _UF2_FLAG_FAMILY_ID,
        _NRF_UICR_BASE,
        256,
        0,
        1,
        _UF2_BOOTLOADER_FAMILY_ID,
    )
    struct.pack_into("<I", block, 508, _UF2_MAGIC_END)
    return bytes(block)


def _volume_is_mounted(volume: Path) -> bool:
    try:
        return (volume / "INFO_UF2.TXT").is_file()
    except OSError:
        return False


def reset_nrf_to_application(volume: Path, timeout: int = 3) -> None:
    """Reset an Adafruit-derived nRF UF2 bootloader without changing flash."""
    if not _volume_is_mounted(volume):
        raise MPFlashError(f"nRF UF2 volume is no longer mounted at {volume}")

    destination = volume / _RESET_FILENAME
    stream = None
    try:
        stream = destination.open("wb", buffering=0)
        stream.write(build_nrf_reset_uf2())
        os.fsync(stream.fileno())
    except OSError as error:
        if _volume_is_mounted(volume):
            raise MPFlashError(f"Failed to reset nRF board through {volume}: {error}") from error
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                if _volume_is_mounted(volume):
                    raise

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _volume_is_mounted(volume):
            return
        time.sleep(0.1)
    raise MPFlashError(f"nRF UF2 volume {volume} remained mounted after reset")


def _bootloader_command(mcu: "MPRemoteBoard") -> str:
    if mcu.family == "circuitpython":
        return "import microcontroller;microcontroller.on_next_reset(microcontroller.RunMode.UF2);microcontroller.reset()"
    if mcu.family == "micropython":
        return f"import machine;machine.mem32[{_NRF_POWER_GPREGRET:#x}]={_DFU_MAGIC_UF2_RESET:#x};machine.reset()"
    raise MPFlashError(f"Cannot enter the nRF UF2 bootloader from {mcu.family or 'unknown'} firmware")


def probe_nrf_softdevice(mcu: "MPRemoteBoard", timeout: int = 10) -> Optional[str]:
    """Round-trip an nRF board through UF2 mode and return its SoftDevice."""
    existing_volumes = mounted_uf2_volumes()
    command = _bootloader_command(mcu)
    rc, _ = mcu.run_command(
        ["exec", "--no-follow", command],
        no_info=True,
        timeout=timeout,
        soft_reset=False,
        log_errors=False,
    )
    if rc == 0:
        log.debug(f"nRF bootloader command on {mcu.serialport} completed before disconnect")

    volume = wait_for_new_volume(existing_volumes, timeout=timeout)
    if volume is None:
        raise MPFlashError(f"nRF board on {mcu.serialport} did not expose a new UF2 volume")

    board_id = get_board_id(volume)
    softdevice = get_softdevice(volume)
    log.debug(f"nRF UF2 metadata for {mcu.serialport}: board_id={board_id!r}, softdevice={softdevice!r}")

    reset_nrf_to_application(volume)
    if not mcu.wait_for_restart(timeout=timeout):
        raise MPFlashError(
            f"nRF board {board_id} did not reconnect after reading SoftDevice metadata; press its reset button to return to the application"
        )
    return softdevice


def enrich_mounted_nrf_bootloader(mcus: List["MPRemoteBoard"]) -> None:
    """Enrich one unresponsive serial device from one mounted nRF UF2 volume."""
    candidates = [mcu for mcu in mcus if mcu.family == "unknown"]
    volumes = []
    for volume in mounted_uf2_volumes():
        board_id = get_board_id(volume)
        softdevice = get_softdevice(volume)
        if board_id.casefold().startswith("nrf") or softdevice:
            volumes.append((volume, board_id, softdevice))

    if not candidates or not volumes:
        return
    if len(candidates) != 1 or len(volumes) != 1:
        log.warning(
            "Cannot associate mounted nRF UF2 metadata unambiguously: "
            f"{len(candidates)} unresponsive serial devices, {len(volumes)} nRF volumes"
        )
        return

    mcu = candidates[0]
    volume, board_id, softdevice = volumes[0]
    mcu.port = "nrf"
    mcu.sys_platform = "nrf"
    mcu.board_id = board_id
    mcu.description = f"UF2 bootloader at {volume}"
    mcu.softdevice = softdevice or ""
