import sqlite3
from pathlib import Path
from typing import List
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.config import config


def query( query: str = "",db_path: Path | None = None) -> List[sqlite3.Row]:
    """Run a query on the database and return the results"""
    db_path = db_path or config.db_path
    if not db_path.exists():
        raise MPFlashError(f"Database {db_path} not found.")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = []
    with conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
    return rows

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
