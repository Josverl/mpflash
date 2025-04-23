# update boardlist from zip
import zipfile
import io
import sqlite3
import json
from pathlib import Path
from mpflash.logger import log

HERE = Path(__file__).parent.resolve()


def load_data_from_zip(conn: sqlite3.Connection, zip_file: Path):
    log.debug("Loading data from zip file")
    csv_filename = "micropython_boards.csv"  # name of the .csv inside the .zip

    # Check if the zip file exists
    if not zip_file.exists() or not zip_file.is_file():
        log.error(f"Zip file {zip_file} not found.")
        return
    conn.row_factory = sqlite3.Row  # return rows as dicts

    # Load data directly from the zip file
    with zipfile.ZipFile(zip_file, "r") as zipf:
        # Read the CSV file from the zip
        with zipf.open(csv_filename) as csv_file:
            log.info("Reading CSV data...")
            header = None
            rows = []
            for line in io.TextIOWrapper(csv_file, "utf-8"):
                if header is None:
                    header = [col.strip() for col in line.split(",")]
                else:
                    row = [col.strip() for col in line.split(",")]
                    rows.append(row)

            # Replace None or empty strings with '' to avoid NULL values in the database
            rows = [[col or "" for col in row] for row in rows]

            if not header:
                log.error("No header found in the CSV file.")
                return
            # Insert data into the SQLite database
            placeholders = ", ".join("?" for _ in header)
            sql = f"INSERT INTO boards ({', '.join(header)}) VALUES ({placeholders})"
            conn.executemany(sql, rows)

    # Create indices for faster searching
    conn.execute("CREATE INDEX IF NOT EXISTS idx_version ON boards (version)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_id_version ON boards (board_id, version)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_descr ON boards (description)")

    conn.commit()


def load_jsonl_to_sqlite(jsonl_path: Path, conn: sqlite3.Connection, table_name="downloads"):
    """
    Load a JSONL file into a SQLite database without using pandas.

    Args:
        jsonl_path (Path): Path to the JSONL file
        conn (sqlite3.Connection): SQLite database connection
        table_name (str): Name of the table to insert data into

    Returns:
        int: Number of records imported
    """
    log.debug("Loading JSONL file into SQLite database")
    # Ensure file exists
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")

    log.info("Reading JSONL file...")
    record_count = 0
    cursor = conn.cursor()

    # First, remove all rows from the table
    conn.execute(f"DELETE FROM {table_name}")
    conn.commit()

    with jsonl_path.open("r", encoding="utf-8") as file:
        for line in file:
            record = json.loads(line.strip())
            # Clean up the record
            record.pop("url", None)  # Remove 'url' column if it exists
            if "variant" in record:
                record["board_id"] = record.pop("variant")  # Rename 'variant' to 'board_id'
            if "firmware" in record:
                record["source"] = record.pop("firmware")  # Rename 'firmware' to 'source'
            if "filename" in record:
                record["filename"] = (
                    str(Path(record["filename"]).as_posix()) if record["filename"] else ""
                )  # Convert filename to POSIX format
            if "preview" in record:
                record["version"] = f"{record['version']}-preview" if record["preview"] else record["version"]
                record.pop("preview", None)  # Remove 'preview' column

            # Insert the record into the database
            columns = ", ".join(f'"{key}"' for key in record.keys())
            placeholders = ", ".join("?" for _ in record.values())
            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
            cursor.execute(sql, tuple(record.values()))
            record_count += 1

    conn.commit()

    # Create indices for faster searching
    for col in ["board_id", "filename", "version"]:
        cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_dl_{col} ON {table_name} ("{col}")')

    conn.commit()
    log.info(f"Successfully imported {record_count} records")
    return record_count
