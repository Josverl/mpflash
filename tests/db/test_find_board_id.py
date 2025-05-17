from pathlib import Path

import pytest

from mpflash.errors import MPFlashError
from mpflash.mpboard_id.board_id import _find_board_id_by_description, find_board_id_by_description

pytestmark = [pytest.mark.mpflash]

# Constants for test
HERE = Path(__file__).parent




@pytest.mark.parametrize(
    "test_id,version, descr, short_descr,  expected_result",
    [
        # Happy path tests
        ("happy-1", "stable", "Arduino Nano RP2040 Connect", None, "ARDUINO_NANO_RP2040_CONNECT"),
        ("happy-2", "v1.23.0", "Pimoroni Tiny 2040", None, "PIMORONI_TINY2040"),
        ("happy-3", "v1.23.0", "Pimoroni Tiny 2040", "", "PIMORONI_TINY2040"),
        (
            "happy-4",
            "stable",
            "Generic ESP32 module with ESP32",
            "Generic ESP32 module",
            "ESP32_GENERIC",
        ),
        # Edge cases
        ("edge-1", "v1.23.0", "Pimoroni Tiny 2040 fake", "Pimoroni Tiny 2040", "PIMORONI_TINY2040"),
        (
            "edge-2",
            "stable",
            "Generic ESP32 module with ESP32 OTA",
            "Generic ESP32 module with ESP32",
            "ESP32_GENERIC",
        ),
        # v13.0
        # ("esp32_v1.13-a", "v1.13", "ESP32 module with ESP32", None, "GENERIC"),
        # ("esp32_v1.13-b", "v1.13", "ESP32 module with ESP32", "ESP32 module", "GENERIC"),
        # ("esp32_v1.14-a", "v1.14", "ESP32 module with ESP32", None, "GENERIC"),
        # ("esp32_v1.15-a", "v1.15", "ESP32 module with ESP32", None, "GENERIC"),
        # ("esp32_v1.16-a", "v1.16", "ESP32 module with ESP32", None, "GENERIC"),
        # ("esp32_v1.17-a", "v1.17", "ESP32 module with ESP32", None, "GENERIC"),
        ("esp32_v1.18-a", "v1.18", "ESP32 module (spiram) with ESP32", None, "GENERIC_SPIRAM"),
        ("esp32_v1.19.1-a", "v1.19.1", "ESP32 module (spiram) with ESP32", None, "GENERIC_SPIRAM"),
        ("esp32_v1.19.1-a", "v1.20.0", "ESP32 module (spiram) with ESP32", None, "GENERIC_SPIRAM"),
        # ESP32 board names changed in v1.21.0
        ("esp32_v1.21.0-a", "v1.21.0", "Generic ESP32 module with ESP32", None, "ESP32_GENERIC"),
        ("esp32_v1.22.0-a", "v1.22.0", "Generic ESP32 module with ESP32", None, "ESP32_GENERIC"),
        ("esp32_v1.21.0-a", None, "Generic ESP32 module with ESP32", None, "ESP32_GENERIC"),
        ("esp32_v1.22.0-a", None, "Generic ESP32 module with ESP32", None, "ESP32_GENERIC"),
        # PICO
        (
            "pico_v1.19.1-old",
            "v1.19.1",
            "Raspberry Pi Pico with RP2040",
            "Raspberry Pi Pico",
            "PICO",
        ),
        (
            "pico_v1.23.0",
            "v1.23.0",
            "Raspberry Pi Pico with RP2040",
            "Raspberry Pi Pico",
            "RPI_PICO",
        ),
        # Error cases
        ("error-1", "stable", "Board FOO", "FOO", None),
        ("error-2", "stable", "Board BAR", "BAR", None),
        ("removed-3", "v1.24.0", "Pimoroni Tiny 2040", "", None),
        # Bugs #1
        ("PICO2_W", "1.25.0", "Raspberry Pi Pico 2 W with RP2350", "Raspberry Pi Pico 2 W", "RPI_PICO2_W"),
        ("PICO2_W", "1.25.0", "Raspberry Pi Pico 2 W", "", "RPI_PICO2_W"),
        ("RPI_PICO_W", "1.25.0", "Raspberry Pi Pico 2 W", "", "RPI_PICO2_W"),
    ],
)
@pytest.mark.parametrize("test_data", [True, False])
def test_find_board_id_real(test_id, test_data, descr, short_descr, expected_result, version, mocker, session_fx):
    # Act
    # patch the Session
    if test_data:
        mocker.patch("mpflash.mpboard_id.board_id.Session", session_fx)

    if expected_result:
        result = find_board_id_by_description(descr=descr, short_descr=short_descr, version=version)
        # Assert
        assert result == expected_result
    else:
        with pytest.raises(MPFlashError):
            # internal method raises exception
            _find_board_id_by_description(descr=descr, short_descr=short_descr, version=version)
