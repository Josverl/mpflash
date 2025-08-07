"""Tests for mpflash.bootloader.manual module."""

from unittest.mock import Mock, patch

import pytest

from mpflash.bootloader.manual import MCUHighlighter, enter_bootloader_manual, mcu_theme


class TestMCUHighlighter:
    """Test cases for MCUHighlighter class."""

    def test_highlighter_initialization(self):
        """Test MCUHighlighter initialization."""
        highlighter = MCUHighlighter()

        assert highlighter.base_style == "mcu."
        assert isinstance(highlighter.highlights, list)
        assert len(highlighter.highlights) > 0

    def test_highlighter_contains_expected_patterns(self):
        """Test that highlighter contains expected regex patterns."""
        highlighter = MCUHighlighter()

        # Check for some expected patterns
        patterns = [str(pattern) for pattern in highlighter.highlights]

        # Should contain GPIO pattern
        assert any("GPIO" in pattern for pattern in patterns)
        # Should contain button patterns
        assert any("BOOTSEL" in pattern for pattern in patterns)
        assert any("RESET" in pattern for pattern in patterns)
        # Should contain pad patterns
        assert any("GND" in pattern for pattern in patterns)


class TestMcuTheme:
    """Test cases for mcu_theme."""

    def test_theme_structure(self):
        """Test that mcu_theme has expected structure."""
        assert "mcu.bold" in mcu_theme.styles
        assert "mcu.button" in mcu_theme.styles
        assert "mcu.pad" in mcu_theme.styles
        assert "mcu.cable" in mcu_theme.styles

    # def test_theme_colors(self):
    #     """Test that theme colors are defined."""
    #     assert mcu_theme.styles["mcu.bold"] == "orange3"
    #     assert mcu_theme.styles["mcu.button"] == "bold green"
    #     assert mcu_theme.styles["mcu.pad"] == "dodger_blue2"
    #     assert mcu_theme.styles["mcu.cable"] == "dodger_blue2"


class TestEnterBootloaderManual:
    """Test cases for enter_bootloader_manual function."""

    def test_enter_bootloader_manual_rp2_confirm_yes(self, mocker):
        """Test bootloader entry for RP2 with user confirmation."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"
        mock_mcu.board = "pico"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = True
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        result = enter_bootloader_manual(mock_mcu)

        assert result is True
        mock_console.print.assert_called_once()
        mock_confirm.ask.assert_called_once()

    def test_enter_bootloader_manual_rp2_confirm_no(self, mocker):
        """Test bootloader entry for RP2 with user rejection."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"
        mock_mcu.board = "pico"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = False
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        result = enter_bootloader_manual(mock_mcu)

        assert result is False
        mock_console.print.assert_called_once()
        mock_confirm.ask.assert_called_once()

    def test_enter_bootloader_manual_samd(self, mocker):
        """Test bootloader entry for SAMD boards."""
        mock_mcu = Mock()
        mock_mcu.port = "samd"
        mock_mcu.board = "seeed_xiao"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = True
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        result = enter_bootloader_manual(mock_mcu)

        assert result is True
        mock_console.print.assert_called_once()
        # TODO: Check that the message contains SAMD-specific instructions
        # call_args = mock_console.print.call_args[0][0]
        # assert "RESET button twice" in str(call_args)

    def test_enter_bootloader_manual_other_mcu(self, mocker):
        """Test bootloader entry for other MCU types."""
        mock_mcu = Mock()
        mock_mcu.port = "stm32"
        mock_mcu.board = "nucleo_f446re"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = True
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        result = enter_bootloader_manual(mock_mcu)

        assert result is True
        mock_console.print.assert_called_once()
        # TODO: Check that the message contains generic RESET instructions
        # call_args = mock_console.print.call_args[0][0]
        # assert "Pressing the RESET button" in str(call_args)

    def test_enter_bootloader_manual_with_abort(self, mocker):
        """Test bootloader entry when user aborts."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"
        mock_mcu.board = "pico"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.side_effect = Exception("Aborted")  # Simulate Abort exception
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        # Should handle the exception gracefully
        with pytest.raises(Exception):
            enter_bootloader_manual(mock_mcu)

    def test_enter_bootloader_manual_timeout_parameter(self, mocker):
        """Test bootloader entry with custom timeout parameter."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"
        mock_mcu.board = "pico"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = True
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        result = enter_bootloader_manual(mock_mcu, timeout=20)

        assert result is True
        # timeout parameter doesn't affect the current implementation
        # but test verifies it can be passed without error

    @pytest.mark.parametrize(
        "user_input,expected_result",
        [
            ("y", True),
            ("Y", True),
            (True, True),
            ("n", False),
            ("N", False),
            (False, False),
        ],
    )
    def test_enter_bootloader_manual_user_inputs(self, mocker, user_input, expected_result):
        """Test various user input responses."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"
        mock_mcu.board = "pico"

        mock_console = Mock()
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = user_input
        mocker.patch("mpflash.bootloader.manual.Console", return_value=mock_console)

        result = enter_bootloader_manual(mock_mcu)

        assert result == expected_result

    def test_enter_bootloader_manual_console_creation(self, mocker):
        """Test that Console is created with correct parameters."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"
        mock_mcu.board = "pico"

        mock_console_class = mocker.patch("mpflash.bootloader.manual.Console")
        mock_console = Mock()
        mock_console_class.return_value = mock_console
        mock_confirm = mocker.patch("mpflash.bootloader.manual.Confirm")
        mock_confirm.ask.return_value = True

        enter_bootloader_manual(mock_mcu)

        # Verify Console was created with highlighter and theme
        mock_console_class.assert_called_once()
        call_kwargs = mock_console_class.call_args[1]
        assert "highlighter" in call_kwargs
        assert "theme" in call_kwargs
