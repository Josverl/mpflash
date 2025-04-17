"""
Translate board description to board designator
"""

import functools
import re
import sqlite3
from pathlib import Path
from typing import List, Optional

from mpflash.config import config
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.mpboard_id.board import Board
from mpflash.mpboard_id.store import read_known_boardinfo
from mpflash.versions import clean_version, get_preview_mp_version, get_stable_mp_version


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

    try:
        with sqlite3.connect(db_path or config.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            qry = f"""
            SELECT 
                *
            FROM board_downloaded
            WHERE 
                board_id IN (
                    SELECT  DISTINCT board_id
                    FROM board_downloaded
                    WHERE description IN {str(tuple(descriptions))}
                )
                AND version like '{version}'
                AND variant like '{variant}'
            """
            cursor.execute(qry)
            rows = cursor.fetchall()
            for row in rows:
                r = dict(row)

                boards.append(Board.from_dict(dict(row)))
    except sqlite3.OperationalError as e:
        raise MPFlashError("Database error") from e
    if not boards:
        raise MPFlashError(f"No board info found for description '{descr}' or '{short_descr}'")
    return boards


@functools.lru_cache(maxsize=20)
def _find_board_id_by_description_xx(
    *,
    descr: str,
    short_descr: str,
    version: Optional[str] = None,
    board_info: Optional[Path] = None,
):
    """
    Find the MicroPython BOARD_ID based on the description in the firmware
    using the pre-built board_info.json file

    Parameters:
    descr: str
        Description of the board
    short_descr: str
        Short description of the board (optional)
    version: str
        Version of the MicroPython firmware
    board_info: Path
        Path to the board_info.json file (optional)

    """
    # Some functional overlap with
    # src\mpflash\mpflash\mpboard_id\__init__.py find_known_board

    candidate_boards = read_known_boardinfo(board_info)
    if not short_descr and " with " in descr:
        short_descr = descr.split(" with ")[0]
    if version:
        # filter for matching version
        if version in ("stable"):
            version = get_stable_mp_version()
        if version in ("preview", "master"):
            version = get_preview_mp_version()
        known_versions = sorted({b.version for b in candidate_boards})
        if version not in known_versions:
            log.trace(known_versions)
            log.debug(f"Version {version} not found in board info, using latest stable version {get_stable_mp_version()}")
            version = ".".join(get_stable_mp_version().split(".")[:2])  # take only major.minor
        if version_matches := [b for b in candidate_boards if b.version.startswith(version)]:
            candidate_boards = version_matches
        else:
            raise MPFlashError(f"No board info found for version {version}")
    # First try full match on description, then partial match
    matches = [b for b in candidate_boards if b.description == descr]
    if not matches and short_descr:
        matches = [b for b in candidate_boards if b.description == short_descr]
    if not matches:
        # partial match (for added VARIANT)
        matches = [b for b in candidate_boards if b.description.startswith(descr)]
        if not matches and short_descr:
            matches = [b for b in candidate_boards if b.description.startswith(short_descr)]
    if not matches:
        raise MPFlashError(f"No board info found for description '{descr}' or '{short_descr}'")
    return sorted(matches, key=lambda x: x.version)
