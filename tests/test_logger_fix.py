#!/usr/bin/env python3
"""
Test script to verify the logger fixes for angle bracket issues.

This script simulates the error condition that was occurring with
the micropython-stubber package when logging messages containing
angle bracket notation like <board_default>.

Run this script to verify that the logging fixes are working properly.
"""

import sys
from pathlib import Path

# Add the mpflash package to the path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger as log
from mpflash.logger import set_loglevel


def test_angle_bracket_logging():
    """Test logging messages with angle brackets."""
    # Test messages that previously caused errors
    test_messages = [
        "# .. class:: LAN(id, *, phy_type=<board_default>, phy_addr=<board_default>, ref_clk_mode=<board_default>)",
        "# class:: LAN - LAN(id, *, phy_type=<board_default>, phy_addr=<board_default>, ref_clk_mode=<board_default>)",
        "Testing <something> with angle brackets",
        "Normal message without angle brackets",
        "Message with {curly} braces",
        "Mixed message with <angle> and {curly} brackets",
        "Complex case: <board_default> and {format} with <tag>value</tag>",
    ]

    set_loglevel("TRACE")

    success_count = 0
    for i, message in enumerate(test_messages, 1):
        try:
            log.trace(f"Test {i}: {message}")
            success_count += 1
        except Exception as e:
            print(f"Error logging message {i}: {e}")

    assert success_count == len(test_messages)

