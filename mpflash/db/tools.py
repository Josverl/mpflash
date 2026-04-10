import sqlite3
from pathlib import Path
from typing import List

from mpflash.config import config
from mpflash.errors import MPFlashError
from mpflash.logger import log


def backup_db(source_db: Path, backup_path: Path):
    """
    Backup the SQLite database to a specified path.

    Args:
        conn (sqlite3.Connection): SQLite connection object
        backup_path (str or Path): Path to save the backup file
    """

    # Ensure the backup directory exists
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(source_db)
    try:
        # Perform the backup
        with open(backup_path, "wb") as f:
            for line in conn.iterdump():
                f.write(f"{line}\n".encode("utf-8"))
    finally:
        conn.close()

    log.info(f"Backup created at {backup_path}")
