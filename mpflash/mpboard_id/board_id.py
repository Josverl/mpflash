"""
Translate board description to board designator
"""


from pathlib import Path
from typing import List, Optional

from mpflash.config import config
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpboard_id.board import Board
from mpflash.versions import clean_version

from mpflash.db import query

def find_board_id_by_description(
    descr: str,
    short_descr: str,
    *,
    version: str,
    board_info: Optional[Path] = None,
) -> Optional[str]:
    """Find the MicroPython BOARD_ID based on the description in the firmware"""
    version = clean_version(version) if version else ""
    try:
        boards = _find_board_id_by_description(
            descr=descr,
            short_descr=short_descr,
            db_path=board_info,
            version=version,
        )
        if not boards:
            log.debug(f"Version {version} not found in board info, using any version")
            boards = _find_board_id_by_description(
                descr=descr,
                short_descr=short_descr,
                db_path=board_info,
                version="%",  # any version
            )
        return boards[0].board_id if boards else None
    except MPFlashError:
        return "UNKNOWN_BOARD"


def _find_board_id_by_description(
    *,
    descr: str,
    short_descr: str,
    version: Optional[str] = None,
    variant: str = "",
    db_path: Optional[Path] = None,
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

    qry = f"""
    SELECT 
        *
    FROM board_downloaded
    WHERE 
        board_id IN (
            SELECT  DISTINCT board_id
            FROM board_downloaded
            WHERE description IN {tuple(descriptions)}
        )
        AND version like '{version}'
        AND variant like '{variant}'
    """
    rows = query(qry, db_path=db_path)
    boards.extend(Board.from_dict(dict(row)) for row in rows)
    if not boards:
        raise MPFlashError(f"No board info found for description '{descr}' or '{short_descr}'")
    return boards

