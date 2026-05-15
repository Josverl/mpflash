"""
Integration tests for CLI functionality with pyOCD support.

Tests the CLI flash command with pyOCD method selection,
parameter parsing, and error handling.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


@pytest.fixture(autouse=True)
def _init_db(db_fx):
    """Initialise the shared peewee database from the test DB.

    cli_flash_board triggers mpboard_id.resolve_board_ids which queries the
    peewee database. Normally cli_main.mpflash() initialises it via
    migrate_database(); when invoking cli_flash_board directly via CliRunner
    we need to initialise it ourselves. Reuses the module-scoped db_fx fixture
    from tests/conftest.py.
    """
    yield
from click.testing import CliRunner

# Import CLI functions and related modules
from mpflash.cli_flash import cli_flash_board
from mpflash.common import FlashMethod, BootloaderMethod
from mpflash.errors import MPFlashError

# Import test fixtures
from tests.fixtures.mock_pyocd_data import MOCK_MCUS, MOCK_PROBES


@pytest.fixture
def _patch_filtered_comports():
    """Patch filtered_comports so detection-branch CLI flows have ports.

    The CLI's auto-detect path calls `mpflash.cli_flash.filtered_comports`
    (imported from `mpflash.common`). Tests in this module mock
    `connected_ports_boards_variants` but the second call to
    `filtered_comports` is what populates the comport list used by
    `_create_worklist_or_fail`. On dev/CI machines no real comports exist,
    which would otherwise raise `click.UsageError`.
    """
    with patch("mpflash.cli_flash.filtered_comports", return_value=["COM1"]) as m:
        yield m


class TestCLIFlashCommandPyOCD:
    """Test CLI flash command with pyOCD integration."""

    @pytest.fixture(autouse=True)
    def _comports(self, _patch_filtered_comports):
        yield _patch_filtered_comports

    def setup_method(self):
        """Set up CLI runner for testing."""
        self.runner = CliRunner()
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    @patch('mpflash.download.jid.ensure_firmware_downloaded_tasks')
    def test_flash_with_pyocd_method(self, mock_download, mock_connected, mock_flash_list):
        """Test flash command with explicit pyOCD method."""
        # Mock board detection
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        
        # Mock successful flashing
        mock_flash_list.return_value = [mock_board]
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable",
            "--probe-id", "066CFF",
            "--auto-install-packs"
        ])
        
        assert result.exit_code == 0
        
        # Verify flash_list was called with correct parameters
        mock_flash_list.assert_called_once()
        call_args = mock_flash_list.call_args
        
        assert call_args[1]["method"] == FlashMethod.PYOCD
        assert call_args[1]["probe_id"] == "066CFF"
        assert call_args[1]["auto_install_packs"] is True
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    @patch('mpflash.download.jid.ensure_firmware_downloaded_tasks')
    def test_flash_with_pyocd_no_auto_install(self, mock_download, mock_connected, mock_flash_list):
        """Test flash command with pyOCD and disabled pack installation."""
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        mock_flash_list.return_value = [mock_board]
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable", 
            "--no-auto-install-packs"
        ])
        
        assert result.exit_code == 0
        
        call_args = mock_flash_list.call_args
        assert call_args[1]["auto_install_packs"] is False
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    def test_flash_with_auto_method_excludes_pyocd(self, mock_connected, mock_flash_list):
        """Test that auto method selection excludes pyOCD by default."""
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        mock_flash_list.return_value = [mock_board]
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "auto",  # Should not use pyOCD
            "--version", "stable"
        ])
        
        assert result.exit_code == 0
        
        call_args = mock_flash_list.call_args
        assert call_args[1]["method"] == FlashMethod.AUTO
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    def test_flash_command_parameter_extraction(self, mock_connected, mock_flash_list):
        """Test that pyOCD parameters are correctly extracted from CLI args."""
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        mock_flash_list.return_value = [mock_board]
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--probe-id", "066CFF505750827567154312",
            "--version", "stable",
            "--erase",
            "--auto-install-packs"
        ])
        
        assert result.exit_code == 0
        
        call_args = mock_flash_list.call_args
        assert call_args[1]["method"] == FlashMethod.PYOCD
        assert call_args[1]["probe_id"] == "066CFF505750827567154312"
        assert call_args[1]["auto_install_packs"] is True
        assert call_args[0][1] is True  # erase parameter
    
    def test_invalid_flash_method(self):
        """Test error handling for invalid flash method."""
        result = self.runner.invoke(cli_flash_board, [
            "--method", "invalid_method",
            "--version", "stable"
        ])
        
        assert result.exit_code != 0
        assert "Invalid value" in result.output
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    def test_flash_failure_handling(self, mock_connected, mock_flash_list):
        """Test handling of flash operation failures."""
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        
        # Mock flash failure
        mock_flash_list.return_value = []  # No boards flashed
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable"
        ])
        
        assert result.exit_code == 1
        # Verify the flash pipeline ran end-to-end and produced the empty result
        # we configured. Asserting on mock calls is more robust than asserting on
        # loguru log output, which is order-dependent across the full suite.
        mock_connected.assert_called_once()
        mock_flash_list.assert_called_once()


class TestCLIParameterValidation:
    """Test CLI parameter validation and error handling."""

    @pytest.fixture(autouse=True)
    def _comports(self, _patch_filtered_comports):
        yield _patch_filtered_comports

    def setup_method(self):
        self.runner = CliRunner()

    def test_probe_id_parameter_validation(self):
        """Test probe ID parameter accepts various formats."""
        with patch("mpflash.flash.flash_tasks") as mock_flash:
            with patch("mpflash.connected.connected_ports_boards_variants") as mock_connected:
                mock_board = MOCK_MCUS["stm32wb55"]
                mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
                mock_flash.return_value = [mock_board]

                # Test short probe ID
                result = self.runner.invoke(cli_flash_board, ["--method", "pyocd", "--probe-id", "066C", "--version", "stable"])

                assert result.exit_code == 0

                # Test full probe ID
                result = self.runner.invoke(
                    cli_flash_board, ["--method", "pyocd", "--probe-id", "066CFF505750827567154312", "--version", "stable"]
                )

                assert result.exit_code == 0

    def test_auto_install_packs_default_true(self):
        """Test that auto-install-packs defaults to True."""
        with patch("mpflash.flash.flash_tasks") as mock_flash:
            with patch("mpflash.connected.connected_ports_boards_variants") as mock_connected:
                mock_board = MOCK_MCUS["stm32wb55"]
                mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
                mock_flash.return_value = [mock_board]

                result = self.runner.invoke(
                    cli_flash_board,
                    [
                        "--method",
                        "pyocd",
                        "--version",
                        "stable",
                        # No explicit --auto-install-packs flag
                    ],
                )

                assert result.exit_code == 0

                call_args = mock_flash.call_args
                assert call_args[1]["auto_install_packs"] is True  # Default value

    def test_multiple_versions_error(self):
        """Test error when multiple versions specified."""
        result = self.runner.invoke(
            cli_flash_board,
            [
                "--version",
                "stable",
                "--version",
                "1.20.0",  # Multiple versions not allowed
                "--method",
                "pyocd",
            ],
        )

        # Should fail during parameter processing
        assert result.exit_code != 0


class TestCLIWorkflowIntegration:
    """Test complete CLI workflows with pyOCD."""

    @pytest.fixture(autouse=True)
    def _comports(self, _patch_filtered_comports):
        yield _patch_filtered_comports

    def setup_method(self):
        self.runner = CliRunner()
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    @patch('mpflash.download.jid.ensure_firmware_downloaded_tasks')
    @patch('mpflash.list.show_mcus')
    def test_complete_pyocd_workflow_success(self, mock_show, mock_download, mock_connected, mock_flash_list):
        """Test complete successful pyOCD flash workflow."""
        # Setup mocks
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        mock_flash_list.return_value = [mock_board]  # Successful flash
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable",
            "--probe-id", "066CFF",
            "--erase",
            "--auto-install-packs"
        ])
        
        assert result.exit_code == 0

        # Verify all steps were called. We assert on mock calls rather than on
        # loguru log output ("Flashed 1 boards"), because log capture is
        # order-dependent across the full suite and unreliable here.
        mock_download.assert_called_once()  # Firmware downloaded
        mock_flash_list.assert_called_once()  # Flash operation
        mock_show.assert_called_once()  # Results displayed
        # show_mcus must receive the flashed boards from flash_tasks
        shown_boards, *_ = mock_show.call_args.args
        assert shown_boards == [mock_board]
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    @patch('mpflash.download.jid.ensure_firmware_downloaded_tasks')
    def test_custom_firmware_pyocd_workflow(self, mock_download, mock_connected, mock_flash_list):
        """Test pyOCD workflow with custom firmware."""
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        mock_flash_list.return_value = [mock_board]
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable",
            "--custom"  # Custom firmware flag
        ])
        
        assert result.exit_code == 0
        
        # Custom firmware should skip download
        mock_download.assert_not_called()
        mock_flash_list.assert_called_once()
    
    @patch('mpflash.connected.connected_ports_boards_variants')
    @patch('mpflash.ask_input.ask_missing_params')
    def test_interactive_parameter_prompting(self, mock_ask, mock_connected):
        """Test interactive parameter prompting with pyOCD method."""
        # No boards detected initially
        mock_connected.return_value = ([], [], [], [])
        
        # Mock user cancellation
        mock_ask.return_value = None  # User cancelled
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable"
        ])
        
        assert result.exit_code == 2  # User cancellation exit code
        mock_ask.assert_called_once()


class TestCLIErrorScenarios:
    """Test CLI error handling scenarios."""
    
    def setup_method(self):
        self.runner = CliRunner()
    
    @patch('mpflash.flash.flash_tasks')
    @patch('mpflash.connected.connected_ports_boards_variants')
    def test_flash_method_error_propagation(self, mock_connected, mock_flash_list):
        """Test that flash method errors are properly propagated."""
        mock_board = MOCK_MCUS["stm32wb55"]
        mock_connected.return_value = (["COM1"], ["NUCLEO_WB55"], [""], [mock_board])
        
        # Mock flash_list raising an exception
        mock_flash_list.side_effect = MPFlashError("pyOCD programming failed")
        
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable"
        ])
        
        assert result.exit_code != 0
        # Exception should be caught and handled gracefully
    
    @patch('mpflash.connected.connected_ports_boards_variants')
    def test_no_boards_detected_workflow(self, mock_connected):
        """Test workflow when no boards are detected."""
        # No boards detected
        mock_connected.return_value = ([], [], [], [])
        
        with patch('mpflash.ask_input.ask_missing_params') as mock_ask:
            # Mock FlashParams with pyOCD method
            mock_params = Mock()
            mock_params.boards = ["NUCLEO_WB55"]
            mock_params.versions = ["stable"]
            mock_params.serial = ["COM1"]
            mock_params.bootloader = BootloaderMethod.MANUAL
            mock_ask.return_value = mock_params
            
            with patch('mpflash.flash.flash_tasks') as mock_flash:
                mock_flash.return_value = []
                
                result = self.runner.invoke(cli_flash_board, [
                    "--method", "pyocd",
                    "--version", "stable"
                ])
                
                assert result.exit_code == 1  # No boards flashed
    
    def test_missing_required_parameters(self):
        """Test behavior with missing required parameters."""
        # No version specified - should use default "stable"
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd"
            # Missing version - should use default
        ])
        
        # Should not fail immediately due to missing version (has default)
        # May fail later due to no boards detected, but that's expected


class TestCLIHelpAndDocumentation:
    """Test CLI help text and documentation for pyOCD options."""
    
    def setup_method(self):
        self.runner = CliRunner()
    
    def test_cli_help_includes_pyocd_options(self):
        """Test that CLI help includes pyOCD-specific options."""
        result = self.runner.invoke(cli_flash_board, ["--help"])
        
        assert result.exit_code == 0
        assert "--method" in result.output
        assert "pyocd" in result.output
        assert "--probe-id" in result.output
        assert "--auto-install-packs" in result.output
    
    def test_method_choice_validation(self):
        """Test that method parameter validates choices correctly."""
        # Valid method
        result = self.runner.invoke(cli_flash_board, [
            "--method", "pyocd",
            "--version", "stable",
            "--help"  # Just show help, don't execute
        ])
        
        assert "pyocd" in result.output
        
        # Should include all valid methods in help
        assert "auto" in result.output
        assert "serial" in result.output


if __name__ == "__main__":
    pytest.main([__file__])