from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

from mpflash.common import FWInfo
from mpflash.config import config
from mpflash.logger import log


def upsert_download(conn: sqlite3.Connection, board: FWInfo):
    """
    Adds a row to the downloaded firmware table in the database.
      - downloads.board_id <-- FWInfo.variant
      - downloads.source   <-- FWInfo.firmware

    Args:
        conn : The database connection to use.
        board : The firmware information to add to the database.

    """
    with conn:
        conn.execute(
            """
            INSERT INTO downloads 
                (port, board, filename, source, board_id, version, build, ext, family, custom, description) 
            VALUES 
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                port=excluded.port,
                board=excluded.board,
                source=excluded.source,
                board_id=excluded.board_id,
                version=excluded.version,
                build=excluded.build,
                ext=excluded.ext,
                family=excluded.family,
                custom=excluded.custom,
                description=excluded.description
            """,
            (
                board.port,
                board.board,
                Path(board.filename).as_posix() if board.filename else "",
                board.url,
                board.variant,
                board.version,
                board.build,
                board.ext,
                board.family,
                board.custom,
                board.description,
            ),
        )
        conn.commit()


# def downloaded_fw(db_path: Path | None = None) -> List[FWInfo]:
#     """Load a list of locally downloaded firmwares from the database"""
#     db_path = db_path or config.db_path
#     assert db_path.is_file() and db_path.exists(), f"Database {db_path} not found."
#     with sqlite3.connect(db_path) as conn:
#         try:
#             conn.row_factory = sqlite3.Row
#             cursor = conn.cursor()
#             cursor.execute("SELECT * FROM downloads")
#             rows = cursor.fetchall()
#         except sqlite3.Error as e:
#             log.error(f"Database error: {e}")
#     return rows_to_fwinfo(rows)


def search_downloaded_fw(
    conn: sqlite3.Connection | None = None,
    board_id: str = "%",
    version: str = "%",
    port="%",
    variant: str = "%",
) -> List[FWInfo]:
    """Load a list of locally downloaded firmwares from the database"""

    if not conn:
        closeme = True
        conn = sqlite3.connect(config.db_path)
    else:
        closeme = False

    qry = """
        SELECT * FROM downloads
        WHERE filename NOT NULL and board_id LIKE ? AND version LIKE ? AND port LIKE ? 
    """
    if "preview" in version:
        version = f"%{version}"
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(qry, (board_id, version, port))
        rows = cursor.fetchall()
    except sqlite3.Error as e:
        log.error(f"Database error: {e}")
    finally:
        if closeme:
            conn.close()
    return downloads_to_fwinfo(rows)


def downloads_to_fwinfo(rows) -> List[FWInfo]:
    firmwares: List[FWInfo] = []
    for row in rows:
        fw_info = FWInfo.from_dict(dict(row))
        firmwares.append(fw_info)
    # sort by filename
    firmwares.sort(key=lambda x: x.filename)
    return firmwares

