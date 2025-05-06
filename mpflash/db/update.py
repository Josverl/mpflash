
import sqlite3
from pathlib import Path
from typing import Optional

from mpflash.config import config
from mpflash.logger import log

from .create import create_database
from .load import load_data_from_zip, load_jsonl_to_sqlite

HERE = Path(__file__).parent.resolve()

def update_database(v_goal=""):
    """
    Update the SQLite database to the specified version.
    """
    v_goal = v_goal or config.db_version
    db_path = config.db_path
    log.debug(f"Updating database {db_path} to version {v_goal}")

    with sqlite3.connect(db_path) as conn:
        # Create the database and initialize it with the schema if it doesn't exist
        create_database(conn, v_goal)
        zip_file = HERE / "micropython_boards.zip"
        load_data_from_zip(conn, zip_file)
        # Test retrieving some data
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM boards")
        record_count = cursor.fetchone()[0]
        log.info(f"Total records stored in database from zip: {record_count}")


def migrate_jsonl(jsonl_file: Optional[Path] = None, db_path: Optional[Path] = None):
    jsonl_file = jsonl_file or config.firmware_folder / "firmware.jsonl"
    db_path = db_path or config.db_path
    with sqlite3.connect(db_path) as conn:
        # Execute the function
        if jsonl_file.exists() and jsonl_file.is_file():
            log.debug(f"Loading JSONL file {jsonl_file} into database...")
            record_count = load_jsonl_to_sqlite(jsonl_file, conn)
            log.success(f"Total records imported from JSONL: {record_count}")
            for n in range(1, 10):
                try:
                    jsonl_file.rename(jsonl_file.with_suffix(f".jsonl.{n}.bak"))
                    break
                except Exception as e:
                    if n == 9:
                        log.error(f"Failed to rename {jsonl_file} to {jsonl_file.with_suffix(f'.jsonl.{n}.bak')}: {e}")
        else:
            log.warning(f"JSONL file {jsonl_file} not found. Skipping import.")
