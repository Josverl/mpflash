from pathlib import Path
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from mpflash.custom.naming import custom_fw_from_path, extract_commit_count, port_and_boardid_from_path


class TestPortAndBoardidFromPath:
    """Test port_and_boardid_from_path function."""

    @pytest.mark.parametrize(
        "path,expected_port,expected_board",
        [
            # Build directory patterns
            ("/micropython/ports/esp32/build-GENERIC/firmware.bin", "esp32", "GENERIC"),
            ("/micropython/ports/esp32/build-GENERIC_S3/firmware.bin", "esp32", "GENERIC_S3"),
            ("/micropython/ports/esp32/build-GENERIC_S3-SPIRAM_OCT/firmware.bin", "esp32", "GENERIC_S3"),
            ("/micropython/ports/rp2/build-PICO/firmware.uf2", "rp2", "PICO"),
            ("C:\\micropython\\ports\\esp32\\build-GENERIC\\firmware.bin", "esp32", "GENERIC"),
            # Port-only patterns
            ("/micropython/ports/esp32/firmware.bin", "esp32", None),
            ("/micropython/ports/rp2/firmware.uf2", "rp2", None),
            ("C:\\micropython\\ports\\esp32\\firmware.bin", "esp32", None),
            # No match patterns
            ("/some/other/path/firmware.bin", None, None),
            ("/micropython/firmware.bin", None, None),
            ("", None, None),
            # Filename-based fallback (port name embedded in filename)
            ("/home/user/build/lvgl_micropy_ESP32_GENERIC-SPIRAM-16.bin", "esp32", None),
            ("/tmp/my_custom_RP2_build.uf2", "rp2", None),
        ],
    )
    def test_valid_paths(self, path: str, expected_port: str, expected_board: str):
        """Test extraction with various valid path patterns."""
        port, board_id = port_and_boardid_from_path(Path(path))
        assert port == expected_port
        assert board_id == expected_board


class TestExtractCommitCount:
    """Test extract_commit_count function."""

    @pytest.mark.parametrize(
        "git_describe,expected_count",
        [
            ("v1.26.0-preview-214-ga56a1eec7b", 214),
            ("v1.26.0-214-ga56a1eec7b", 214),
            ("v1.26.0-preview-214-ga56a1eec7b-dirty", 214),
            ("v1.26.0-0-ga56a1eec7b", 0),
            ("v1.26.0-1-ga56a1eec7b", 1),
            ("v1.26.0", 0),  # No commit count
            ("v1.26.0-preview", 0),  # No commit count
            ("invalid-format", 0),  # Invalid format
            ("", 0),  # Empty string
        ],
    )
    def test_commit_count_extraction(self, git_describe: str, expected_count: int):
        """Test commit count extraction from git describe strings."""
        count = extract_commit_count(git_describe)
        assert count == expected_count


class TestCustomFwFromPath:
    """Test custom_fw_from_path function."""

    def test_valid_firmware_path(self, mocker: MockerFixture):
        """Test custom firmware naming with valid path."""
        # Mock the git functions
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = "v1.26.0"
        mock_get_git_describe.return_value = "v1.26.0-preview-214-ga56a1eec7b"
        mock_get_current_branch.return_value = "feature/new-board"

        fw_path = Path("/micropython/ports/esp32/build-GENERIC/firmware.bin")

        result = custom_fw_from_path(fw_path)

        expected = {
            "port": "esp32",
            "board_id": "GENERIC",
            "custom_id": "GENERIC@new-board",
            "version": "v1.26.0",
            "build": 214,
            "custom": True,
            "firmware_file": "esp32/GENERIC@new-board-v1.26.0.214.bin",
            "source": fw_path.expanduser().absolute().as_uri(),
        }

        assert result == expected

    def test_no_build_count(self, mocker: MockerFixture):
        """Test firmware naming when there's no build count."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = "v1.26.0"
        mock_get_git_describe.return_value = "v1.26.0"  # No commit count
        mock_get_current_branch.return_value = "main"

        fw_path = Path("/micropython/ports/esp32/build-GENERIC/firmware.bin")

        result = custom_fw_from_path(fw_path)

        assert result["build"] == 0
        assert result["firmware_file"] == "esp32/GENERIC@main-v1.26.0.bin"

    def test_no_branch(self, mocker: MockerFixture):
        """Test firmware naming when there's no branch info."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = "v1.26.0"
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = None

        fw_path = Path("/micropython/ports/esp32/build-GENERIC/firmware.bin")

        result = custom_fw_from_path(fw_path)

        assert result["custom_id"] == "GENERIC"
        assert result["firmware_file"] == "esp32/GENERIC-v1.26.0.bin"

    def test_unknown_version(self, mocker: MockerFixture):
        """Test firmware naming when version is unknown."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = None
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = "main"

        fw_path = Path("/micropython/ports/esp32/build-GENERIC/firmware.bin")

        result = custom_fw_from_path(fw_path)

        assert result["version"] == "unknown"
        assert result["firmware_file"] == "esp32/GENERIC@main-unknown.bin"

    def test_nested_branch_name(self, mocker: MockerFixture):
        """Test firmware naming with nested branch names."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = "v1.26.0"
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = "origin/feature/new-board"

        fw_path = Path("/micropython/ports/esp32/build-GENERIC/firmware.bin")

        result = custom_fw_from_path(fw_path)

        assert result["custom_id"] == "GENERIC@new-board"

    def test_wsl_path_handling(self, mocker: MockerFixture):
        """Test that WSL paths are handled correctly."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = "v1.26.0"
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = "main"

        fw_path = Path("//wsl.localhost/Ubuntu/micropython/ports/esp32/build-GENERIC/firmware.bin")

        # Should not raise an exception and should return valid result
        result = custom_fw_from_path(fw_path)

        assert result["port"] == "esp32"
        assert result["board_id"] == "GENERIC"
        assert result["version"] == "v1.26.0"

    def test_invalid_path_uses_filename_fallback(self, mocker: MockerFixture):
        """Test that paths not matching the standard MicroPython build layout
        fall back to using the filename stem as board_id instead of crashing."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = None
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = None

        fw_path = Path("/invalid/path/firmware.bin")

        # Should not raise; falls back to filename stem
        result = custom_fw_from_path(fw_path)
        assert result["board_id"] == "firmware"
        assert result["port"] == ""
        assert result["firmware_file"] == "firmware-unknown.bin"

    def test_filename_with_known_port_fallback(self, mocker: MockerFixture):
        """Test fallback behaviour for the user-reported case where the
        firmware file is in a non-standard location but the filename
        contains a known port name (e.g. ESP32)."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = None
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = None

        fw_path = Path("/home/user/lvgl_micropython/build/lvgl_micropy_ESP32_GENERIC-SPIRAM-16.bin")

        result = custom_fw_from_path(fw_path)

        assert result["port"] == "esp32"
        assert result["board_id"] == "lvgl_micropy_ESP32_GENERIC-SPIRAM-16"
        assert result["version"] == "unknown"
        assert result["firmware_file"] == "esp32/lvgl_micropy_ESP32_GENERIC-SPIRAM-16-unknown.bin"

    def test_different_file_extensions(self, mocker: MockerFixture):
        """Test firmware naming with different file extensions."""
        mock_get_local_tag = mocker.patch("mpflash.custom.naming.git.get_local_tag")
        mock_get_git_describe = mocker.patch("mpflash.custom.naming.git.get_git_describe")
        mock_get_current_branch = mocker.patch("mpflash.custom.naming.git.get_current_branch")

        mock_get_local_tag.return_value = "v1.26.0"
        mock_get_git_describe.return_value = None
        mock_get_current_branch.return_value = "main"

        test_cases = [
            ("/micropython/ports/rp2/build-PICO/firmware.uf2", "rp2/PICO@main-v1.26.0.uf2"),
            ("/micropython/ports/stm32/build-BOARD/firmware.hex", "stm32/BOARD@main-v1.26.0.hex"),
            ("/micropython/ports/esp32/build-GENERIC/firmware.bin", "esp32/GENERIC@main-v1.26.0.bin"),
        ]

        for fw_path_str, expected_firmware_file in test_cases:
            fw_path = Path(fw_path_str)
            result = custom_fw_from_path(fw_path)
            assert result["firmware_file"] == expected_firmware_file
