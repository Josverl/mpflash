"""Tests for mpflash.cli_main module."""

import os
from unittest.mock import Mock, patch

import click.exceptions as click_exceptions
import pytest

from mpflash.cli_main import mpflash
from mpflash.errors import MPFlashError


class TestMpflash:
    """Test cases for mpflash main function."""

    def test_mpflash_normal_execution(self, mocker):
        """Test normal execution of mpflash."""
        mock_migrate = mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.return_value = 0
        mock_exit = mocker.patch("builtins.exit")

        mpflash()

        mock_migrate.assert_called_once_with(boards=True, firmwares=True)
        assert mock_cli.add_command.call_count == 4  # Four commands added
        mock_cli.assert_called_once_with(standalone_mode=True)

    def test_mpflash_migrate_database_called(self, mocker):
        """Test that database migration is called correctly."""
        mock_migrate = mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.return_value = 0
        mocker.patch("builtins.exit")

        mpflash()

        mock_migrate.assert_called_once_with(boards=True, firmwares=True)

    def test_mpflash_commands_added(self, mocker):
        """Test that all CLI commands are added."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.return_value = 0
        mocker.patch("builtins.exit")

        mpflash()

        # Check that add_command was called 4 times (for 4 commands)
        assert mock_cli.add_command.call_count == 4

        # Check that the right commands were added
        added_commands = [call[0][0] for call in mock_cli.add_command.call_args_list]
        from mpflash.cli_main import cli_add_custom, cli_download, cli_flash_board, cli_list_mcus

        expected_commands = [cli_list_mcus, cli_download, cli_flash_board, cli_add_custom]

        for expected_cmd in expected_commands:
            assert expected_cmd in added_commands

    def test_mpflash_attribute_error(self, mocker):
        """Test handling of AttributeError exception."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.side_effect = AttributeError("Test attribute error")
        mock_log = mocker.patch("mpflash.cli_main.log")
        mock_exit = mocker.patch("builtins.exit")

        mpflash()

        mock_log.error.assert_called_once_with("Error: Test attribute error")
        mock_exit.assert_called_once_with(-1)

    def test_mpflash_click_exception(self, mocker):
        """Test handling of ClickException."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.side_effect = click_exceptions.ClickException("Test click error")
        mock_log = mocker.patch("mpflash.cli_main.log")
        mock_exit = mocker.patch("builtins.exit")

        mpflash()

        mock_log.error.assert_called_once_with("Error: Test click error")
        mock_exit.assert_called_once_with(-2)

    def test_mpflash_abort_exception(self, mocker):
        """Test handling of Abort exception (Ctrl-C)."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.side_effect = click_exceptions.Abort()
        mock_exit = mocker.patch("builtins.exit")

        mpflash()

        mock_exit.assert_called_once_with(-3)

    def test_mpflash_mpflash_error(self, mocker):
        """Test handling of MPFlashError exception."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.side_effect = MPFlashError("Test MPFlash error")
        mock_log = mocker.patch("mpflash.cli_main.log")
        mock_exit = mocker.patch("builtins.exit")

        mpflash()

        mock_log.error.assert_called_once_with("MPFlashError: Test MPFlash error")
        mock_exit.assert_called_once_with(-4)

    def test_mpflash_successful_exit(self, mocker):
        """Test successful execution with exit code."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.return_value = 0
        mock_exit = mocker.patch("builtins.exit")

        mpflash()

        mock_exit.assert_called_once_with(0)

    def test_mpflash_standalone_mode_true(self, mocker):
        """Test that CLI is called with standalone_mode=True in normal cases."""
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.return_value = 0
        mocker.patch("builtins.exit")

        mpflash()

        mock_cli.assert_called_once_with(standalone_mode=True)

    @pytest.mark.skipif(True, reason="Dev machine specific test")
    def test_mpflash_dev_machine_mode(self, mocker):
        """Test dev machine specific behavior (disabled by default)."""
        # This test is for the conditional dev machine code
        # which is currently disabled with `if False`
        mocker.patch("mpflash.cli_main.migrate_database")
        mock_cli = mocker.patch("mpflash.cli_main.cli")
        mock_cli.add_command = Mock()
        mock_cli.return_value = 0

        # Mock environment variable
        mocker.patch.dict(os.environ, {"COMPUTERNAME": "JOSVERL-DEV"})

        # This would test the dev machine path if it were enabled
        # Currently the condition is `if False` so it won't execute
        mpflash()

        # In normal execution, standalone_mode=True is used
        mock_cli.assert_called_with(standalone_mode=True)

    def test_mpflash_integration_commands_import(self):
        """Test that all command imports work correctly."""
        # Test that all imports are available
        from mpflash.cli_main import cli_add_custom, cli_download, cli_flash_board, cli_list_mcus

        # Basic assertion that imports succeeded
        assert cli_add_custom is not None
        assert cli_download is not None
        assert cli_flash_board is not None
        assert cli_list_mcus is not None
