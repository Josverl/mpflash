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
        # Variant V1.20.0 --> 1.25.0
        (
            "GENERIC_SPIRAM",
            "",
            [
                "GENERIC_SPIRAM",
                "ESP32_GENERIC_SPIRAM",
                "ESP8266_GENERIC_SPIRAM",
                "GENERIC",
                # "GENERIC-SPIRAM",
                "ESP32_GENERIC",
                # "ESP32_GENERIC-SPIRAM",
                "ESP8266_GENERIC",
                # "ESP8266_GENERIC-SPIRAM",
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
