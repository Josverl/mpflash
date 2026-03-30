from typing import List

import pytest

from mpflash.mpboard_id.alternate import add_renamed_boards, alternate_board_names

"""
Tests for alternate board names functions.

This module tests the alternate_board_names and add_renamed_boards functions.
It verifies that alternate names are created correctly based on board prefixes
and that the boards list is extended properly.
"""


@pytest.mark.parametrize(
    "board_id, port, expected",
    [
        ("MYBOARD", "", ["MYBOARD"]),
        ("BOARD_SPIRAM", "", ["BOARD_SPIRAM", "BOARD"]),
        ("BOARD_THREAD", "", ["BOARD_THREAD", "BOARD"]),
        ("PICO", "", ["PICO", "RPI_PICO"]),
        ("PICO_W", "", ["PICO_W", "RPI_PICO_W"]),
        ("RPI_BOARD", "", ["RPI_BOARD", "BOARD"]),
        ("GENERIC", "", ["GENERIC", "ESP32_GENERIC", "ESP8266_GENERIC"]),
        ("GENERIC", "myPort", ["GENERIC", "MYPORT_GENERIC"]),
        ("ESP32_BOARDEXTRA", "", ["ESP32_BOARDEXTRA", "BOARDEXTRA"]),
        ("ESP8266_DEVICE", "", ["ESP8266_DEVICE", "DEVICE"]),
        # Old board name GENERIC_SPIRAM (esp32, v1.18-v1.20) with explicit port.
        # From v1.21.0 the board was renamed to ESP32_GENERIC-SPIRAM (hyphen).
        # Both the underscore form (ESP32_GENERIC_SPIRAM) and the hyphen form
        # (ESP32_GENERIC-SPIRAM) must be included so old firmware can be found.
        (
            "GENERIC_SPIRAM",
            "esp32",
            [
                "GENERIC_SPIRAM",
                "ESP32_GENERIC_SPIRAM",
                "ESP32_GENERIC-SPIRAM",
                "GENERIC",
                "ESP32_GENERIC",
            ],
        ),
        # Old board name GENERIC_SPIRAM without port hint → both ESP32 and ESP8266 variants.
        (
            "GENERIC_SPIRAM",
            "",
            [
                "GENERIC_SPIRAM",
                "ESP32_GENERIC_SPIRAM",
                "ESP32_GENERIC-SPIRAM",
                "ESP8266_GENERIC_SPIRAM",
                "ESP8266_GENERIC-SPIRAM",
                "GENERIC",
                "ESP32_GENERIC",
                "ESP8266_GENERIC",
            ],
        ),
    ],
)
def test_alternate_board_names(board_id: str, port: str, expected: List[str]) -> None:
    """
    Test alternate_board_names to ensure the function produces the correct alternate names.
    """
    result = alternate_board_names(board_id, port)
    assert result == expected, f"Expected {expected} but got {result} for board_id: {board_id}, port: {port}"
