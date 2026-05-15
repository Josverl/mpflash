"""Unit tests for mpflash.build module.

Regression coverage for the original ImportError on `mpflash flash --build`
(build.py imported a non-existent `Session` from `mpflash.db.core`) and for
the Peewee-based `import_firmware_to_database` upsert path.
"""

from pathlib import Path

import pytest

from mpflash.db.models import Board, Firmware


def test_build_module_imports():
    """Regression: `mpflash flash --build` failed with ImportError on
    `from mpflash.db.core import Session`. Ensure the module imports clean."""
    import mpflash.build as build_mod

    assert hasattr(build_mod, "BuildManager")
    assert hasattr(build_mod, "build_firmware")
    assert hasattr(build_mod, "import_firmware_to_database")
    assert hasattr(build_mod, "is_build_available")
    assert hasattr(build_mod, "get_build_unavailable_reason")


def test_cli_flash_build_block_imports():
    """Regression: the lazy import inside `cli_flash_board` must succeed.

    `mpflash flash --build` exercises a deferred import of build symbols
    inside the Click callback; reproduce that exact import to guard against
    future drift.
    """
    from mpflash.build import (  # noqa: F401
        build_firmware,
        get_build_unavailable_reason,
        import_firmware_to_database,
        is_build_available,
    )


def test_import_firmware_to_database_inserts(tmp_path, db_fx):
    """`import_firmware_to_database` should insert Board + Firmware rows."""
    from mpflash.build import import_firmware_to_database

    fw_file = tmp_path / "firmware.bin"
    fw_file.write_bytes(b"\x00" * 16)

    count = import_firmware_to_database(
        firmware_files=[fw_file],
        board_id="BUILT_TEST_BOARD",
        version="v9.99.0",
        port="stm32",
    )

    assert count == 1
    assert Board.select().where(Board.board_id == "BUILT_TEST_BOARD").count() == 1
    fw = Firmware.get(Firmware.board_id == "BUILT_TEST_BOARD")
    assert fw.source == "mpbuild"
    assert fw.custom is True
    assert fw.port == "stm32"


def test_import_firmware_to_database_upsert(tmp_path, db_fx):
    """Re-importing the same firmware file should upsert (no duplicate)."""
    from mpflash.build import import_firmware_to_database

    fw_file = tmp_path / "firmware.bin"
    fw_file.write_bytes(b"\x00" * 16)

    import_firmware_to_database([fw_file], "BUILT_UPSERT_BOARD", "v9.99.0", port="rp2")
    import_firmware_to_database([fw_file], "BUILT_UPSERT_BOARD", "v9.99.0", port="rp2")

    assert Firmware.select().where(Firmware.board_id == "BUILT_UPSERT_BOARD").count() == 1
    assert Board.select().where(Board.board_id == "BUILT_UPSERT_BOARD").count() == 1


def test_import_firmware_to_database_empty_list(db_fx):
    """Empty file list short-circuits to 0 without DB writes."""
    from mpflash.build import import_firmware_to_database

    assert import_firmware_to_database([], "any", "v0") == 0
