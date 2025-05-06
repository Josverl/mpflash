import pytest
from mpflash.bootloader.activate import enter_bootloader
from pytest_mock import MockerFixture
from serial import SerialException
from mpflash.errors import MPFlashError
from mpflash.mpremoteboard import MPRemoteBoard
from mpflash.bootloader.touch1200 import enter_bootloader_touch_1200bps

pytestmark = [pytest.mark.mpflash]


@pytest.fixture
def mock_mcu():
    return MPRemoteBoard(serialport="COM3")


def test_enter_bootloader_success(mocker: MockerFixture, mock_mcu):
    mock_serial = mocker.patch("mpflash.bootloader.touch1200.serial.Serial")
    result = enter_bootloader_touch_1200bps(mock_mcu)
    mock_serial.assert_called_once_with("COM3", 1200, dsrdtr=True)
    mock_serial.return_value.close.assert_called_once()
    assert result is True


def test_enter_bootloader_no_serialport():
    mcu = MPRemoteBoard(serialport=None)
    with pytest.raises(MPFlashError, match="No serial port specified"):
        enter_bootloader_touch_1200bps(mcu)


def test_enter_bootloader_serial_exception(mocker: MockerFixture, mock_mcu):
    mocker.patch("mpflash.bootloader.touch1200.serial.Serial", side_effect=SerialException("Serial error"))
    with pytest.raises(MPFlashError, match="pySerial error: Serial error"):
        enter_bootloader_touch_1200bps(mock_mcu)


def test_enter_bootloader_generic_exception(mocker: MockerFixture, mock_mcu):
    mocker.patch("mpflash.bootloader.touch1200.serial.Serial", side_effect=Exception("Generic error"))
    with pytest.raises(MPFlashError, match="Error: Generic error"):
        enter_bootloader_touch_1200bps(mock_mcu)
