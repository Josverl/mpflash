from pathlib import Path

import pytest

from mpflash.db.tools import backup_db


def test_backup_db(test_db: Path, tmp_path: Path):
    """
    Test the backup_db function.
    """
    # Prepare test data
    backup_file = tmp_path / "backup_mpflash.db"

    # Call the function
    backup_db(test_db, backup_file)

    # Check if the backup file exists
    assert backup_file.exists()

    # Clean up
    backup_file.unlink()
