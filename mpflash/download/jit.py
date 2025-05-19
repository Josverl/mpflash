# Just-in-time download of firmware if not already available
from loguru import logger as log

from mpflash.common import Params
from mpflash.download import download
from mpflash.downloaded import find_downloaded_firmware
from mpflash.flash.worklist import WorkList


def ensure_firmware_downloaded(worklist: WorkList, version) -> None:
    """
    ensure firmware is downloaded.
    """
    # iterate over the worklist ann update missing firmware
    newlist: WorkList = []
    for mcu, firmware in worklist:
        if firmware:
            # firmware is already downloaded
            newlist.append((mcu, firmware))
            continue
        # check if the firmware is already downloaded
        board_firmwares = find_downloaded_firmware(
            board_id=f"{mcu.board}-{mcu.variant}" if mcu.variant else mcu.board,
            version=version,
            port=mcu.port,
        )
        if not board_firmwares:
            # download the firmware
            log.info(f"Downloading {version} firmware for {mcu.board} on {mcu.serialport}.")
            download(ports=[mcu.port], boards=[mcu.board], versions=[version], force=True, clean=True)
            new_firmware = find_downloaded_firmware(
                board_id=f"{mcu.board}-{mcu.variant}" if mcu.variant else mcu.board,
                version=version,
                port=mcu.port,
            )
            newlist.append((mcu, new_firmware[0]))
        else:
            log.info(f"Found {version} firmware {board_firmwares[-1].firmware_file} for {mcu.board} on {mcu.serialport}.")
            newlist.append((mcu, firmware))

    worklist.clear()
    worklist.extend(newlist)

    pass
