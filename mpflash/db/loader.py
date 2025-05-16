import csv
import io
import json
import zipfile
from pathlib import Path
from turtle import up

from loguru import logger as log

from .core import Session, engine
from .meta import get_metadata, set_metadata_value
from .models import Board, Firmware

HERE = Path(__file__).parent.resolve()

def load_data_from_zip(zip_file: Path):
    log.debug("Loading data from zip file")
    csv_filename = "micropython_boards.csv"  # name of the .csv inside the .zip
    # Check if the zip file exists
    if not zip_file.exists() or not zip_file.is_file():
        log.error(f"Zip file {zip_file} not found.")
        return

    # Load data directly from the zip file
    with zipfile.ZipFile(zip_file, "r") as zipf:
        # Read the CSV file from the zip
        with zipf.open(csv_filename) as csv_file:
            log.info("Reading CSV data...")
            reader = csv.DictReader(io.TextIOWrapper(csv_file, "utf-8"))

            # save to database
            with Session() as session:
                for row in reader:
                    # Create a board instance from the row data
                    board = Board(**row)
                    # Use merge to update existing or insert new record
                    # based on primary key (board_id and version)
                    session.merge(board)
                session.commit()

def load_jsonl_to_db(jsonl_path: Path):
    """
    Load a JSONL file into a SQLite database

    Args:
        jsonl_path (Path): Path to the JSONL file
        conn (sqlite3.Connection): SQLite database connection
        table_name (str): Name of the table to insert data into

    Returns:
        int: Number of records imported
    """
    log.debug("Loading JSONL file into database")
    # Ensure file exists
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")
    num_records = 0
    with jsonl_path.open("r", encoding="utf-8") as file:
        with Session() as session:
            for line in file:
                record = json.loads(line.strip())
                # Clean up the record

                if "variant" in record:
                    record["board_id"] = record.pop("variant")  # Rename 'variant' to 'board_id'
                if "firmware" in record:
                    record["source"] = record.pop("firmware")  # Rename 'firmware' to 'source'
                if "preview" in record:
                    record["version"] = f"{record['version']}-preview" if record["preview"] else record["version"]
                    record.pop("preview", None)  # Remove 'preview' column
                firmware_file = str(Path(record["filename"]).as_posix()) if record["filename"] else ""

                # Check if Firmware with this firmware_file exists
                existing_fw = session.query(Firmware).filter_by(firmware_file=firmware_file).first()
                if existing_fw:
                    # Update fields
                    existing_fw.board_id = record["board_id"]
                    existing_fw.version = record["version"]
                    existing_fw.source = record["source"]
                    existing_fw.build = record["build"]
                    existing_fw.custom = record["custom"]
                    existing_fw.port = record["port"]
                else:
                    # Add new Firmware
                    fw = Firmware(
                        board_id=record["board_id"],
                        version=record["version"],
                        firmware_file=firmware_file,
                        source=record["source"],
                        build=record["build"],
                        custom=record["custom"],
                        port=record["port"],
                    )
                    session.merge(fw)
                num_records += 1
            # commit once after all records are processed
            session.commit()
    return num_records

def update_boards():
    meta = get_metadata()
    log.info(f"Metadata: {meta}")
    if meta.get("boards_version", "") < "v1.25.0":
        # Load data from the zip file into the database
        load_data_from_zip(HERE/"micropython_boards.zip")
        set_metadata_value("boards_version", "v1.25.0")
        meta = get_metadata()




