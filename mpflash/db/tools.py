import sqlite3
from pathlib import Path
from typing import List
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.config import config



def backup_db(conn: sqlite3.Connection, backup_path: Path):
    """
    Backup the SQLite database to a specified path.

    Args:
        conn (sqlite3.Connection): SQLite connection object
        backup_path (str or Path): Path to save the backup file
    """
    # Ensure the backup directory exists
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    # Perform the backup
    with open(backup_path, "wb") as f:
        for line in conn.iterdump():
            f.write(f"{line}\n".encode("utf-8"))

    log.info(f"Backup created at {backup_path}")
