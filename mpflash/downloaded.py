import os
from pathlib import Path
from typing import List

from loguru import logger as log

from mpflash.config import config
from mpflash.db.core import Session
from mpflash.db.models import Firmware
from mpflash.mpboard_id.alternate import alternate_board_names
from mpflash.versions import clean_version

# #########################################################################################################


def clean_downloaded_firmwares() -> None:
    """
    - Check if all firmware records in the database are still available on disk.
        - If not, remove the record from the database.
    - For all firmware files on disk that are not in the database:
        - loag a warning message.
        - Check if the file is a valid firmware file.
        - If so, add it to the database.

    """
    """
    Get all firmware files in the firmware directory and its subfolders.
    """

    firmware_dir = Path(config.firmware_folder)

    """
    Returns a set of firmware file paths (relative to firmware_dir) found on disk.
    Uses a generator for performance and includes files in subfolders.
    Skips files with certain extensions.
    """
    firmware_files_on_disk = {
        str(f.relative_to(firmware_dir)) for f in firmware_dir.rglob("*") if f.is_file() and f.suffix not in {".db", ".bak", ".jsonl"}
    }

    with Session() as session:
        db_firmwares = session.query(Firmware).all()
        db_firmware_files = {fw.firmware_file for fw in db_firmwares}

        # Remove DB records for files not on disk
        for fw in db_firmwares:
            if fw.firmware_file not in firmware_files_on_disk:
                log.warning(f"Firmware file missing on disk, removing DB record: {fw.firmware_file}")
                session.delete(fw)
        session.commit()

        # Warn about files on disk not in DB
        for fw_file in firmware_files_on_disk - db_firmware_files:
            log.debug(f"Found file in firmware folder but not in DB: {fw_file}")


def find_downloaded_firmware(
    board_id: str,
    version: str = "",
    port: str = "",
    variants: bool = False,
) -> List[Firmware]:
    version = clean_version(version)
    log.debug(f"Looking for firmware for {board_id} {version} ")
    # Special handling for preview versions
    with Session() as session:
        if version == "preview" or "preview" in version:
            # Find all preview firmwares for this board/port, return the latest (highest build)
            query = session.query(Firmware).filter(Firmware.board_id == board_id)
            if port:
                query = query.filter(Firmware.port == port)
            query = query.filter(Firmware.firmware_file.contains("preview")).order_by(Firmware.build.desc())
            fw_list = query.all()
            if fw_list:
                return [fw_list[0]]  # Return the latest preview only
        else:
            fw_list = session.query(Firmware).filter(Firmware.board_id == board_id, Firmware.version == version).all()
            if fw_list:
                return fw_list
    #
    more_board_ids = alternate_board_names(board_id, port)
    #
    log.debug(f"2nd search with renamed board_id :{board_id}")
    with Session() as session:
        if version == "preview" or "preview" in version:
            query = session.query(Firmware).filter(Firmware.board_id.in_(more_board_ids))
            if port:
                query = query.filter(Firmware.port == port)
            query = query.filter(Firmware.firmware_file.contains("preview")).order_by(Firmware.build.desc())
            fw_list = query.all()
            if fw_list:
                return [fw_list[0]]
        else:
            fw_list = session.query(Firmware).filter(Firmware.board_id.in_(more_board_ids), Firmware.version == version).all()
            if fw_list:
                return fw_list
    log.warning(f"No firmware files found for board {board_id} version {version}")
    return []

