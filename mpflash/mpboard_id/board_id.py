"""
Translate board description to board designator
"""

from typing import List, Optional

from mpflash.db.models import Board
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.versions import clean_version


def find_board_id_by_description(
    descr: str,
    short_descr: str,
    *,
    version: str,
) -> str:
    """Find the MicroPython BOARD_ID based on the description in the firmware"""
    version = clean_version(version) if version else ""
    boards = _find_board_id_by_description(
        descr=descr,
        short_descr=short_descr,
        version=version,
    )
    if not boards:
        log.debug(f"Version {version} not found in board info, using any version")
        boards = _find_board_id_by_description(
            descr=descr,
            short_descr=short_descr,
            version="%",  # any version
        )
    if not boards:
        raise MPFlashError(f"No board info found for description '{descr}' or '{short_descr}'")
    return boards[0].board_id


def _find_board_id_by_description(
    *,
    descr: str,
    short_descr: str,
    version: Optional[str] = None,
    variant: str = "",
):
    short_descr = short_descr or ""
    boards: List[Board] = []
    version = clean_version(version) if version else "%"
    if "-preview" in version:
        version = version.replace("-preview", "%")
    descriptions = [descr, short_descr]
    if descr.startswith("Generic"):
        descriptions.append(descr[8:])
        descriptions.append(short_descr[8:])

    qry = Board.select().where(
        Board.description.in_(descriptions),
        Board.version ** version,   # ** is LIKE in Peewee
        Board.variant ** variant,
    )
    boards = list(qry)
    return boards
