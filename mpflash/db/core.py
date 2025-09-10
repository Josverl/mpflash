from pathlib import Path
from sqlite3 import DatabaseError, OperationalError

from loguru import logger as log
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from mpflash.config import config
from mpflash.errors import MPFlashError

from .models import Base

TRACE = False
connect_str = f"sqlite:///{config.db_path.as_posix()}"
if TRACE:
    log.debug(f"Connecting to database at {connect_str}")
engine = create_engine(connect_str, echo=TRACE)
Session = sessionmaker(bind=engine)


def get_schema_version() -> int:
    """Get current database schema version."""
    from .meta import get_metadata_value

    version = get_metadata_value("schema_version")
    return int(version) if version else 0


def set_schema_version(version: int) -> None:
    """Set database schema version."""
    from .meta import set_metadata_value

    set_metadata_value("schema_version", str(version))


def migration_001_add_custom_id() -> None:
    """Add custom_id column to firmwares table."""
    log.info("Running migration 001: Add custom_id column to firmwares table")

    with Session() as session:
        # Check if column already exists
        result = session.execute(text("PRAGMA table_info(firmwares)")).fetchall()

        columns = [row[1] for row in result]
        if "custom_id" not in columns:
            # Add column without UNIQUE constraint
            session.execute(text("ALTER TABLE firmwares ADD COLUMN custom_id VARCHAR(40)"))

            # Create regular index for performance
            session.execute(text("CREATE INDEX IF NOT EXISTS idx_firmwares_custom_id ON firmwares(custom_id)"))

            session.commit()
            log.info("Added custom_id column and index to firmwares table")
        else:
            log.info("custom_id column already exists in firmwares table")

            # Check if index exists and create if needed
            result = session.execute(text("PRAGMA index_list(firmwares)")).fetchall()

            index_names = [row[1] for row in result]
            if "idx_firmwares_custom_id" not in index_names:
                session.execute(text("CREATE INDEX IF NOT EXISTS idx_firmwares_custom_id ON firmwares(custom_id)"))
                session.commit()
                log.info("Added index to existing custom_id column")


def run_schema_migrations() -> None:
    """Run all pending database schema migrations."""
    current_version = get_schema_version()
    target_version = 1  # Current latest version

    if current_version >= target_version:
        log.debug(f"Database schema is up to date (version {current_version})")
        return

    log.info(f"Upgrading database schema from version {current_version} to {target_version}")

    try:
        # Run migrations in order
        if current_version < 1:
            migration_001_add_custom_id()

        # Update schema version
        set_schema_version(target_version)
        log.info(f"Database schema upgraded to version {target_version}")

    except SQLAlchemyError as e:
        log.error(f"Migration failed: {e}")
        raise MPFlashError(f"Failed to migrate database schema: {e}")


def migrate_database(boards: bool = True, firmwares: bool = True):
    """Migrate from 1.24.x to 1.25.x and run schema migrations."""
    # Move import here to avoid circular import
    from .loader import load_jsonl_to_db, update_boards

    # get the location of the database from the session
    with Session() as session:
        db_location = session.get_bind().url.database  # type: ignore
        log.debug(f"Database location: {Path(db_location)}")  # type: ignore

    try:
        create_database()
    except (DatabaseError, OperationalError) as e:
        log.error(f"Error creating database: {e}")
        log.error("Database might already exist, trying to migrate.")
        raise MPFlashError("Database migration failed. Please check the logs for more details.") from e

    # Run schema migrations after creating database
    run_schema_migrations()

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
    """Create the SQLite database and tables if they don't exist."""
    # Create the database and tables if they don't exist
    Base.metadata.create_all(engine)

    # Run schema migrations after table creation
    run_schema_migrations()
