import csv
import io
import json
import zipfile
from pathlib import Path

from loguru import logger as log

from mpflash.errors import MPFlashError

from .meta import delete_metadata_value, get_metadata, set_metadata_value
from .models import Board, Firmware, database

HERE = Path(__file__).parent.resolve()


def load_data_from_zip(zip_file: Path) -> int:
    """Load board data from a CSV file inside a ZIP archive into the database."""
    log.debug("Loading data from zip file")
    csv_filename = "micropython_boards.csv"
    if not zip_file.exists() or not zip_file.is_file():
        log.error(f"Zip file {zip_file} not found.")
        return 0
    count = 0
    with zipfile.ZipFile(zip_file, "r") as zipf:
        with zipf.open(csv_filename) as csv_file:
            log.info("Reading CSV data...")
            reader = csv.DictReader(io.TextIOWrapper(csv_file, "utf-8"))

            with database.atomic():
                for row in reader:
                    # upsert: replace existing record if primary key matches
                    Board.insert(**row).on_conflict(
                        conflict_target=[Board.board_id, Board.version],
                        update=row,
                    ).execute()
                    count += 1
    log.info(f"Loaded {count} boards from {zip_file}")
    return count


def load_jsonl_to_db(jsonl_path: Path) -> int:
    """
    Load a JSONL file into the SQLite database.

    Args:
        jsonl_path: Path to the JSONL file.

    Returns:
        Number of records imported.
    """
    log.debug("Loading JSONL file into database")
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")

    num_records = 0
    with jsonl_path.open("r", encoding="utf-8") as file:
        with database.atomic():
            for line in file:
                record = json.loads(line.strip())

                if "variant" in record:
                    record["board_id"] = record.pop("variant")
                if "firmware" in record:
                    record["source"] = record.pop("firmware")
                if "preview" in record:
                    record["version"] = f"{record['version']}-preview" if record["preview"] else record["version"]
                    record.pop("preview", None)
                if "custom" not in record:
                    record["custom"] = False

                firmware_file = str(Path(record["filename"]).as_posix()) if record["filename"] else ""

                existing_fw = Firmware.get_or_none(Firmware.firmware_file == firmware_file)
                if existing_fw:
                    existing_fw.board_id = record["board_id"]
                    existing_fw.version = record["version"]
                    existing_fw.source = record["source"]
                    existing_fw.build = record["build"]
                    existing_fw.custom = record["custom"]
                    existing_fw.port = record["port"]
                    existing_fw.save()
                else:
                    Firmware.insert(
                        board_id=record["board_id"],
                        version=record["version"],
                        firmware_file=firmware_file,
                        source=record["source"],
                        build=record["build"],
                        custom=record["custom"],
                        port=record["port"],
                    ).on_conflict(
                        conflict_target=[Firmware.board_id, Firmware.version, Firmware.firmware_file],
                        update={
                            "source": record["source"],
                            "build": record["build"],
                            "custom": record["custom"],
                            "port": record["port"],
                        },
                    ).execute()
                num_records += 1

    return num_records


def get_boards_hash() -> str:
    """Return the board CSV content hash from the bundled hash file."""
    hash_file = HERE / "boards_hash.txt"
    if hash_file.is_file():
        boards_hash = hash_file.read_text(encoding="utf-8").strip()
        log.debug(f"Boards hash from file: {boards_hash}")
        return boards_hash
    log.warning(f"Boards hash file not found: {hash_file}")
    return "unknown"


def update_boards():
    """Update the boards table when the bundled CSV content hash has changed."""
    boards_hash = get_boards_hash()
    try:
        meta = get_metadata()
        log.debug(f"Metadata: {meta}")
        if meta.get("boards_hash") != boards_hash:
            log.info("Update boards from CSV to SQLite database.")
            load_data_from_zip(HERE / "micropython_boards.zip")
            set_metadata_value("boards_hash", boards_hash)
        delete_metadata_value("boards_version")
    except Exception as e:
        raise MPFlashError(f"Error updating boards table: {e}") from e
