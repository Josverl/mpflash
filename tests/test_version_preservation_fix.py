"""
Test for the version preservation fix in ask_input.py.

This test ensures that command-line provided parameters (like version)
are preserved throughout the interactive flow when ask_missing_params is called.

Regression test for the bug where:
1. User specifies --version v1.26.0 on command line
2. Version gets correctly added to answers dict: {"versions": ["v1.26.0"]}
3. When inquirer.prompt() is called for interactive board selection,
   it replaces the entire answers dict
4. The returned dict only contains interactive responses, losing pre-existing version information
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

        # Mock inquirer.prompt to simulate user selecting a board
        with patch("inquirer.prompt") as mock_prompt:
            # Simulate user selecting ESP32_GENERIC board
            mock_prompt.return_value = {"boards": ["ESP32_GENERIC"]}

            # Mock the port/board selection functions to return questions
            with patch("mpflash.ask_input.ask_port_board") as mock_ask_port_board:
                mock_ask_port_board.return_value = [MagicMock(name="board_question")]

                # Call the function that was fixed
                result = ask_missing_params(params)

                # Verify that inquirer.prompt was called with the original answers
                # that included the version info
                mock_prompt.assert_called_once()
                args, kwargs = mock_prompt.call_args

                # The answers dict passed to inquirer should include version and action
                initial_answers = kwargs.get("answers", {})
                assert "versions" in initial_answers, "Version should be preserved in initial answers"
                assert initial_answers["versions"] == ["v1.26.0"], "Version value should be preserved"
                assert initial_answers["action"] == "flash", "Action should be set"

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

        # Mock inquirer.prompt to return None (user cancelled)
        with patch("inquirer.prompt") as mock_prompt:
            mock_prompt.return_value = None  # User cancelled

            with patch("mpflash.ask_input.ask_port_board") as mock_ask_port_board:
                mock_ask_port_board.return_value = [MagicMock(name="board_question")]

                result = ask_missing_params(params)

                # Should return empty list when user cancels
                assert result == [], "Should return empty list when user cancels"


def test_ask_missing_params_no_questions_needed():
    """Test that the function works correctly when no interactive questions are needed."""

    # All parameters are specified, no "?" values
    params = FlashParams(versions=["v1.26.0"], boards=["ESP32_GENERIC"], serial=["COM3"], erase=True, bootloader=BootloaderMethod.AUTO)

    with patch("mpflash.ask_input.config") as mock_config:
        mock_config.interactive = True

        # inquirer.prompt should not be called
        with patch("inquirer.prompt") as mock_prompt:
            result = ask_missing_params(params)

            # inquirer.prompt should not be called since no questions needed
            mock_prompt.assert_not_called()

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

        with patch("inquirer.prompt") as mock_prompt:
            # Mock user selecting additional boards
            mock_prompt.return_value = {"boards": ["ESP32_GENERIC", "RPI_PICO"]}

            with patch("mpflash.ask_input.ask_port_board") as mock_ask_port_board:
                mock_ask_port_board.return_value = [MagicMock(name="board_question")]

                result = ask_missing_params(params)

                # All original values should be preserved
                assert set(result.versions) == {"v1.26.0", "v1.25.0"}, "Multiple versions should be preserved"
                assert result.serial == ["COM3"], "Serial port should be preserved"

                # New interactive selections should be included
                assert set(result.boards) == {"ESP32_GENERIC", "RPI_PICO"}, "Interactive board selection should be included"
