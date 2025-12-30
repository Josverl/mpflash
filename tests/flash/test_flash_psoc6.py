"""Tests for PSoC6 flashing functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess

from mpflash.flash.psoc6 import flash_psoc6, _check_openocd_available, _flash_with_openocd
from mpflash.mpremoteboard import MPRemoteBoard


@pytest.fixture
def mock_mcu():
    """Create a mock MPRemoteBoard for PSoC6."""
    mcu = Mock(spec=MPRemoteBoard)
    mcu.board = "CY8CPROTO-062-4343W"
    mcu.serialport = "/dev/ttyACM0"
    mcu.port = "psoc6"
    return mcu


@pytest.fixture
def mock_firmware_file(tmp_path):
    """Create a mock firmware file."""
    fw_file = tmp_path / "firmware.hex"
    fw_file.write_text("mock firmware content")
    return fw_file


class TestPSoC6Flash:
    """Test PSoC6 flashing functionality."""

    @patch('mpflash.flash.psoc6._check_openocd_available')
    @patch('mpflash.flash.psoc6._flash_with_openocd')
    def test_flash_psoc6_success(self, mock_flash, mock_openocd_check, mock_mcu, mock_firmware_file):
        """Test successful PSoC6 flashing."""
        mock_openocd_check.return_value = True
        mock_flash.return_value = True
        
        result = flash_psoc6(mock_mcu, mock_firmware_file)
        
        assert result == mock_mcu
        mock_openocd_check.assert_called_once()
        mock_flash.assert_called_once_with(mock_mcu, mock_firmware_file, erase=True)

    @patch('mpflash.flash.psoc6._check_openocd_available')
    def test_flash_psoc6_no_openocd(self, mock_openocd_check, mock_mcu, mock_firmware_file):
        """Test PSoC6 flashing when OpenOCD is not available."""
        mock_openocd_check.return_value = False
        
        result = flash_psoc6(mock_mcu, mock_firmware_file)
        
        assert result is None
        mock_openocd_check.assert_called_once()

    def test_flash_psoc6_file_not_found(self, mock_mcu, tmp_path):
        """Test PSoC6 flashing when firmware file doesn't exist."""
        nonexistent_file = tmp_path / "nonexistent.hex"
        
        result = flash_psoc6(mock_mcu, nonexistent_file)
        
        assert result is None

    def test_flash_psoc6_unsupported_file_format(self, mock_mcu, tmp_path):
        """Test PSoC6 flashing with unsupported file format."""
        bad_file = tmp_path / "firmware.txt"
        bad_file.write_text("content")
        
        result = flash_psoc6(mock_mcu, bad_file)
        
        assert result is None

    @pytest.mark.parametrize("file_ext", [".hex", ".elf", ".bin"])
    @patch('mpflash.flash.psoc6._check_openocd_available')
    @patch('mpflash.flash.psoc6._flash_with_openocd')
    def test_flash_psoc6_supported_formats(self, mock_flash, mock_openocd_check, 
                                         mock_mcu, tmp_path, file_ext):
        """Test PSoC6 flashing with supported file formats."""
        mock_openocd_check.return_value = True
        mock_flash.return_value = True
        
        fw_file = tmp_path / f"firmware{file_ext}"
        fw_file.write_text("mock content")
        
        result = flash_psoc6(mock_mcu, fw_file)
        
        assert result == mock_mcu


class TestOpenOCDAvailability:
    """Test OpenOCD availability checking."""

    @patch('subprocess.run')
    def test_openocd_available(self, mock_run):
        """Test when OpenOCD is available."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        assert _check_openocd_available() is True
        mock_run.assert_called_once_with(
            ["openocd", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )

    @patch('subprocess.run')
    def test_openocd_not_available(self, mock_run):
        """Test when OpenOCD is not available."""
        mock_run.side_effect = FileNotFoundError()
        
        assert _check_openocd_available() is False

    @patch('subprocess.run')
    def test_openocd_subprocess_error(self, mock_run):
        """Test when OpenOCD command fails."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result
        
        assert _check_openocd_available() is False


class TestOpenOCDFlashing:
    """Test OpenOCD flashing functionality."""

    @patch('subprocess.run')
    def test_flash_with_openocd_hex_success(self, mock_run, mock_mcu, tmp_path):
        """Test successful flashing with .hex file."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Success"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        fw_file = tmp_path / "firmware.hex"
        fw_file.write_text("mock hex content")
        
        result = _flash_with_openocd(mock_mcu, fw_file, erase=True)
        
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "openocd" in args
        assert "-f" in args
        assert "interface/kitprog3.cfg" in args
        assert "target/psoc6.cfg" in args

    @patch('subprocess.run')
    def test_flash_with_openocd_bin_success(self, mock_run, mock_mcu, tmp_path):
        """Test successful flashing with .bin file."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Success"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        fw_file = tmp_path / "firmware.bin"
        fw_file.write_text("mock bin content")
        
        result = _flash_with_openocd(mock_mcu, fw_file, erase=False)
        
        assert result is True
        # Check that the command includes the address for .bin files
        args = mock_run.call_args[0][0]
        assert any("0x10000000" in arg for arg in args)

    @patch('subprocess.run')
    def test_flash_with_openocd_failure(self, mock_run, mock_mcu, tmp_path):
        """Test OpenOCD flashing failure."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error"
        mock_run.return_value = mock_result
        
        fw_file = tmp_path / "firmware.hex"
        fw_file.write_text("mock content")
        
        result = _flash_with_openocd(mock_mcu, fw_file)
        
        assert result is False

    @patch('subprocess.run')
    def test_flash_with_openocd_timeout(self, mock_run, mock_mcu, tmp_path):
        """Test OpenOCD flashing timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("openocd", 60)
        
        fw_file = tmp_path / "firmware.hex"
        fw_file.write_text("mock content")
        
        result = _flash_with_openocd(mock_mcu, fw_file)
        
        assert result is False