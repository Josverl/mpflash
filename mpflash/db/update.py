from math import e
from pathlib import Path
import sqlite3
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
    log.debug(f"Updating database to version {v_goal}")

    with sqlite3.connect(config.db_path) as conn:
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



def migrate_jsonl():
    log.debug("Migrating JSONL data to SQLite database")
    with sqlite3.connect(config.db_path) as conn:
        # Execute the function
        jsonl_path = config.firmware_folder /  "firmware.jsonl"
        if jsonl_path.exists() and jsonl_path.is_file():
            log.info(f"Loading JSONL file {jsonl_path} into database...")
            record_count = load_jsonl_to_sqlite(jsonl_path, conn)
            log.success(f"Total records imported from JSONL: {record_count}")
            for n in range(1, 10):
                try:
                    jsonl_path.rename(jsonl_path.with_suffix(f".jsonl.{n}.bak"))
                    break
                except Exception as e:
                    log.debug(f"Failed to rename {jsonl_path} to {jsonl_path.with_suffix(f'.jsonl.{n}.bak')}: {e}")
        else:
            log.warning(f"JSONL file {jsonl_path} not found. Skipping import.")

                