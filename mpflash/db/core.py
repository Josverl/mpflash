from pathlib import Path
from sqlite3 import DatabaseError, OperationalError

from loguru import logger as log
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mpflash.config import config

# TODO:  lazy import to avoid slowdowns ?
from .models import Base

TRACE = False
connect_str = f"sqlite:///{config.db_path.as_posix()}"
engine = create_engine(connect_str, echo=TRACE)
Session = sessionmaker(bind=engine)


def migrate_database(boards: bool = True, firmwares: bool = True):
    """Migrate from 1.24.x to 1.25.x"""
    # Move import here to avoid circular import
    from .loader import load_jsonl_to_db, update_boards

    # get the location of the database from the session
    with Session() as session:
        db_location = session.get_bind().url.database # type: ignore
        log.debug(f"Database location: {Path(db_location)}") # type: ignore

    create_database()
    if boards:

        update_boards()
    if firmwares:
        jsonl_file = config.firmware_folder / "firmware.jsonl"
        if jsonl_file.exists():
            log.info(f"Migrating JSONL data {jsonl_file} to SQLite database.")
            load_jsonl_to_db(jsonl_file)
            # rename the jsonl file to jsonl.bak
            log.info(f"Renaming {jsonl_file} to {jsonl_file.with_suffix('.jsonl.bak')}")
            try:
                jsonl_file.rename(jsonl_file.with_suffix(".jsonl.bak"))
            except OSError as e:
                for i in range(1, 10):
                    try:
                        jsonl_file.rename(jsonl_file.with_suffix(f".jsonl.{i}.bak"))
                        break
                    except OSError:
                        continue


def create_database():
    """
    Create the SQLite database and tables if they don't exist.
    """
    # Create the database and tables if they don't exist
    Base.metadata.create_all(engine)
