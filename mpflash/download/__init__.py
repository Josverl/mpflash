"""
Module to download MicroPython firmware for specific boards and versions.
Uses the micropython.org website to get the available versions and locations to download firmware files.
"""

import itertools
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

# #########################################################################################################
# make sure that jsonlines does not mistake the MicroPython ujson for the CPython ujson
import jsonlines
from loguru import logger as log
from rich.progress import track

from mpflash.common import PORT_FWTYPES, FWInfo
from .from_web import get_boards, fetch_firmware_files
from mpflash.downloaded import clean_downloaded_firmwares
from mpflash.errors import MPFlashError
from mpflash.versions import clean_version
from mpflash.config import config
from mpflash.db.downloads import upsert_download
# avoid conflict with the ujson used by MicroPython
jsonlines.ujson = None  # type: ignore
# #########################################################################################################



def key_fw_ver_pre_ext_bld(x: FWInfo):
    "sorting key for the retrieved board urls"
    return x.variant, x.version, x.preview, x.ext, x.build


def key_fw_var_pre_ext(x: FWInfo):
    "Grouping key for the retrieved board urls"
    return x.variant, x.preview, x.ext


def download_firmwares(
    firmware_folder: Path,
    ports: List[str],
    boards: List[str],
    versions: Optional[List[str]] = None,
    *,
    force: bool = False,
    clean: bool = True,
) -> int:
    """
    Downloads firmware files based on the specified firmware folder, ports, boards, versions, force flag, and clean flag.

    Args:
        firmware_folder : The folder to save the downloaded firmware files.
        ports : The list of ports to check for firmware.
        boards : The list of boards to download firmware for.
        versions : The list of versions to download firmware for.
        force : A flag indicating whether to force the download even if the firmware file already exists.
        clean : A flag indicating to clean the date from the firmware filename.
    """


    skipped = downloaded = 0
    versions = [] if versions is None else [clean_version(v) for v in versions]
    # handle renamed boards
    boards = add_renamed_boards(boards)

    available_firmwares = get_firmware_list(ports, boards, versions, clean)

    for b in available_firmwares:
        log.debug(b.filename)
    # relevant

    log.info(f"Found {len(available_firmwares)} relevant unique firmwares")
    if not available_firmwares:
        log.error("No relevant firmwares could be found on https://micropython.org/download")
        log.info(f"{versions=} {ports=} {boards=}")
        log.info("Please check the website for the latest firmware files or try the preview version.")
        return 0

    firmware_folder.mkdir(exist_ok=True)

    downloaded = download_firmware_files(available_firmwares, firmware_folder, force  )
    log.success(f"Downloaded {downloaded} firmware images." )
    return downloaded 

def download_firmware_files(available_firmwares :List[FWInfo],firmware_folder:Path, force:bool ):
    """
    Downloads the firmware files to the specified folder.
    Args:
        firmware_folder : The folder to save the downloaded firmware files.
        force : A flag indicating whether to force the download even if the firmware file already exists.
        requests : The requests module to use for downloading the firmware files.
        unique_boards : The list of unique firmware information to download.
    """

    # with jsonlines.open(firmware_folder / "firmware.jsonl", "a") as writer:
    with sqlite3.connect(config.db_path) as conn:
        # skipped, downloaded = fetch_firmware_files(available_firmwares, firmware_folder, force, requests, writer)
        downloaded = 0
        for fw in fetch_firmware_files(available_firmwares, firmware_folder, force):
            upsert_download(conn, fw)
            # writer.write(fw)
            log.debug(f" {fw.filename} downloaded")
            downloaded += 1
    if downloaded > 0:
        clean_downloaded_firmwares(firmware_folder)
    return downloaded



def get_firmware_list(ports: List[str], boards: List[str], versions: List[str], clean: bool = True):
    """
    Retrieves a list of unique firmware files potentially  available on micropython.org > downloads
    based on the specified ports, boards, versions, and clean flag.

    Args:
        ports : One or more ports to check for firmware.
        boards : One or more boards to filter the firmware by.
        versions : One or more versions to filter the firmware by.
        clean : Remove date-stamp and Git Hash from the firmware name.

    Returns:
        List[FWInfo]: A list of unique firmware information.

    """

    log.trace("Checking MicroPython download pages")
    versions = [clean_version(v, drop_v=False) for v in versions]
    preview = "preview" in versions

    board_urls = sorted(get_boards(ports, boards, clean), key=key_fw_ver_pre_ext_bld)

    log.debug(f"Total {len(board_urls)} firmwares")

    relevant = [
        board for board in board_urls if board.version in versions and board.build == "0" and board.board in boards and not board.preview
    ]

    if preview:
        relevant.extend([board for board in board_urls if board.board in boards and board.preview])
    log.debug(f"Matching firmwares: {len(relevant)}")
    # select the unique boards
    unique_boards: List[FWInfo] = []
    for _, g in itertools.groupby(relevant, key=key_fw_var_pre_ext):
        # list is aleady sorted by build so we can just get the last item
        sub_list = list(g)
        unique_boards.append(sub_list[-1])
    log.debug(f"Last preview only: {len(unique_boards)}")
    return unique_boards


def download(
    destination: Path,
    ports: List[str],
    boards: List[str],
    versions: List[str],
    force: bool,
    clean: bool,
) -> int:
    """
    Downloads firmware files based on the specified destination, ports, boards, versions, force flag, and clean flag.

    Args:
        destination : The destination folder to save the downloaded firmware files.
        ports : The list of ports to check for firmware.
        boards : The list of boards to download firmware for.
        versions : The list of versions to download firmware for.
        force : A flag indicating whether to force the download even if the firmware file already exists.
        clean : A flag indicating whether to clean the date from the firmware filename.

    Returns:
        int: The number of downloaded firmware files.

    Raises:
        MPFlashError : If no boards are found or specified.

    """
    # Just in time import
    import requests

    if not boards:
        log.critical("No boards found, please connect a board or specify boards to download firmware for.")
        raise MPFlashError("No boards found")

    try:
        destination.mkdir(exist_ok=True, parents=True)
    except (PermissionError, FileNotFoundError) as e:
        log.critical(f"Could not create folder {destination}")
        raise MPFlashError(f"Could not create folder {destination}") from e
    try:
        result = download_firmwares(destination, ports, boards, versions, force=force, clean=clean)
    except requests.exceptions.RequestException as e:
        log.exception(e)
        raise MPFlashError("Could not connect to micropython.org") from e

    return result


def add_renamed_boards(boards: List[str]) -> List[str]:
    """
    Adds the renamed boards to the list of boards.

    Args:
        boards : The list of boards to add the renamed boards to.

    Returns:
        List[str]: The list of boards with the renamed boards added.
    """

    renamed = {
        "PICO": ["RPI_PICO"],
        "PICO_W": ["RPI_PICO_W"],
        "GENERIC": ["ESP32_GENERIC", "ESP8266_GENERIC"],  # just add both of them
    }
    _boards = boards.copy()
    for board in boards:
        if board in renamed and renamed[board] not in boards:
            _boards.extend(renamed[board])
        if board != board.upper() and board.upper() not in boards:
            _boards.append(board.upper())
    return _boards
