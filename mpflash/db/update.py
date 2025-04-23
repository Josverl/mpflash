from math import e
from pathlib import Path
import sqlite3
from typing import Optional
from packaging.version import Version
from mpflash.config import config
from mpflash.logger import log
from .load import load_data_from_zip, load_jsonl_to_sqlite
from .create import create_schema, create_views, get_database_version, set_database_version, update_boardlist_schema

HERE = Path(__file__).parent.resolve()


def update_database(v_goal="1.24.1"):
    """
    Update the SQLite database to the specified version.
    """
    db_path = config.db_path

    log.debug(f"Updating database {db_path} to version {v_goal}")

    with sqlite3.connect(db_path) as conn:
        if not get_database_version(conn):
            create_schema(conn)
            set_database_version(conn, "0.0.1")
        current = get_database_version(conn)
        if not current or Version(current) < Version(v_goal):
            update_boardlist_schema(conn)

            # Create/update views
            create_views(conn)

            set_database_version(conn, v_goal)

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
