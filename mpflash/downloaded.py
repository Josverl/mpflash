import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import jsonlines
from loguru import logger as log

from mpflash.common import PORT_FWTYPES
from mpflash.db.core import Session
from mpflash.db.models import Board, Firmware
from mpflash.versions import clean_version

from .config import config

# #########################################################################################################


def clean_downloaded_firmwares() -> None:
    """
    Remove duplicate entries from the firmware.jsonl file, keeping the latest one
    uniqueness is based on the filename
    """
    # Duplication should no longer happen,
    # but is would be a good idea to check the consistence between the DB and the downloads folder sometimes
    pass


def find_downloaded_firmware(
    board_id: str,
    version: str = "",  # v1.2.3
    port: str = "",
    variants: bool = False,
) -> List[Firmware]:
    version = clean_version(version)
    log.debug(f"Looking for firmware for {board_id} {version} ")
    # fw_list = search_downloaded_fw(conn=conn, board_id=board_id, version=version, port=port)
    with Session() as session:
        fw_list = (
            session.query(Firmware)
            .filter(Firmware.board_id == board_id, Firmware.version == version)
            .all()
        )
    if fw_list:
        return fw_list
    #
    log.debug("try for renamed board_id")
    if board_id.startswith("PICO"):
        board_id = board_id.replace("PICO", "RPI_PICO")
    elif board_id.startswith("RPI_"):
        board_id = board_id.replace("RPI_", "")
    elif board_id.startswith("GENERIC"):
        board_id = board_id.replace("GENERIC", f"{port.upper()}_GENERIC")
    elif board_id.startswith("ESP32_"):
        board_id = board_id.replace("ESP32_", "")
    elif board_id.startswith("ESP8266_"):
        board_id = board_id.replace("ESP8266_", "")
    #        
    log.debug(f"2nd search with renamed board_id :{board_id}")
    with Session() as session:
        fw_list = (
            session.query(Firmware)
            .filter(Firmware.board_id == board_id, Firmware.version == version)
            .all()
        )
    if fw_list:
        return fw_list
    log.error("No firmware files found. Please download the firmware first.")
    return []
