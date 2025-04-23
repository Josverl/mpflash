from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

from mpflash.common import FWInfo
from mpflash.config import config
from mpflash.logger import log


def find_board_id(db_path: Path | None = None, board_id: str = "", description: str = "", version: str = "%") -> List[str]:
    """Get a list of board IDs from the database based on the board ID or description"""
    db_path = db_path or config.db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = []
    with conn:
        cursor = conn.cursor()

        query = """
        SELECT DISTINCT board_id FROM board_downloaded
        where board_id like ? and version like ?
        ORDER BY `version` ASC
        """
        cursor.execute(query, (board_id, version))
        rows = cursor.fetchall()
        if len(rows) == 0:
            cursor.execute(
                """
                SELECT DISTINCT description FROM board_downloaded
                where description like ? and version like ?
                ORDER BY `description` ASC
                """,
                (description, version),
            )
            rows = cursor.fetchall()

    return [row["board_id"] for row in rows]


def find_board_info(db_path: Path | None = None, board_id: str = "", version: str = "%") -> List[sqlite3.Row]:
    """get a list of board rows  from the database based on the board ID and version"""
    db_path = db_path or config.db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = []
    with conn:
        cursor = conn.cursor()
        query = """
        SELECT * FROM board_downloaded
        where board_id like ? and version like ?
        ORDER BY board_id, version ASC
        """
        cursor.execute(
            query,
            (
                board_id,
                version,
            ),
        )
        rows = cursor.fetchall()

    return rows
