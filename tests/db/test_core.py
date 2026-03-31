import sqlite3
from pathlib import Path

import peewee
import pytest
from mock import MagicMock, PropertyMock, patch
from mpflash.config import MPFlashConfig, config

from mpflash.db.core import (
    Session,
    _init_database,
    _SessionContext,
    _SessionProxy,
    create_database,
    get_schema_version,
    migrate_database,
    migration_001_add_custom_id,
    run_schema_migrations,
    set_schema_version,
)
from mpflash.db.models import Board, Firmware, Metadata, database


def test_session_factory(session_mem, mocker):
    """Test the session context and factory."""
    with Session() as session:
        assert isinstance(session, _SessionProxy)
        # Test execute
        result = session.execute("SELECT 1")
        assert result.fetchone()[0] == 1

        # Test no-op commit
        session.commit()

        # Test mock bind
        bind = session.get_bind()
        assert hasattr(bind, "url")
        assert hasattr(bind.url, "database")

    with Session() as session:
        mock_rollback = mocker.patch.object(session._db, "rollback")
        session.rollback()
        mock_rollback.assert_called_once()


def test_schema_versions(session_mem, mocker):
    """Test get and set schema versions."""
    set_schema_version(1)
    version = get_schema_version()
    assert version == 1


def test_migration_001_add_custom_id(session_fx, mocker):
    """Test the migration 001."""
    migration_001_add_custom_id()


def test_migration_001_mocked(session_mem, mocker):
    """Test the migration 001 branches."""
    mock_execute = mocker.patch("mpflash.db.core.database.execute_sql")

    # Case 1: custom_id not in columns
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(0, "id"), (1, "name")]
    mock_execute.return_value = mock_result

    migration_001_add_custom_id()

    # Check calls
    assert mock_execute.call_count >= 2

    # Case 2: custom_id exists but no index
    mock_execute.reset_mock()
    mock_result_cols = MagicMock()
    mock_result_cols.fetchall.return_value = [(0, "id"), (1, "custom_id")]

    mock_result_idx = MagicMock()
    mock_result_idx.fetchall.return_value = [(0, "idx_other")]

    mock_execute.side_effect = [mock_result_cols, mock_result_idx, MagicMock()]

    migration_001_add_custom_id()
    assert mock_execute.call_count >= 3


def test_run_schema_migrations(session_mem, mocker):
    """Test run_schema_migrations."""
    mocker.patch("mpflash.db.core.get_schema_version", return_value=10)
    mock_migration_001 = mocker.patch("mpflash.db.core.migration_001_add_custom_id")
    run_schema_migrations()
    mock_migration_001.assert_not_called()

    mocker.patch("mpflash.db.core.get_schema_version", return_value=0)
    mock_set = mocker.patch("mpflash.db.core.set_schema_version")
    run_schema_migrations()
    mock_migration_001.assert_called_once()
    mock_set.assert_called_once_with(1)


def test_run_schema_migrations_exception(session_mem, mocker):
    """Test run_schema_migrations raises MPFlashError."""
    mocker.patch("mpflash.db.core.get_schema_version", return_value=0)
    mocker.patch("mpflash.db.core.set_schema_version", side_effect=peewee.PeeweeException("Test error"))

    from mpflash.errors import MPFlashError

    with pytest.raises(MPFlashError):
        run_schema_migrations()


def test_create_database(session_mem, mocker):
    """Test create_database."""
    mock_connect = mocker.patch("mpflash.db.core.database.connect")
    mock_create_tables = mocker.patch("mpflash.db.core.database.create_tables")
    mock_migrations = mocker.patch("mpflash.db.core.run_schema_migrations")
    mocker.patch("mpflash.db.core.database.is_closed", return_value=True)

    create_database()
    mock_connect.assert_called_once()
    mock_create_tables.assert_called_once()
    mock_migrations.assert_called_once()


def test_migrate_database(session_mem, mocker):
    """Test migrate_database."""
    mock_create = mocker.patch("mpflash.db.core.create_database")
    mock_migrations = mocker.patch("mpflash.db.core.run_schema_migrations")
    mock_update = mocker.patch("mpflash.db.loader.update_boards")
    mock_load_jsonl = mocker.patch("mpflash.db.loader.load_jsonl_to_db")

    migrate_database(boards=True, firmwares=False)

    mock_create.assert_called_once()
    mock_migrations.assert_called_once()
    mock_update.assert_called_once()
    mock_load_jsonl.assert_not_called()


def test_migrate_database_jsonl(session_mem, mocker, tmp_path):
    """Test migrate_database with jsonl."""
    mock_create = mocker.patch("mpflash.db.core.create_database")
    mock_migrations = mocker.patch("mpflash.db.core.run_schema_migrations")
    mock_update = mocker.patch("mpflash.db.loader.update_boards")
    mock_load_jsonl = mocker.patch("mpflash.db.loader.load_jsonl_to_db")

    jsonl_file = tmp_path / "firmware.jsonl"
    jsonl_file.write_text("{}")
    mocker.patch.object(MPFlashConfig, "firmware_folder", new_callable=PropertyMock, return_value=tmp_path)

    migrate_database(boards=False, firmwares=True)

    mock_load_jsonl.assert_called_once_with(jsonl_file)
    assert not jsonl_file.exists()
    assert (tmp_path / "firmware.jsonl.bak").exists()


def test_migrate_database_db_error(session_mem, mocker):
    """Test migrate_database handles error."""
    mock_create = mocker.patch("mpflash.db.core.create_database", side_effect=sqlite3.OperationalError("Test error"))

    from mpflash.errors import MPFlashError

    with pytest.raises(MPFlashError):
        migrate_database(boards=False, firmwares=False)


def test_init_database(mocker):
    """Test _init_database coverage TRACE branch."""
    mocker.patch("mpflash.db.core.TRACE", True)
    mock_init = mocker.patch("mpflash.db.core.database.init")
    _init_database(Path("/tmp/test.db"))
    mock_init.assert_called_once_with(str(Path("/tmp/test.db")))
