"""
Test for the version preservation fix in ask_input.py.

This test ensures that command-line provided parameters (like version)
are preserved throughout the interactive flow when ask_missing_params is called.

Regression test for the bug where:
1. User specifies --version v1.26.0 on command line
2. Version gets correctly added to answers dict: {"versions": ["v1.26.0"]}
3. When prompting for interactive board selection the answers should include version
4. The returned result must not lose pre-existing version information
"""

from unittest.mock import patch

import pytest

from mpflash.ask_input import ask_missing_params
from mpflash.common import BootloaderMethod, FlashParams


def test_ask_missing_params_preserves_command_line_version():
    """Test that command-line version info is preserved during interactive prompting."""

    params = FlashParams(
        versions=["v1.26.0"],  # Version specified on command line
        boards=["?"],  # Board needs interactive selection
        serial=["COM3"],  # Port is specified
        erase=True,
        bootloader=BootloaderMethod.AUTO,
    )

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        # Mock ask_port_board_variant to simulate user selecting a board+variant
        with patch("mpflash.ask_input.ask_port_board_variant") as mock_ask_port_board_variant:
            mock_ask_port_board_variant.return_value = ("esp32", ["ESP32_GENERIC"], "SPIRAM")

            result = ask_missing_params(params)

            # Verify that ask_port_board_variant was called with answers preserving version
            mock_ask_port_board_variant.assert_called_once()
            _, kwargs = mock_ask_port_board_variant.call_args
            answers_passed = kwargs.get("answers", {})
            assert "versions" in answers_passed, "Version should be preserved in answers"
            assert answers_passed["versions"] == ["v1.26.0"], "Version value should be preserved"
            assert answers_passed["action"] == "flash", "Action should be set"

            # Verify result preserves original version and includes new board + variant
            assert result.versions == ["v1.26.0"], "Original version should be preserved"
            assert result.boards == ["ESP32_GENERIC"], "Board selection should be included"
            assert result.variant == "SPIRAM", "Variant should be captured"


def test_ask_missing_params_handles_user_cancellation():
    """Test that the function handles user cancellation during interactive prompting."""

    params = FlashParams(versions=["v1.26.0"], boards=["?"], serial=["COM3"], erase=True, bootloader=BootloaderMethod.AUTO)

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        # Mock ask_port_board_variant returning (None, None, None) to simulate cancellation
        with patch("mpflash.ask_input.ask_port_board_variant") as mock_ask_port_board_variant:
            mock_ask_port_board_variant.return_value = (None, None, None)

            result = ask_missing_params(params)

            assert result == [], "Should return empty list when user cancels"


def test_ask_missing_params_no_questions_needed():
    """Test that the function works correctly when no interactive questions are needed."""

    params = FlashParams(versions=["v1.26.0"], boards=["ESP32_GENERIC"], serial=["COM3"], erase=True, bootloader=BootloaderMethod.AUTO)

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        with (
            patch("mpflash.ask_input.ask_serialport") as mock_serial,
            patch("mpflash.ask_input.ask_mp_version") as mock_version,
            patch("mpflash.ask_input.ask_port_board_variant") as mock_port_board_variant,
        ):
            result = ask_missing_params(params)

            mock_serial.assert_not_called()
            mock_version.assert_not_called()
            mock_port_board_variant.assert_not_called()

            assert result.versions == ["v1.26.0"]
            assert result.boards == ["ESP32_GENERIC"]
            assert result.serial == ["COM3"]


def test_ask_missing_params_merge_preserves_all_pre_existing_values():
    """Test that all pre-existing command-line values are preserved during merge."""

    params = FlashParams(
        versions=["v1.26.0", "v1.25.0"],
        boards=["?"],
        serial=["COM3"],
        erase=False,
        bootloader=BootloaderMethod.AUTO,
    )

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        with patch("mpflash.ask_input.ask_port_board_variant") as mock_ask_port_board_variant:
            mock_ask_port_board_variant.return_value = ("esp32", ["ESP32_GENERIC", "RPI_PICO"], "")

            result = ask_missing_params(params)

            assert set(result.versions) == {"v1.26.0", "v1.25.0"}, "Multiple versions should be preserved"
            assert result.serial == ["COM3"], "Serial port should be preserved"
            assert set(result.boards) == {"ESP32_GENERIC", "RPI_PICO"}, "Interactive board selection should be included"
            assert result.variant == "", "Empty variant should be preserved"
