from typing import List

from loguru import logger as log

from mpflash.db.core import Session
from mpflash.db.models import Firmware
from mpflash.mpboard_id.alternate import alternate_board_names
from mpflash.versions import clean_version

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
    log.warning("No firmware files found. Please download the firmware first.")
    return []

