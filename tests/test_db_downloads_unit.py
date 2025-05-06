import sqlite3
from pathlib import Path

import pytest

from mpflash.common import FWInfo
from mpflash.db.create import create_database
from mpflash.db.downloads import (downloads_to_fwinfo, search_downloaded_fw,
                                  upsert_download)


@pytest.fixture
def memory_db():
    with sqlite3.connect(":memory:") as conn:
        # Create empty database
        create_database(conn)
        yield conn
    conn.close()


def test_upsert_download_and_search(memory_db, tmp_path):
    fw = FWInfo(
        port="usb",
        board="test_board",
        filename=(tmp_path / "fw.bin").as_posix(),
        url="http://example.com/fw.bin",  # This is used as 'source' in upsert_download
        variant="test_variant",           # This is used as 'board_id' in upsert_download
        version="1.0.0",
        build="1" ,
        ext="bin",
        family="test_family",
        custom=True,
        description="Test firmware"
    )
    memory_db.row_factory = sqlite3.Row  # Enable row factory to access columns by name
    upsert_download(memory_db, fw)
    memory_db.commit()
    cur = memory_db.execute("SELECT * FROM downloads WHERE filename = ?", (fw.filename,))
    row = cur.fetchone()
    assert row is not None
    assert row[1] == "test_board"
    # Update same row
    fw2 = FWInfo(**{**fw.__dict__, "description": "Updated desc"})
    upsert_download(memory_db, fw2)
    memory_db.commit()
    cur = memory_db.execute("SELECT * FROM downloads WHERE filename=?", (fw.filename,))
    row = cur.fetchone()
    assert row["description"] == "Updated desc"




# def test_search_downloaded_fw(memory_db, tmp_path):
#     # Insert a row into board_downloaded with board_id
#     memory_db.execute(
#         "INSERT INTO downloads (family, port, board_name, variant, filename, version, mcu, build, board_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
#         ("fam", "p", "b", "v", str(tmp_path / "f.bin"), "1.0", "mcu", 2, "b")
#     )
#     memory_db.commit()
#     result = search_downloaded_fw(Path(db_file.name), board_id="b", version="1.0", port="p")
#     assert result
#     assert result[0].family == "fam"
#     # import os
#     # os.unlink(db_file.name)

#     # import shutil
#     # import tempfile
#     # db_file = tempfile.NamedTemporaryFile(delete=False)
#     # db_file.close()
#     # backup_con = sqlite3.connect(db_file.name)
#     # with backup_con:
#     #     memory_db.backup(backup_con)
#     # backup_con.close()
#     # memory_db.close()  # Ensure all connections are closed before deleting