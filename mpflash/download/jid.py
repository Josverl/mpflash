# Just In-time Download of firmware if not already available
import warnings

from loguru import logger as log

from mpflash.download import download
from mpflash.downloaded import find_downloaded_firmware
from mpflash.errors import MPFlashError
from mpflash.flash.worklist import FlashTaskList
from mpflash.mpboard_id.alternate import alternate_board_names


def ensure_firmware_downloaded_tasks(tasks: FlashTaskList, version: str, force: bool) -> None:
    """Ensure firmware present for each FlashTask, updating in-place.

    Mirrors ensure_firmware_downloaded logic but works directly on FlashTaskList.
    """
    updated: FlashTaskList = []
    for task in tasks:
        mcu = task.board
        fw = task.firmware
        if not force and fw:
            updated.append(task)
            continue
        # find already downloaded firmware unless forcing
        if force or not fw:
            found = (
                find_downloaded_firmware(
                    board_id=f"{mcu.board}-{mcu.variant}" if mcu.variant else mcu.board,
                    version=version,
                    port=mcu.port,
                )
                if not force
                else []
            )
            if not found:
                log.info(f"Downloading {version} firmware for {mcu.board} on {mcu.serialport}.")
                download(ports=[mcu.port], boards=alternate_board_names(mcu.board, mcu.port), versions=[version], force=True, clean=True)
                found = find_downloaded_firmware(
                    board_id=f"{mcu.board}-{mcu.variant}" if mcu.variant else mcu.board,
                    version=version,
                    port=mcu.port,
                )
                if not found:
                    raise MPFlashError(f"Failed to download {version} firmware for {mcu.board} on {mcu.serialport}.")
            # choose last/newest
            task.firmware = found[-1]
        updated.append(task)
    tasks.clear()
    tasks.extend(updated)
