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

from unittest.mock import MagicMock, patch

import pytest

from mpflash.ask_input import ask_missing_params
from mpflash.common import BootloaderMethod, FlashParams


def test_ask_missing_params_preserves_command_line_version():
    """Test that command-line version info is preserved during interactive prompting."""

    # Set up a FlashParams object with version specified but board as "?"
    # This simulates: mpflash flash --version v1.26.0 --board ?
    params = FlashParams(
        versions=["v1.26.0"],  # Version specified on command line
        boards=["?"],  # Board needs interactive selection
        serial=["COM3"],  # Port is specified
        erase=True,
        bootloader=BootloaderMethod.AUTO,
    )

    # Mock the config to enable interactive mode
    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        # Mock ask_port_board to simulate user selecting a board
        with patch("mpflash.ask_input.ask_port_board") as mock_ask_port_board:
            mock_ask_port_board.return_value = ("esp32", ["ESP32_GENERIC"])

            result = ask_missing_params(params)

            # Verify that ask_port_board was called with answers preserving version
            mock_ask_port_board.assert_called_once()
            _, kwargs = mock_ask_port_board.call_args
            answers_passed = kwargs.get("answers", {})
            assert "versions" in answers_passed, "Version should be preserved in answers passed to ask_port_board"
            assert answers_passed["versions"] == ["v1.26.0"], "Version value should be preserved"
            assert answers_passed["action"] == "flash", "Action should be set"

            # Verify the final result preserves both the original version
            # and the new board selection
            assert hasattr(result, "versions"), "Result should have versions attribute"
            assert result.versions == ["v1.26.0"], "Original version should be preserved in result"
            assert hasattr(result, "boards"), "Result should have boards attribute"
            assert result.boards == ["ESP32_GENERIC"], "New board selection should be included"


def test_ask_missing_params_handles_user_cancellation():
    """Test that the function handles user cancellation during interactive prompting."""

    params = FlashParams(versions=["v1.26.0"], boards=["?"], serial=["COM3"], erase=True, bootloader=BootloaderMethod.AUTO)

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        # Mock ask_port_board returning (None, None) to simulate cancellation
        with patch("mpflash.ask_input.ask_port_board") as mock_ask_port_board:
            mock_ask_port_board.return_value = (None, None)

            result = ask_missing_params(params)

            # Should return empty list when user cancels
            assert result == [], "Should return empty list when user cancels"


def test_ask_missing_params_no_questions_needed():
    """Test that the function works correctly when no interactive questions are needed."""

    # All parameters are specified, no "?" values
    params = FlashParams(versions=["v1.26.0"], boards=["ESP32_GENERIC"], serial=["COM3"], erase=True, bootloader=BootloaderMethod.AUTO)

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        # None of the ask_* helpers should be called since no questions needed
        with patch("mpflash.ask_input.ask_serialport") as mock_serial, patch("mpflash.ask_input.ask_mp_version") as mock_version, patch("mpflash.ask_input.ask_port_board") as mock_port_board:
            result = ask_missing_params(params)

            mock_serial.assert_not_called()
            mock_version.assert_not_called()
            mock_port_board.assert_not_called()

            # Should return the original params unchanged
            assert result.versions == ["v1.26.0"]
            assert result.boards == ["ESP32_GENERIC"]
            assert result.serial == ["COM3"]


def test_ask_missing_params_merge_preserves_all_pre_existing_values():
    """Test that all pre-existing command-line values are preserved during merge."""

    params = FlashParams(
        versions=["v1.26.0", "v1.25.0"],  # Multiple versions
        boards=["?"],  # Interactive selection needed
        serial=["COM3"],
        erase=False,  # Non-default value
        bootloader=BootloaderMethod.AUTO,
    )

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        with patch("mpflash.ask_input.ask_port_board") as mock_ask_port_board:
            mock_ask_port_board.return_value = ("esp32", ["ESP32_GENERIC", "RPI_PICO"])

            result = ask_missing_params(params)

            # All original values should be preserved
            assert set(result.versions) == {"v1.26.0", "v1.25.0"}, "Multiple versions should be preserved"
            assert result.serial == ["COM3"], "Serial port should be preserved"

            # New interactive selections should be included
            assert set(result.boards) == {"ESP32_GENERIC", "RPI_PICO"}, "Interactive board selection should be included"

