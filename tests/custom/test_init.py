import shutil
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from pytest_mock import MockerFixture

from mpflash.custom import add_firmware, copy_firmware
from mpflash.db.models import Firmware
from mpflash.errors import MPFlashError

pytestmark = [pytest.mark.mpflash]


@pytest.fixture
def mock_config():
    """Mock config with temporary firmware folder."""
    with patch("mpflash.custom.config") as mock_cfg:
        mock_cfg.firmware_folder = Path("/tmp/firmware")
        yield mock_cfg


@pytest.fixture
def sample_fw_info():
    """Sample firmware info dictionary."""
    return {
        "board_id": "esp32_generic",
        "version": "v1.21.0",
        "port": "esp32",
        "firmware_file": "esp32/firmware_test.bin",
        "source": "local",
        "description": "Test firmware",
    }


@pytest.fixture
def temp_source_file(tmp_path):
    """Create a temporary source firmware file."""
    source_file = tmp_path / "source_firmware.bin"
    source_file.write_bytes(b"fake firmware content")
    return source_file


@pytest.fixture
def mock_session():
    """Mock database session."""
    with patch("mpflash.custom.Session") as mock_session_cls:
        session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = session
        yield session


class TestAddFirmware:
    """Test cases for add_firmware function."""

    def test_add_firmware_success(
        self,
        temp_source_file,
        sample_fw_info,
        mock_config,
        mock_session,
        mocker: MockerFixture,
    ):
        """Test successful firmware addition."""
        # Mock copy_firmware to return True
        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock query chain to return no existing firmware
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.filter.return_value.first.return_value = None
        query_mock.filter.return_value = filter_mock
        mock_session.query.return_value = query_mock

        result = add_firmware(temp_source_file, sample_fw_info)

        assert result is True
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_add_firmware_source_not_exists(self, sample_fw_info, mock_config):
        """Test add_firmware with non-existent source file."""
        non_existent_path = Path("/non/existent/file.bin")

        result = add_firmware(non_existent_path, sample_fw_info)

        assert result is False

    def test_add_firmware_missing_board_id(self, temp_source_file, mock_config, mock_session):
        """Test add_firmware with missing board_id."""
        fw_info = {
            "version": "v1.21.0",
            "port": "esp32",
            "firmware_file": "esp32/firmware_test.bin",
        }

        result = add_firmware(temp_source_file, fw_info)

        assert result is False

    def test_add_firmware_copy_fails(
        self,
        temp_source_file,
        sample_fw_info,
        mock_config,
        mock_session,
        mocker: MockerFixture,
    ):
        """Test add_firmware when copy_firmware fails."""
        mocker.patch("mpflash.custom.copy_firmware", return_value=False)

        result = add_firmware(temp_source_file, sample_fw_info)

        assert result is False

    def test_add_firmware_existing_without_force(
        self,
        temp_source_file,
        sample_fw_info,
        mock_config,
        mock_session,
        mocker: MockerFixture,
    ):
        """Test add_firmware with existing firmware and force=False."""
        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock existing firmware
        existing_fw = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.filter.return_value.first.return_value = existing_fw
        query_mock.filter.return_value = filter_mock
        mock_session.query.return_value = query_mock

        result = add_firmware(temp_source_file, sample_fw_info, force=False)

        assert result is False
        mock_session.add.assert_not_called()

    def test_add_firmware_existing_with_force(
        self,
        temp_source_file,
        sample_fw_info,
        mock_config,
        mock_session,
        mocker: MockerFixture,
    ):
        """Test add_firmware with existing firmware and force=True."""
        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock existing firmware
        existing_fw = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.filter.return_value.first.return_value = existing_fw
        query_mock.filter.return_value = filter_mock
        mock_session.query.return_value = query_mock

        result = add_firmware(temp_source_file, sample_fw_info, force=True)

        assert result is True
        # Should update existing firmware, not add new one
        mock_session.add.assert_not_called()
        mock_session.commit.assert_called_once()

    def test_add_firmware_custom_flag(
        self,
        temp_source_file,
        sample_fw_info,
        mock_config,
        mock_session,
        mocker: MockerFixture,
    ):
        """Test add_firmware with custom=True."""
        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock query chain to return no existing firmware
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.filter.return_value.first.return_value = None
        query_mock.filter.return_value = filter_mock
        mock_session.query.return_value = query_mock

        result = add_firmware(temp_source_file, sample_fw_info, custom=True)

        assert result is True
        # Verify that the firmware was marked as custom
        added_fw = mock_session.add.call_args[0][0]
        assert added_fw.custom is True

    def test_add_firmware_database_error(self, temp_source_file, sample_fw_info, mock_config, mocker: MockerFixture):
        """Test add_firmware with database error."""
        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock database error
        with patch("mpflash.custom.Session") as mock_session_cls:
            mock_session_cls.side_effect = sqlite3.DatabaseError("DB Error")

            with pytest.raises(MPFlashError, match="Failed to add firmware"):
                add_firmware(temp_source_file, sample_fw_info)

    @pytest.mark.parametrize("custom_value", [True, False])
    def test_add_firmware_custom_query_logic(
        self,
        temp_source_file,
        sample_fw_info,
        mock_config,
        mock_session,
        custom_value,
        mocker: MockerFixture,
    ):
        """Test different query logic for custom vs non-custom firmware."""
        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock query chain to return no existing firmware
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.filter.return_value.first.return_value = None
        query_mock.filter.return_value = filter_mock
        mock_session.query.return_value = query_mock

        result = add_firmware(temp_source_file, sample_fw_info, custom=custom_value)

        assert result is True
        # Verify correct query filters were applied
        mock_session.query.assert_called_with(Firmware)

    def test_add_firmware_expanduser_path(self, sample_fw_info, mock_config, mock_session, mocker: MockerFixture, tmp_path):
        """Test add_firmware with path containing ~ (user home)."""
        # Create a source file in tmp_path
        source_file = tmp_path / "firmware.bin"
        source_file.write_bytes(b"test firmware")

        # Mock expanduser to return our temp file
        mock_expanduser = mocker.patch.object(Path, "expanduser")
        mock_expanduser.return_value = source_file.absolute()

        mocker.patch("mpflash.custom.copy_firmware", return_value=True)

        # Mock query chain to return no existing firmware
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.filter.return_value.first.return_value = None
        query_mock.filter.return_value = filter_mock
        mock_session.query.return_value = query_mock

        # Use a path with ~ to trigger expanduser
        home_path = Path("~/firmware.bin")
        result = add_firmware(home_path, sample_fw_info)

        assert result is True
        mock_expanduser.assert_called_once()

    def test_add_firmware_invalid_fw_info_type(self, temp_source_file, mock_config):
        """Test add_firmware with invalid firmware info that can't create Firmware object."""
        # This should raise an exception during Firmware(**fw_info)
        invalid_fw_info = {
            "board_id": "test_board",
            "invalid_field": "invalid_value",  # This will cause TypeError
        }

        # This should raise a TypeError due to invalid field
        with pytest.raises(TypeError, match="invalid keyword argument"):
            add_firmware(temp_source_file, invalid_fw_info)


class TestCopyFirmware:
    """Test cases for copy_firmware function."""

    def test_copy_firmware_success(self, tmp_path):
        """Test successful firmware copy."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"test firmware")

        target = tmp_path / "target" / "firmware.bin"

        result = copy_firmware(source, target)

        assert result is True
        assert target.exists()
        assert target.read_bytes() == b"test firmware"

    def test_copy_firmware_source_not_exists(self, tmp_path):
        """Test copy_firmware with non-existent source."""
        source = tmp_path / "non_existent.bin"
        target = tmp_path / "target.bin"

        result = copy_firmware(source, target)

        assert result is False
        assert not target.exists()

    def test_copy_firmware_target_exists_no_force(self, tmp_path):
        """Test copy_firmware when target exists and force=False."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"new content")

        target = tmp_path / "target.bin"
        target.write_bytes(b"old content")

        result = copy_firmware(source, target, force=False)

        assert result is False
        assert target.read_bytes() == b"old content"

    def test_copy_firmware_target_exists_with_force(self, tmp_path):
        """Test copy_firmware when target exists and force=True."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"new content")

        target = tmp_path / "target.bin"
        target.write_bytes(b"old content")

        result = copy_firmware(source, target, force=True)

        assert result is True
        assert target.read_bytes() == b"new content"

    def test_copy_firmware_creates_parent_dirs(self, tmp_path):
        """Test copy_firmware creates parent directories."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"test content")

        target = tmp_path / "deep" / "nested" / "path" / "firmware.bin"

        result = copy_firmware(source, target)

        assert result is True
        assert target.exists()
        assert target.parent.exists()

    def test_copy_firmware_non_path_source(self, tmp_path):
        """Test copy_firmware with non-Path source (edge case)."""
        # Test with string that's not a valid Path or URL
        source = "invalid_source"
        target = tmp_path / "target.bin"

        # This should return None for non-Path, non-URL sources
        # Based on the current implementation, it would fall through without return
        result = copy_firmware(source, target)  # type: ignore

        assert result is None

    def test_copy_firmware_large_file(self, tmp_path):
        """Test copy_firmware with larger file."""
        source = tmp_path / "large.bin"
        large_content = b"A" * 10000  # 10KB file
        source.write_bytes(large_content)

        target = tmp_path / "target.bin"

        result = copy_firmware(source, target)

        assert result is True
        assert target.exists()
        assert target.read_bytes() == large_content

    def test_copy_firmware_special_characters_in_path(self, tmp_path):
        """Test copy_firmware with special characters in file paths."""
        source = tmp_path / "firmware with spaces.bin"
        source.write_bytes(b"test content")

        target = tmp_path / "target with spaces & symbols!.bin"

        result = copy_firmware(source, target)

        assert result is True
        assert target.exists()
        assert target.read_bytes() == b"test content"


class TestIntegration:
    """Integration tests for the custom module functions."""

    def test_add_firmware_end_to_end(self, tmp_path, sample_fw_info, mocker: MockerFixture):
        """Test complete add_firmware workflow."""
        # Create source file
        source_file = tmp_path / "firmware.bin"
        source_file.write_bytes(b"real firmware content")

        # Mock config to use tmp_path
        firmware_folder = tmp_path / "firmware"
        with patch("mpflash.custom.config") as mock_config:
            mock_config.firmware_folder = firmware_folder

            # Mock database session
            with patch("mpflash.custom.Session") as mock_session_cls:
                session = MagicMock()
                mock_session_cls.return_value.__enter__.return_value = session

                # Mock query chain to return no existing firmware
                query_mock = MagicMock()
                filter_mock = MagicMock()
                filter_mock.filter.return_value.first.return_value = None
                query_mock.filter.return_value = filter_mock
                session.query.return_value = query_mock

                result = add_firmware(source_file, sample_fw_info)

                assert result is True
                # Verify file was actually copied
                expected_path = firmware_folder / sample_fw_info["firmware_file"]
                assert expected_path.exists()
                assert expected_path.read_bytes() == b"real firmware content"
