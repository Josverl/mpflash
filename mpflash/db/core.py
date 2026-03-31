from pathlib import Path
from sqlite3 import DatabaseError, OperationalError

import peewee
from loguru import logger as log

from mpflash.config import config
from mpflash.errors import MPFlashError

from .models import Board, Firmware, Metadata, database

TRACE = False


def _init_database(db_path: Path = config.db_path) -> None:
    """Initialise the module-level Peewee database with the given path."""
    if TRACE:
        log.debug(f"Connecting to database at {db_path}")
    database.init(str(db_path))


# Initialise the database connection immediately on module load
_init_database()


class _SessionContext:
    """Thin context-manager shim so existing ``with Session() as session:``
    call-sites continue to work without modification.

    Within the context the database connection is opened (if needed) and
    wrapped in an atomic transaction.  ``session`` is the database object
    itself, which exposes ``execute_sql`` for raw SQL.
    """

    def __init__(self):
        self._atomic = None

    def __enter__(self):
        if database.is_closed():
            database.connect()
        self._atomic = database.atomic()
        self._atomic.__enter__()
        return _SessionProxy(database)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._atomic is not None:
            result = self._atomic.__exit__(exc_type, exc_val, exc_tb)
            return result
        return False


class _SessionProxy:
    """Proxy that exposes the subset of the SQLAlchemy Session API used by
    the rest of mpflash, translated into Peewee calls."""

    def __init__(self, db: peewee.SqliteDatabase):
        self._db = db

    # ------------------------------------------------------------------
    # Raw SQL
    # ------------------------------------------------------------------
    def execute(self, query, params=None):
        """Execute a raw SQL string (accepts Peewee SQL objects or plain strings)."""
        sql = str(query)
        return self._db.execute_sql(sql, params)

    # ------------------------------------------------------------------
    # Transaction helpers (no-ops when inside _SessionContext)
    # ------------------------------------------------------------------
    def commit(self):
        """No-op: the enclosing ``_SessionContext`` uses Peewee's ``atomic()``
        context manager which commits on ``__exit__``.  Kept for API
        compatibility with call-sites that were written against SQLAlchemy."""
        pass

    def rollback(self):
        """Roll back the current transaction."""
        self._db.rollback()

    def get_bind(self):
        """Return a minimal object that exposes ``url.database`` as the DB path.

        Only used in the legacy ``migrate_database`` function.
        """

        class _Url:
            database = str(config.db_path)

        class _Bind:
            url = _Url()

        return _Bind()


# Public "Session" is a factory: ``Session()`` returns a _SessionContext
class _SessionFactory:
    """Callable that returns a fresh _SessionContext each time."""

    def __call__(self):
        return _SessionContext()


Session = _SessionFactory()


# ---------------------------------------------------------------------------
# Schema-version helpers
# ---------------------------------------------------------------------------


def get_schema_version() -> int:
    """Get current database schema version."""
    from .meta import get_metadata_value

    version = get_metadata_value("schema_version")
    return int(version) if version else 0


def set_schema_version(version: int) -> None:
    """Set database schema version."""
    from .meta import set_metadata_value

    set_metadata_value("schema_version", str(version))


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def migration_001_add_custom_id() -> None:
    """Add custom_id column to firmwares table."""
    log.info("Running migration 001: Add custom_id column to firmwares table")

    result = database.execute_sql("PRAGMA table_info(firmwares)").fetchall()
    columns = [row[1] for row in result]

    if "custom_id" not in columns:
        database.execute_sql("ALTER TABLE firmwares ADD COLUMN custom_id VARCHAR(40)")
        database.execute_sql(
            "CREATE INDEX IF NOT EXISTS idx_firmwares_custom_id ON firmwares(custom_id)"
        )
        log.info("Added custom_id column and index to firmwares table")
    else:
        log.info("custom_id column already exists in firmwares table")
        result = database.execute_sql("PRAGMA index_list(firmwares)").fetchall()
        index_names = [row[1] for row in result]
        if "idx_firmwares_custom_id" not in index_names:
            database.execute_sql(
                "CREATE INDEX IF NOT EXISTS idx_firmwares_custom_id ON firmwares(custom_id)"
            )
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
        if current_version < 1:
            migration_001_add_custom_id()

        set_schema_version(target_version)
        log.info(f"Database schema upgraded to version {target_version}")

    except peewee.PeeweeException as e:
        log.error(f"Migration failed: {e}")
        raise MPFlashError(f"Failed to migrate database schema: {e}")


# ---------------------------------------------------------------------------
# Database creation / data loading
# ---------------------------------------------------------------------------


def migrate_database(boards: bool = True, firmwares: bool = True):
    """Migrate from 1.24.x to 1.25.x and run schema migrations."""
    from .loader import load_jsonl_to_db, update_boards

    db_location = str(config.db_path)
    log.debug(f"Database location: {Path(db_location)}")

    try:
        create_database()
    except (DatabaseError, OperationalError) as e:
        log.error(f"Error creating database: {e}")
        log.error("Database might already exist, trying to migrate.")
        raise MPFlashError("Database migration failed. Please check the logs for more details.") from e

    run_schema_migrations()

    if boards:
        update_boards()
    if firmwares:
        jsonl_file = config.firmware_folder / "firmware.jsonl"
        if jsonl_file.exists():
            log.info(f"Migrating JSONL data {jsonl_file} to SQLite database.")
            load_jsonl_to_db(jsonl_file)
            log.info(f"Renaming {jsonl_file} to {jsonl_file.with_suffix('.jsonl.bak')}")
            try:
                jsonl_file.rename(jsonl_file.with_suffix(".jsonl.bak"))
            except OSError:
                for i in range(1, 10):
                    try:
                        jsonl_file.rename(jsonl_file.with_suffix(f".jsonl.{i}.bak"))
                        break
                    except OSError:
                        continue


def create_database():
    """Create the SQLite database and tables if they don't exist."""
    if database.is_closed():
        database.connect()
    database.create_tables([Metadata, Board, Firmware], safe=True)

    # Run schema migrations after table creation
    run_schema_migrations()
