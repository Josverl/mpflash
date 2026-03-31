import sqlite3
from pathlib import Path

from loguru import logger as log

from mpflash.custom.naming import custom_fw_from_path
from mpflash.db.models import Firmware, database
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
    Add a firmware to the database, and firmware folder.
    Stored in the port folder, with the filename.

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
        from mpflash import custom as custom_pkg

        config = custom_pkg.config
        copy_fn = custom_pkg.copy_firmware
        source = source.expanduser().absolute()
        if not source.exists() or not source.is_file():
            log.error(f"Source file {source} does not exist or is not a file")
            return False

        new_fw = Firmware(**fw_info)
        if custom:
            new_fw.custom = True

        if not new_fw.board_id:
            log.error("board_id is required")
            return False

        fw_filename = config.firmware_folder / new_fw.firmware_file

        if not copy_fn(source, fw_filename, force):
            log.error(f"Failed to copy {source} to {fw_filename}")
            return False

        # check if the firmware already exists
        if custom:
            qry = Firmware.select().where(Firmware.custom_id == new_fw.custom_id)
        else:
            qry = Firmware.select().where(Firmware.board_id == new_fw.board_id)

        qry = qry.where(
            (Firmware.board_id == new_fw.board_id)
            & (Firmware.version == new_fw.version)
            & (Firmware.port == new_fw.port)
            & (Firmware.custom == new_fw.custom)
        )
        existing_fw = qry.first()

        with database.atomic():
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
                existing_fw.save()
            else:
                new_fw.save(force_insert=True)

        return True
    except sqlite3.DatabaseError as e:
        raise MPFlashError(f"Failed to add firmware {fw_info['firmware_file']}: {e}") from e
