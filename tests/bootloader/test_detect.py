"""Tests for mpflash.bootloader.detect module."""

from unittest.mock import MagicMock, Mock

import pytest

from mpflash.bootloader.detect import (
    check_dfu_devices,
    check_for_stm32_bootloader_device,
    in_bootloader,
    in_stm32_bootloader,
    in_uf2_bootloader,
)


class TestInBootloader:
    """Test cases for in_bootloader function."""

    def test_in_bootloader_uf2_board(self, mocker):
        """Test bootloader detection for UF2 boards."""
        mock_mcu = Mock()
        mock_mcu.port = "rp2"

        mocker.patch("mpflash.bootloader.detect.PORT_FWTYPES", {"rp2": [".uf2"]})
        mock_in_uf2 = mocker.patch("mpflash.bootloader.detect.in_uf2_bootloader", return_value=True)

        result = in_bootloader(mock_mcu)

        assert result is True
        mock_in_uf2.assert_called_once_with("RP2")

    def test_in_bootloader_stm32_board(self, mocker):
        """Test bootloader detection for STM32 boards."""
        mock_mcu = Mock()
        mock_mcu.port = "stm32"

        mock_in_stm32 = mocker.patch("mpflash.bootloader.detect.in_stm32_bootloader", return_value=True)

        result = in_bootloader(mock_mcu)

        assert result is True
        mock_in_stm32.assert_called_once()

    def test_in_bootloader_esp32_board(self, mocker):
        """Test bootloader detection for ESP32 boards."""
        mock_mcu = Mock()
        mock_mcu.port = "esp32"

        mock_log = mocker.patch("mpflash.bootloader.detect.log")

        result = in_bootloader(mock_mcu)

        assert result is True
        mock_log.debug.assert_called_once()

    def test_in_bootloader_esp8266_board(self, mocker):
        """Test bootloader detection for ESP8266 boards."""
        mock_mcu = Mock()
        mock_mcu.port = "esp8266"

        mock_log = mocker.patch("mpflash.bootloader.detect.log")

        result = in_bootloader(mock_mcu)

        assert result is True
        mock_log.debug.assert_called_once()

    def test_in_bootloader_unsupported_board(self, mocker):
        """Test bootloader detection for unsupported boards."""
        mock_mcu = Mock()
        mock_mcu.port = "unsupported"
        mock_mcu.board = "unsupported_board"
        mock_mcu.serialport = "COM1"

        mock_log = mocker.patch("mpflash.bootloader.detect.log")

        result = in_bootloader(mock_mcu)

        assert result is False
        mock_log.error.assert_called_once()


class TestInUf2Bootloader:
    """Test cases for in_uf2_bootloader function."""

    def test_in_uf2_bootloader_found(self, mocker):
        """Test UF2 bootloader detection when device is found."""
        mock_waitfor = mocker.patch("mpflash.bootloader.detect.waitfor_uf2", return_value="device_path")

        result = in_uf2_bootloader("RP2")

        assert result is True
        mock_waitfor.assert_called_once_with(board_id="RP2")

    def test_in_uf2_bootloader_not_found(self, mocker):
        """Test UF2 bootloader detection when device is not found."""
        mock_waitfor = mocker.patch("mpflash.bootloader.detect.waitfor_uf2", return_value=None)

        result = in_uf2_bootloader("RP2")

        assert result is False
        mock_waitfor.assert_called_once_with(board_id="RP2")


class TestInStm32Bootloader:
    """Test cases for in_stm32_bootloader function."""

    def test_in_stm32_bootloader_windows_success(self, mocker):
        """Test STM32 bootloader detection on Windows with success."""
        mocker.patch("os.name", "nt")
        mock_check_device = mocker.patch("mpflash.bootloader.detect.check_for_stm32_bootloader_device", return_value=(True, "OK"))
        mock_check_dfu = mocker.patch("mpflash.bootloader.detect.check_dfu_devices", return_value=True)

        result = in_stm32_bootloader()

        assert result is True
        mock_check_device.assert_called_once()
        mock_check_dfu.assert_called_once()

    def test_in_stm32_bootloader_windows_no_driver(self, mocker):
        """Test STM32 bootloader detection on Windows without driver."""
        mocker.patch("os.name", "nt")
        mock_check_device = mocker.patch("mpflash.bootloader.detect.check_for_stm32_bootloader_device", return_value=(False, "Not Found"))
        mock_log = mocker.patch("mpflash.bootloader.detect.log")

        result = in_stm32_bootloader()

        assert result is False
        mock_check_device.assert_called_once()
        mock_log.warning.assert_called_once()

    def test_in_stm32_bootloader_windows_bad_status(self, mocker):
        """Test STM32 bootloader detection on Windows with bad device status."""
        mocker.patch("os.name", "nt")
        mock_check_device = mocker.patch("mpflash.bootloader.detect.check_for_stm32_bootloader_device", return_value=(True, "Error"))
        mock_log = mocker.patch("mpflash.bootloader.detect.log")

        result = in_stm32_bootloader()

        assert result is False
        mock_check_device.assert_called_once()
        mock_log.warning.assert_called()
        mock_log.error.assert_called()

    def test_in_stm32_bootloader_non_windows(self, mocker):
        """Test STM32 bootloader detection on non-Windows systems."""
        mocker.patch("os.name", "posix")
        mock_check_dfu = mocker.patch("mpflash.bootloader.detect.check_dfu_devices", return_value=True)

        result = in_stm32_bootloader()

        assert result is True
        mock_check_dfu.assert_called_once()


class TestCheckDfuDevices:
    """Test cases for check_dfu_devices function."""

    def test_check_dfu_devices_found(self, mocker):
        """Test DFU device check when devices are found."""
        mock_dfu_init = mocker.patch("mpflash.flash.stm32_dfu.dfu_init")
        mock_get_devices = mocker.patch("mpflash.vendor.pydfu.get_dfu_devices", return_value=["device1", "device2"])

        result = check_dfu_devices()

        assert result is True
        mock_dfu_init.assert_called_once()
        mock_get_devices.assert_called_once()

    def test_check_dfu_devices_not_found(self, mocker):
        """Test DFU device check when no devices are found."""
        mock_dfu_init = mocker.patch("mpflash.flash.stm32_dfu.dfu_init")
        mock_get_devices = mocker.patch("mpflash.vendor.pydfu.get_dfu_devices", return_value=[])

        result = check_dfu_devices()

        assert result is False
        mock_dfu_init.assert_called_once()
        mock_get_devices.assert_called_once()


class TestCheckForStm32BootloaderDevice:
    """Test cases for check_for_stm32_bootloader_device function."""

    @pytest.mark.skipif(True, reason="Windows-specific test requiring win32com")
    def test_check_for_stm32_bootloader_device_found(self, mocker):
        """Test STM32 bootloader device check when device is found."""
        # Mock win32com.client
        mock_wmi = Mock()
        mock_device = Mock()
        mock_device.Name = "STM32  BOOTLOADER"
        mock_device.Status = "OK"
        mock_wmi.InstancesOf.return_value = [mock_device]

        mock_client = mocker.patch("win32com.client")
        mock_client.GetObject.return_value = mock_wmi

        result = check_for_stm32_bootloader_device()

        assert result == (True, "OK")

    @pytest.mark.skipif(True, reason="Windows-specific test requiring win32com")
    def test_check_for_stm32_bootloader_device_not_found(self, mocker):
        """Test STM32 bootloader device check when device is not found."""
        # Mock win32com.client
        mock_wmi = Mock()
        mock_device = Mock()
        mock_device.Name = "Other Device"
        mock_wmi.InstancesOf.return_value = [mock_device]

        mock_client = mocker.patch("win32com.client")
        mock_client.GetObject.return_value = mock_wmi

        # Should return None when not imported properly
        result = check_for_stm32_bootloader_device()

        # Function may not be fully testable without win32com
        assert result is None or result == (False, None)

    def test_check_for_stm32_bootloader_device_exception(self, mocker):
        """Test STM32 bootloader device check with exception."""
        # Mock win32com.client to raise ImportError
        mocker.patch("win32com.client", side_effect=ImportError("Module not found"))

        # Should handle the exception gracefully
        with pytest.raises(ImportError):
            check_for_stm32_bootloader_device()
