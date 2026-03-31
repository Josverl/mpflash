import os
from pathlib import Path
from typing import List

from loguru import logger as log
from mpflash.config import config
from mpflash.mpboard_id.alternate import alternate_board_names
from mpflash.versions import clean_version

from mpflash.db.models import Firmware, database

# #########################################################################################################


def clean_downloaded_firmwares() -> None:
    """
    - Check if all firmware records in the database are still available on disk.
        - If not, remove the record from the database.
    - For all firmware files on disk that are not in the database:
        - log a warning message.
        - Check if the file is a valid firmware file.
        - If so, add it to the database.

    """
    firmware_dir = Path(config.firmware_folder)

    firmware_files_on_disk = {
        str(f.relative_to(firmware_dir)) for f in firmware_dir.rglob("*") if f.is_file() and f.suffix not in {".db", ".bak", ".jsonl"}
    }

    with database.atomic():
        db_firmwares = list(Firmware.select())
        db_firmware_files = {fw.firmware_file for fw in db_firmwares}

        # Remove DB records for files not on disk
        for fw in db_firmwares:
            if fw.firmware_file not in firmware_files_on_disk:
                log.warning(f"Firmware file missing on disk, removing DB record: {fw.firmware_file}")
                fw.delete_instance()

        # Warn about files on disk not in DB
        for fw_file in firmware_files_on_disk - db_firmware_files:
            log.debug(f"Found file in firmware folder but not in DB: {fw_file}")


def find_downloaded_firmware(
    board_id: str,
    version: str = "",
    port: str = "",
    variants: bool = False,
    custom: bool = False,
) -> List[Firmware]:
    """Find firmware records matching the given board_id and version."""
    version = clean_version(version)
    log.debug(f"Looking for firmware for {board_id} {version} ")

    if "preview" in version:
        # Find all preview firmwares for this board/port, return the latest (highest build)
        if custom:
            qry = Firmware.select().where(Firmware.custom_id == board_id)
        else:
            qry = Firmware.select().where(Firmware.board_id == board_id)
        if port:
            qry = qry.where(Firmware.port == port)
        qry = qry.where(Firmware.firmware_file.contains("preview")).order_by(Firmware.build.desc())
        log.trace(f"Querying for preview firmware: {qry}")
        fw_list = list(qry)
        if fw_list:
            return [fw_list[0]]
    else:
        fw_list = list(Firmware.select().where((Firmware.board_id == board_id) & (Firmware.version == version)))
        if fw_list:
            return fw_list

    #
    more_board_ids = alternate_board_names(board_id, port)
    #
    log.debug(f"2nd search with renamed board_id :{board_id}")
    # <<<<<<< HEAD
    #     with Session() as session:
    #         if "preview" in version:
    #             query = session.query(Firmware).filter(Firmware.board_id.in_(more_board_ids))
    #             if port:
    #                 query = query.filter(Firmware.port == port)
    #             query = query.filter(Firmware.firmware_file.contains("preview")).order_by(Firmware.build.desc())
    #             fw_list = query.all()
    #             if fw_list:
    #                 return [fw_list[0]]
    #         else:
    #             query = session.query(Firmware).filter(Firmware.board_id.in_(more_board_ids), Firmware.version == version)
    #             if port:
    #                 query = query.filter(Firmware.port == port)
    #             fw_list = query.all()
    #             if fw_list:
    #                 return fw_list
    # =======
    if "preview" in version:
        qry = Firmware.select().where(Firmware.board_id.in_(more_board_ids))
        if port:
            qry = qry.where(Firmware.port == port)
        qry = qry.where(Firmware.firmware_file.contains("preview")).order_by(Firmware.build.desc())
        fw_list = list(qry)
        if fw_list:
            return [fw_list[0]]
    else:
        qry = Firmware.select().where((Firmware.board_id.in_(more_board_ids)) & (Firmware.version == version))
        if port:
            qry = qry.where(Firmware.port == port)
        fw_list = list(qry)
        if fw_list:
            return fw_list

    log.warning(f"No firmware files found for board {board_id} version {version}")
    return []
