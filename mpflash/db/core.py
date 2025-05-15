
from pathlib import Path
from sqlite3 import DatabaseError, OperationalError

from loguru import logger as log
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mpflash.config import config

from .models import Base

TRACE = True
# TODO: Add location from config 
# Full path to the SQLite database file
db_file = Path("d:/mypython/mpflash/mpflash.db")
connect_str = f"sqlite:///{db_file.as_posix()}"
engine = create_engine(connect_str, echo=TRACE)
Session = sessionmaker(bind=engine)

# TODO:  lazy import to avoid slowdowns ?
from .loader import load_jsonl_to_db, update_boards


def migrate_database(boards:bool=True, firmwares:bool=True):
    """Migrate from 1.24.x to 1.25.x"""
    create_database()
    if boards:
        log.info("Update boards from CSV to SQLite database.")
        update_boards()
    if firmwares:
        jsonl_file = config.firmware_folder / "firmware.jsonl"
        if jsonl_file.exists():
            log.info(f"Migrating JSONL data {jsonl_file}to SQLite database.")
            load_jsonl_to_db(jsonl_file)
        if False:
            # Rename the original JSONL file to a backup
            log.info(f"Renaming {jsonl_file} to {jsonl_file.with_suffix('.jsonl.bak')}")


def create_database():
    """
    Create the SQLite database and tables if they don't exist.
    """
    # Create the database and tables if they don't exist
    Base.metadata.create_all(engine)


