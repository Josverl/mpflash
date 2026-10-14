from pathlib import Path
from unittest.mock import MagicMock

import pytest
from esptool import FatalError
from esptool.bin_image import ESP32C5FirmwareImage, ESP32FirmwareImage
from esptool.targets import CHIP_DEFS
from pytest_mock import MockerFixture

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.esp import _chip_params, flash_esp
from mpflash.mpremoteboard import MPRemoteBoard


@pytest.fixture
def mock_mcu():
    mcu = MagicMock(spec=MPRemoteBoard)
    mcu.port = "esp32"
    mcu.board = "ESP32_DEV"
    mcu.serialport = "/dev/ttyUSB0"
    mcu.cpu = "ESP32"
    mcu.version = "v1.0"
    return mcu


@pytest.fixture
def mock_esptool(mocker: MockerFixture, mock_mcu: MagicMock) -> dict[str, MagicMock]:
    """Mock the esptool.cmds functions used by flash_esp."""
    mock_loader = MagicMock()
    mock_loader.change_baud = MagicMock()

    # detect_chip returns a context manager that yields mock_loader
    mock_cm = MagicMock()

    def detected_chip() -> MagicMock:
        chip, _, _ = _chip_params(mock_mcu.cpu)
        mock_loader.CHIP_NAME = CHIP_DEFS[chip].CHIP_NAME
        return mock_loader

    mock_cm.__enter__ = MagicMock(side_effect=detected_chip)
    mock_cm.__exit__ = MagicMock(return_value=False)

    mock_detect = mocker.patch("mpflash.flash.builtins.esp.espcmds.detect_chip", return_value=mock_cm)
    mock_stub = mocker.patch("mpflash.flash.builtins.esp.espcmds.run_stub", return_value=mock_loader)
    mock_erase = mocker.patch("mpflash.flash.builtins.esp.espcmds.erase_flash")
    mock_write = mocker.patch("mpflash.flash.builtins.esp.espcmds.write_flash")
    mock_reset = mocker.patch("mpflash.flash.builtins.esp.espcmds.reset_chip")

    def firmware_image(chip: str, _filename: str) -> MagicMock:
        return MagicMock(spec=ESP32FirmwareImage, chip_id=getattr(CHIP_DEFS[chip], "IMAGE_CHIP_ID", None))

    mock_image = mocker.patch("mpflash.flash.builtins.esp.LoadFirmwareImage", side_effect=firmware_image)
    return {
        "loader": mock_loader,
        "connection": mock_cm,
        "detect": mock_detect,
        "stub": mock_stub,
        "image": mock_image,
        "erase": mock_erase,
        "write": mock_write,
        "reset": mock_reset,
    }


# ---------------------------------------------------------------------------
# _chip_params helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cpu, expected_chip, expected_addr, expected_baud",
    [
        ("ESP32", "esp32", "0x1000", 921_600),
        ("ESP32C2", "esp32c2", "0x0", 921_600),
        ("ESP32S2", "esp32s2", "0x1000", 460_800),
        ("ESP32S3", "esp32s3", "0x0", 921_600),
        ("ESP32C3", "esp32c3", "0x0", 921_600),
        ("ESP32C5", "esp32c5", "0x2000", 921_600),
        ("ESP32-C5", "esp32c5", "0x2000", 921_600),
        ("ESP32C6", "esp32c6", "0x0", 460_800),
        ("ESP32P4", "esp32p4", "0x2000", 921_600),
        ("ESP32-P4", "esp32p4", "0x2000", 921_600),
        ("ESP8266", "esp8266", "0x0", 460_800),
    ],
)
def test_chip_params(cpu, expected_chip, expected_addr, expected_baud):
    chip, addr, baud = _chip_params(cpu)
    assert chip == expected_chip
    assert addr == expected_addr
    assert baud == expected_baud


# ---------------------------------------------------------------------------
# Guard-rail tests (no hardware mocking needed)
# ---------------------------------------------------------------------------


def test_flash_esp_unsupported_mcu(mock_mcu):
    mock_mcu.port = "unsupported"
    assert flash_esp(mock_mcu, Path("/path/to/firmware.bin")) is None


def test_flash_esp_unsupported_board(mock_mcu):
    mock_mcu.board = "ARDUINO_UNO"
    assert flash_esp(mock_mcu, Path("/path/to/firmware.bin")) is None


# ---------------------------------------------------------------------------
# Chip-specific parameter tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "port, cpu, expected_addr, expected_baud",
    [
        ("esp32", "ESP32", "0x1000", 921_600),
        ("esp32", "ESP32C2", "0x0", 921_600),
        ("esp32", "ESP32S2", "0x1000", 460_800),
        ("esp32", "ESP32S3", "0x0", 921_600),
        ("esp32", "ESP32C3", "0x0", 921_600),
        ("esp32", "ESP32C5", "0x2000", 921_600),
        ("esp32", "ESP32-C5", "0x2000", 921_600),
        ("esp32", "ESP32C6", "0x0", 460_800),
        ("esp32", "ESP32P4", "0x2000", 921_600),
        ("esp8266", "ESP8266", "0x0", 460_800),
    ],
)
def test_flash_esp_chips(mock_mcu, mock_esptool, port, cpu, expected_addr, expected_baud):
    """All ESP32 variants and ESP8266 should use compress=True."""
    mock_mcu.port = port
    mock_mcu.cpu = cpu
    fw_path = Path("/path/to/firmware.bin")

    result = flash_esp(mock_mcu, fw_path, erase=False)

    assert result == mock_mcu
    mock_esptool["detect"].assert_called_once_with(port=mock_mcu.serialport)
    mock_esptool["reset"].assert_called_once_with(mock_esptool["loader"])
    mock_esptool["loader"].change_baud.assert_called_once_with(expected_baud)
    mock_esptool["write"].assert_called_once_with(
        mock_esptool["loader"],
        [(int(expected_addr, 16), str(fw_path))],
        flash_mode="keep",
        flash_size="detect",
        erase_all=False,
        compress=True,
    )


# ---------------------------------------------------------------------------
# Erase flag
# ---------------------------------------------------------------------------


def test_flash_esp_erase(mock_mcu, mock_esptool):
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=True)
    assert result == mock_mcu
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_called_once()
    assert mock_esptool["write"].call_args.kwargs["erase_all"] is True
    assert mock_esptool["write"].call_args.kwargs.get("force", False) is False


def test_flash_esp_no_erase(mock_mcu, mock_esptool):
    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)
    assert result == mock_mcu
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_called_once()


# ---------------------------------------------------------------------------
# Compression fallback
# ---------------------------------------------------------------------------


def test_flash_esp_compress_fallback(mock_mcu, mock_esptool):
    """If compressed write raises FatalError, retry with no_compress=True."""
    mock_esptool["write"].side_effect = [FatalError("compressed upload failed"), None]

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)

    assert result == mock_mcu
    assert mock_esptool["write"].call_count == 2
    first_call, second_call = mock_esptool["write"].call_args_list
    assert first_call.kwargs.get("compress") is True
    assert first_call.kwargs.get("force", False) is False
    assert second_call.kwargs.get("no_compress") is True
    assert second_call.kwargs.get("force", False) is False


def test_flash_esp_compress_fallback_also_fails(mock_mcu, mock_esptool):
    """If both compressed and uncompressed writes fail (no retry), return None."""
    mock_esptool["write"].side_effect = [
        FatalError("compressed failed"),
        FatalError("uncompressed also failed"),
    ]

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False, retry_on_error=False)
    assert result is None


# ---------------------------------------------------------------------------
# General exception handling
# ---------------------------------------------------------------------------


def test_flash_esp_exception(mock_mcu, mock_esptool):
    mock_esptool["write"].side_effect = Exception("Flashing error")
    assert flash_esp(mock_mcu, Path("/path/to/firmware.bin")) is None


# ---------------------------------------------------------------------------
# Retry on error
# ---------------------------------------------------------------------------


def test_flash_esp_retry_succeeds(mock_mcu, mock_esptool):
    """First attempt fails; retry with lower baud and different mode succeeds."""
    mock_esptool["write"].side_effect = [Exception("first attempt failed"), None]

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)

    assert result == mock_mcu
    assert mock_esptool["write"].call_count == 2
    # First attempt uses default baud, retry uses 115200
    baud_calls = mock_esptool["loader"].change_baud.call_args_list
    assert baud_calls[0].args[0] == 921_600
    assert baud_calls[1].args[0] == 115_200


def test_flash_esp_retry_uses_retry_flash_mode(mock_mcu, mock_esptool):
    """Retry attempt must use the retry_flash_mode, not the original flash_mode."""
    mock_esptool["write"].side_effect = [Exception("first attempt failed"), None]

    flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False, flash_mode="keep", retry_flash_mode="dio")

    first_call, second_call = mock_esptool["write"].call_args_list
    assert first_call.kwargs["flash_mode"] == "keep"
    assert second_call.kwargs["flash_mode"] == "dio"


def test_flash_esp_retry_custom_baud(mock_mcu, mock_esptool):
    """Retry uses the caller-supplied retry_baud."""
    mock_esptool["write"].side_effect = [Exception("first attempt failed"), None]

    flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False, retry_baud=9_600)

    baud_calls = mock_esptool["loader"].change_baud.call_args_list
    assert baud_calls[1].args[0] == 9_600


def test_flash_esp_retry_also_fails(mock_mcu, mock_esptool):
    """Both attempts fail → return None."""
    mock_esptool["write"].side_effect = Exception("always fails")

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False)

    assert result is None
    assert mock_esptool["write"].call_count == 2


def test_flash_esp_no_retry(mock_mcu, mock_esptool):
    """With retry_on_error=False, a single failure returns None without retry."""
    mock_esptool["write"].side_effect = Exception("Flashing error")

    result = flash_esp(mock_mcu, Path("/path/to/firmware.bin"), erase=False, retry_on_error=False)

    assert result is None
    mock_esptool["write"].assert_called_once()


@pytest.mark.parametrize("erase", [False, True])
def test_wrong_detected_chip_never_erases_or_writes(mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock], erase: bool) -> None:
    mock_mcu.cpu = "ESP32-C5"
    mock_mcu.board = "ESP32_GENERIC_C5"
    mock_esptool["connection"].__enter__.side_effect = None
    mock_esptool["loader"].CHIP_NAME = "ESP32"

    with pytest.raises(MPFlashError, match="ESP32.*ESP32-C5"):
        flash_esp(mock_mcu, Path("/firmware/c5.bin"), erase=erase)

    mock_esptool["detect"].assert_called_once()
    mock_esptool["stub"].assert_not_called()
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_not_called()
    mock_mcu.wait_for_restart.assert_not_called()


@pytest.mark.parametrize("erase", [False, True])
def test_wrong_image_chip_never_erases_or_writes(mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock], erase: bool) -> None:
    mock_esptool["image"].side_effect = None
    mock_esptool["image"].return_value = MagicMock(spec=ESP32FirmwareImage, chip_id=23)

    with pytest.raises(MPFlashError, match="firmware.*ESP32"):
        flash_esp(mock_mcu, Path("/firmware/c5-misnamed.bin"), erase=erase)

    mock_esptool["detect"].assert_not_called()
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_not_called()


def test_invalid_image_never_connects_or_writes(mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock]) -> None:
    mock_esptool["image"].side_effect = FatalError("Invalid image magic")

    with pytest.raises(MPFlashError, match="Invalid.*firmware"):
        flash_esp(mock_mcu, Path("/firmware/invalid.bin"), erase=True)

    mock_esptool["detect"].assert_not_called()
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_not_called()


def test_unknown_cpu_is_not_assumed_to_be_classic_esp32() -> None:
    with pytest.raises(MPFlashError, match="Unknown CPU"):
        _chip_params("not-a-known-esp")


def test_restart_timeout_is_not_reported_as_flash_success(mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock]) -> None:
    mock_mcu.wait_for_restart.return_value = False

    with pytest.raises(MPFlashError, match="did not restart"):
        flash_esp(mock_mcu, Path("/firmware/esp32.bin"), erase=False)

    mock_esptool["write"].assert_called_once()
    mock_mcu.wait_for_restart.assert_called_once()


def test_real_c5_image_is_rejected_for_classic_before_connecting(
    mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock], tmp_path: Path
) -> None:
    from esptool.bin_image import LoadFirmwareImage

    mock_esptool["image"].side_effect = LoadFirmwareImage
    firmware = tmp_path / "ESP32_GENERIC.bin"
    ESP32C5FirmwareImage().save(str(firmware))

    with pytest.raises(MPFlashError, match="chip ID 23.*ESP32"):
        flash_esp(mock_mcu, firmware, erase=True)

    mock_esptool["detect"].assert_not_called()
    mock_esptool["erase"].assert_not_called()
    mock_esptool["write"].assert_not_called()


def test_real_invalid_image_is_rejected_before_connecting(mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock], tmp_path: Path) -> None:
    from esptool.bin_image import LoadFirmwareImage

    mock_esptool["image"].side_effect = LoadFirmwareImage
    firmware = tmp_path / "invalid.bin"
    firmware.write_bytes(b"not a firmware image")

    with pytest.raises(MPFlashError, match="Invalid.*firmware"):
        flash_esp(mock_mcu, firmware, erase=True)

    mock_esptool["detect"].assert_not_called()
    mock_esptool["write"].assert_not_called()


def test_compression_fallback_preserves_erase_and_safety_checks(mock_mcu: MagicMock, mock_esptool: dict[str, MagicMock]) -> None:
    mock_esptool["write"].side_effect = [FatalError("compression failed"), None]

    assert flash_esp(mock_mcu, Path("/firmware/esp32.bin"), erase=True) is mock_mcu

    assert mock_esptool["write"].call_count == 2
    for write in mock_esptool["write"].call_args_list:
        assert write.kwargs["erase_all"] is True
        assert write.kwargs.get("force", False) is False
