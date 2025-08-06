"""
Module to download MicroPython firmware for specific boards and versions.
Uses the micropython.org website to get the available versions and locations to download firmware files.
"""

import itertools
import re
from pathlib import Path
from typing import Dict, List, Optional

# #########################################################################################################
# make sure that jsonlines does not mistake the MicroPython ujson for the CPython ujson
import jsonlines
from loguru import logger as log
from rich.progress import track

from mpflash.common import PORT_FWTYPES
from mpflash.config import config
from mpflash.db.core import Session
from mpflash.db.models import Firmware, Board
from mpflash.downloaded import clean_downloaded_firmwares
from mpflash.errors import MPFlashError
from mpflash.mpboard_id.alternate import add_renamed_boards
from mpflash.versions import clean_version

from .from_web import fetch_firmware_files, get_boards
from .fwinfo import FWInfo

# avoid conflict with the ujson used by MicroPython
jsonlines.ujson = None  # type: ignore
# #########################################################################################################



def key_fw_boardid_preview_ext(fw: Firmware):
    "Grouping key for the retrieved board urls"
    return fw.board_id, fw.preview, fw.ext




# Cache for variant suffixes - will be populated on first use
_PATTERN = ""

def _get_variant_pattern():
    """
    Query the database for all known variant suffixes.
    This is done only once and the result is cached.
    
    Returns:
        List of known variant suffixes.
    """
    global _PATTERN
    
    if _PATTERN:
        # If the pattern is already set, return it
        return _PATTERN

    with Session() as session:
        # Query distinct variants
        variants = session.query(Board.variant).distinct().all()


    _VARIANT_SUFFIXES = [f"_{v[0]}" for v in variants if v[0] and v[0].strip()]
    # workaround for the fact that the variant names do not always match the suffixes
    # e.g. 'PIMORONI_PICOLIPO' has the variant 'FLASH_16MB' but the suffix is '_16MB'
    _VARIANT_SUFFIXES.extend( ["_2MB", "_4MB", "_8MB", "_16MB"] )  # add common SPIRAM size suffixes

    # return _VARIANT_SUFFIXES
    _PATTERN  = f"({'|'.join(re.escape(v) for v in _VARIANT_SUFFIXES)})$"
    return _PATTERN

    

def strip_variant(board: str) -> str:
    """
    Strips the variant suffix from the board name based on variants in the database.
    For example, 'RPI_PICO_W_SPIRAM' becomes 'RPI_PICO_W'.

    Args:
        board: The board name to process.

    Returns:
        The board name without the variant suffix.
    """
    pattern = _get_variant_pattern()
    return re.sub(pattern, "", board)


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


    downloaded = 0
    versions = [] if versions is None else [clean_version(v) for v in versions]
    
    # remove the known variant suffixes from the boards
    # TODO: IS THIS REALLY NEEDED ?
    # boards = [strip_variant(b) for b in boards]
    
    # handle downloading firmware for renamed boards
    boards = add_renamed_boards(boards)


    available_firmwares = get_firmware_list(ports, boards, versions, clean)

    for b in available_firmwares:
        log.debug(b.firmware_file)
    # relevant

    log.info(f"Found {len(available_firmwares)} potentially relevant firmwares")
    if not available_firmwares:
        log.error("No relevant firmwares could be found on https://micropython.org/download")
        log.info(f"{versions=} {ports=} {boards=}")
        log.info("Please check the website for the latest firmware files or try the preview version.")
        return 0

    firmware_folder.mkdir(exist_ok=True)

    downloaded = download_firmware_files(available_firmwares, firmware_folder, force  )
    log.success(f"Downloaded {downloaded} firmware images." )
    return downloaded 

def download_firmware_files(available_firmwares :List[Firmware],firmware_folder:Path, force:bool ):
    """
    Downloads the firmware files to the specified folder.
    Args:
        firmware_folder : The folder to save the downloaded firmware files.
        force : A flag indicating whether to force the download even if the firmware file already exists.
        requests : The requests module to use for downloading the firmware files.
        unique_boards : The list of unique firmware information to download.
    """

    # with jsonlines.open(firmware_folder / "firmware.jsonl", "a") as writer:
    with Session() as session:
        # skipped, downloaded = fetch_firmware_files(available_firmwares, firmware_folder, force, requests, writer)
        downloaded = 0
        for fw in fetch_firmware_files(available_firmwares, firmware_folder, force):
            session.merge(fw)
            log.debug(f" {fw.firmware_file} downloaded")
            downloaded += 1
        session.commit()
    if downloaded > 0:
        clean_downloaded_firmwares()
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
    preview = any("preview" in v for v in versions)

    # board_urls = sorted(get_boards(ports, boards, clean), key=key_fw_ver_pre_ext_bld)
    board_urls = get_boards(ports, boards, clean)

    log.debug(f"Total {len(board_urls)} firmwares")
    if versions:
        # filter out the boards that are not in the versions list
        relevant = [
            board for board in board_urls if ( 
                board.version in versions 
                # or (preview and board.preview )
                # and board.board_id in boards 
                # and board.build == "0" 
                # and not board.preview
            )
        ]
    else:
        relevant = board_urls

    log.debug(f"Matching firmwares: {len(relevant)}")
    # select the unique boards
    unique_boards: List[Firmware] = []
    for _, g in itertools.groupby(relevant, key=key_fw_boardid_preview_ext):
        # list is aleady sorted by build (desc)  so we can just get the first item
        sub_list = list(g)
        unique_boards.append(sub_list[0])
    log.debug(f"Including preview: {len(unique_boards)}")
    return unique_boards


def download(
    ports: List[str],
    boards: List[str],
    versions: List[str],
    force: bool = False,
    clean: bool = True,
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
    destination = config.firmware_folder
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

