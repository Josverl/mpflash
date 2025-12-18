import sqlite3
from pathlib import Path

from loguru import logger as log

from mpflash.config import config
from mpflash.custom.copy import copy_firmware
from mpflash.custom.naming import custom_fw_from_path
from mpflash.db.core import Session
from mpflash.db.models import Firmware
from mpflash.errors import MPFlashError


def add_custom_firmware(
    fw_path: Path,
    force: bool = False,
    description: str = "",
    custom: bool = False,
) -> int:
    """Add a custom MicroPython firmware from a local file."""

    if not fw_path:
        log.error("No firmware path provided. Use --path to specify a firmware file.")
        raise MPFlashError("No firmware path provided.")
    fw_path = Path(fw_path).expanduser().resolve()
    if not fw_path.exists():
        log.error(f"Firmware file does not exist: {fw_path}")
        raise MPFlashError(f"Firmware file does not exist: {fw_path}")

    fw_dict = custom_fw_from_path(fw_path)
    if description:
        fw_dict["description"] = description
    if add_firmware(
        source=fw_path,
        fw_info=fw_dict,
        custom=custom,
        force=force,
    ):
        log.success(f"Added custom firmware: {fw_dict['custom_id']} for {fw_dict['firmware_file']}")
        return 0
    else:
        return 1


def add_firmware(
    source: Path,
    fw_info: dict,
    *,
    force: bool = False,
    custom: bool = False,
) -> bool:
    """
    Add a firmware to the database , and firmware folder.
    stored in the port folder, with the filename.

    fw_info is a dict with the following keys:
    - board_id: str, required
    - version: str, required
    - port: str, required
    - firmware_file: str, required, the filename to store in the firmware folder
    - source: str, optional, the source of the firmware, can be a local path
    - description: str, optional, a description of the firmware
    - custom: bool, optional, if the firmware is a custom firmware, default False
    """
    try:
        source = source.expanduser().absolute()
        if not source.exists() or not source.is_file():
            log.error(f"Source file {source} does not exist or is not a file")
            return False
        with Session() as session:
            # Check minimal info needed
            new_fw = Firmware(**fw_info)
            if custom:
                new_fw.custom = True

            if not new_fw.board_id:
                log.error("board_id is required")
                return False

            # assume the the firmware_file has already been prepared
            fw_filename = config.firmware_folder / new_fw.firmware_file

            if not copy_firmware(source, fw_filename, force):
                log.error(f"Failed to copy {source} to {fw_filename}")
                return False
            # add to inventory
            # check if the firmware already exists
            if custom:
                qry = session.query(Firmware).filter(Firmware.custom_id == new_fw.custom_id)
            else:
                qry = session.query(Firmware).filter(Firmware.board_id == new_fw.board_id)

            qry = qry.filter(
                Firmware.board_id == new_fw.board_id,
                Firmware.version == new_fw.version,
                Firmware.port == new_fw.port,
                Firmware.custom == new_fw.custom,
            )
            existing_fw = qry.first()

            if existing_fw:
                if not force:
                    log.warning(f"Firmware {existing_fw} already exists")
                    return False
                # update the existing firmware
                existing_fw.firmware_file = new_fw.firmware_file
                existing_fw.source = new_fw.source
                existing_fw.description = new_fw.description
                existing_fw.custom = custom
                if custom:
                    existing_fw.custom_id = new_fw.custom_id
            else:
                session.add(new_fw)
            session.commit()

        return True
    except sqlite3.DatabaseError as e:
        raise MPFlashError(f"Failed to add firmware {fw_info['firmware_file']}: {e}") from e
