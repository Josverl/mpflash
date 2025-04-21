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
                board.filename,
                board.firmware,
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

def downloaded(db_path: Path | None = None) -> List[FWInfo]:
    """Load a list of locally downloaded firmwares from the database"""
    db_path = db_path or config.db_path
    with sqlite3.connect(db_path) as conn:
        firmwares: List[FWInfo] = []
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM downloads")
            rows = cursor.fetchall()
            for row in rows:
                fw_info = FWInfo.from_dict(
                    {
                        "filename": row["filename"],
                        "version": row["version"],
                        "board": row["board"],
                        "variant": row["board_id"],
                        "port": row["port"],
                        "firmware": row["source"],
                        "build": row["build"],
                        "preview": 1 if int(row["build"]) > 0 else 0,
                    }
                )
                firmwares.append(fw_info)
        except sqlite3.Error as e:
            log.error(f"Database error: {e}")

    # sort by filename
    firmwares.sort(key=lambda x: x.filename)
    return firmwares