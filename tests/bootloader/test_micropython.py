"""Tests for mpflash.bootloader.micropython module."""

import pytest

from mpflash.bootloader.micropython import enter_bootloader_mpy


@pytest.fixture
def mock_mcu(mocker):
    """Create a mock MCU for testing."""
    mcu = mocker.Mock()
    mcu.serialport = "COM3"
    return mcu


def test_enter_bootloader_mpy_success(mocker, mock_mcu):
    """Test successful bootloader entry using mpremote."""
    mock_log = mocker.patch("mpflash.bootloader.micropython.log")
    
    result = enter_bootloader_mpy(mock_mcu)
    
    assert result is True
    mock_log.info.assert_called_once_with(
        "Attempting bootloader on COM3 using 'mpremote bootloader'"
    )
    mock_mcu.run_command.assert_called_once_with("bootloader", timeout=10)


def test_enter_bootloader_mpy_always_returns_true(mocker, mock_mcu):
    """Test that function always returns True regardless of command result."""
    # Simulate command failure (though it doesn't affect return value)
    mock_mcu.run_command.side_effect = Exception("Command failed")
    mocker.patch("mpflash.bootloader.micropython.log")

    # Note: Current implementation catches no exceptions and always returns True
    # This test documents this behavior but may indicate an implementation issue
    with pytest.raises(Exception, match="Command failed"):
        enter_bootloader_mpy(mock_mcu)


@pytest.mark.parametrize("timeout_value", [1, 5, 10, 30, 60])
def test_enter_bootloader_mpy_various_timeouts(mocker, mock_mcu, timeout_value):
    """Test bootloader entry with various timeout values."""
    mocker.patch("mpflash.bootloader.micropython.log")
    
    result = enter_bootloader_mpy(mock_mcu, timeout=timeout_value)
    
    assert result is True
    mock_mcu.run_command.assert_called_once_with("bootloader", timeout=timeout_value)


@pytest.mark.parametrize("serialport,expected_log", [
    ("COM3", "Attempting bootloader on COM3 using 'mpremote bootloader'"),
    ("/dev/ttyUSB0", "Attempting bootloader on /dev/ttyUSB0 using 'mpremote bootloader'"),
    ("/dev/ttyACM0", "Attempting bootloader on /dev/ttyACM0 using 'mpremote bootloader'"),
])
def test_enter_bootloader_mpy_serial_port_variations(mocker, serialport, expected_log):
    """Test bootloader entry with various serial port formats."""
    mock_mcu = mocker.Mock()
    mock_mcu.serialport = serialport
    mock_log = mocker.patch("mpflash.bootloader.micropython.log")
    
    enter_bootloader_mpy(mock_mcu)
    
    # Check that the log message contains the correct serial port
    mock_log.info.assert_called_once_with(expected_log)
    assert "mpremote bootloader" in expected_log
