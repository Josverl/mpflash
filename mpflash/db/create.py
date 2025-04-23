"""
Functions to update the board ID database with fresh content , and to migrate the jsonl files to a database table.
"""

from pathlib import Path
from mpflash.vendor.board_database import Database
from mpflash.logger import log


# Views

import sqlite3


def create_views(conn: sqlite3.Connection):
    """
    Create views for the SQLite database.

    Args:
        conn (sqlite3.Connection): SQLite connection object
    """
    log.debug("Creating database views")
    cursor = conn.cursor()

    views = {
        "latest_boards": """
            SELECT b.*, d.version, d.filename, d.source
            FROM boards b
            LEFT JOIN downloads d ON b.board_id = d.board_id AND b.version = d.version
        """,
        "board_downloaded": """
            SELECT 
                b.board_id,
                b.board_name ,
                UPPER(b.variant) as variant,
                b.description,
                LOWER(b.mcu) as mcu,
                b.version as version,
                b.path,
                b.port as port,
                b.family as family,
                d.version as download_version,
                d.build,
                d.filename

            FROM
                boards b
            left JOIN 
                downloads d 
            ON 
                b.board_id = d.board_id
                AND d.version LIKE b.version || '%'
            ORDER BY
                d.version DESC,
                d.build DESC,
                d.board_id;
        """,
        "board_variants_versions": """
        SELECT 
            UPPER(board_name) as board_name,
            json_group_array (DISTINCT UPPER(variant)) AS variants,
            json_group_array (DISTINCT (version)) AS versions
        FROM boards
        GROUP BY UPPER(board_name)
        ORDER BY UPPER(board_name)
        """,
        "board_id_versions": """
        SELECT 
            UPPER(board_id) as board_id,
            json_group_array (DISTINCT (version)) AS versions
        FROM boards
        GROUP BY UPPER(board_id)
        ORDER BY UPPER(board_id)
        """,
    }

    # Drop existing views if they exist
    for view_name in views:
        cursor.execute(f"DROP VIEW IF EXISTS {view_name}")

    # Create new views
    for view_name, query in views.items():
        cursor.execute(f"CREATE VIEW {view_name} AS {query}")

    conn.commit()


# create basic schema
import sqlite3


def create_schema(conn: sqlite3.Connection):
    log.debug("Creating database tables")
    with conn:
        # Create metadata table if it doesn't exist
        conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # Create the same table schema
        conn.execute("""
        CREATE TABLE IF NOT EXISTS boards (
            "version" TEXT NOT NULL,
            "board_id" TEXT NOT NULL,
            "board_name" TEXT,
            "mcu" TEXT,
            "variant" TEXT,
            "path" TEXT,
            "description" TEXT,
            "text" TEXT,
            "port" TEXT DEFAULT "",
            "family" TEXT DEFAULT "micropython",
            PRIMARY KEY(version, board_id)
        )
        """)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                port TEXT,
                board TEXT,
                filename TEXT PRIMARY KEY,
                source TEXT,
                board_id TEXT,
                version TEXT,
                build TEXT,
                ext TEXT,
                family TEXT,
                custom TEXT,
                description TEXT
            )
            """
        )

        conn.commit()

        create_views(conn)


# metadata


from mpflash.config import config
import sqlite3


def get_database_version(conn: sqlite3.Connection):
    # Connect to the SQLite database and fetch the version

    cursor = conn.cursor()

    # Query for the 'version' key
    try:
        cursor.execute("SELECT value FROM metadata WHERE key = ?", ("version",))
    except sqlite3.OperationalError as e:
        return None
    # Result will be None if not found, otherwise will contain the value
    value = value[0] if (value := cursor.fetchone()) else None
    return value


def set_database_version(conn: sqlite3.Connection, version: str):
    # Connect to the SQLite database and set the version
    with sqlite3.connect(config.db_path) as conn:
        cursor = conn.cursor()
        # Create metadata table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        conn.commit()
        # Insert or replace the version value
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", ("version", version))
        conn.commit()


def update_boardlist_schema(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row  # return rows as dicts

    # Create indices for faster searching
    conn.execute("CREATE INDEX IF NOT EXISTS idx_version ON boards (version)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_id_version ON boards (board_id,version)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_descr ON boards (description)")

    conn.commit()
