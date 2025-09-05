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

from mpflash.logger import configure_safe_logging, set_loglevel, setup_external_logger_safety


def test_angle_bracket_logging():
    """Test logging messages with angle brackets."""
    print("=" * 60)
    print("Testing MPFlash Logger Fixes for Angle Bracket Issues")
    print("=" * 60)

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

    print(f"\nTesting {len(test_messages)} problematic log messages...")

    # Test 1: Standard MPFlash logger configuration
    print("\n1. Testing with standard MPFlash logger configuration:")
    print("-" * 50)
    set_loglevel("TRACE")

    success_count = 0
    for i, message in enumerate(test_messages, 1):
        try:
            log.trace(f"Test {i}: {message}")
            print(f"   ✓ Successfully logged message {i}")
            success_count += 1
        except Exception as e:
            print(f"   ✗ Error logging message {i}: {e}")

    print(f"   Result: {success_count}/{len(test_messages)} messages logged successfully")

    # Test 2: Safe configuration
    print("\n2. Testing with safe logger configuration:")
    print("-" * 50)
    configure_safe_logging()

    safe_success_count = 0
    for i, message in enumerate(test_messages, 1):
        try:
            log.trace(f"Safe Test {i}: {message}")
            print(f"   ✓ Successfully logged safe message {i}")
            safe_success_count += 1
        except Exception as e:
            print(f"   ✗ Error logging safe message {i}: {e}")

    print(f"   Result: {safe_success_count}/{len(test_messages)} messages logged successfully")

    # Test 3: External logger safety setup
    print("\n3. Testing external logger safety setup:")
    print("-" * 50)
    setup_external_logger_safety()

    external_success_count = 0
    for i, message in enumerate(test_messages, 1):
        try:
            log.trace(f"External Test {i}: {message}")
            print(f"   ✓ Successfully logged external message {i}")
            external_success_count += 1
        except Exception as e:
            print(f"   ✗ Error logging external message {i}: {e}")

    print(f"   Result: {external_success_count}/{len(test_messages)} messages logged successfully")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    print(
        f"Standard MPFlash logger:    {success_count}/{len(test_messages)} ({'✓ PASS' if success_count == len(test_messages) else '✗ FAIL'})"
    )
    print(
        f"Safe logger configuration:  {safe_success_count}/{len(test_messages)} ({'✓ PASS' if safe_success_count == len(test_messages) else '✗ FAIL'})"
    )
    print(
        f"External logger safety:     {external_success_count}/{len(test_messages)} ({'✓ PASS' if external_success_count == len(test_messages) else '✗ FAIL'})"
    )

    if all(count == len(test_messages) for count in [success_count, safe_success_count, external_success_count]):
        print("\n🎉 ALL TESTS PASSED! The logger fixes are working correctly.")
        print("\nTo prevent stubber logging errors, use:")
        print("   from mpflash.logger import setup_external_logger_safety")
        print("   setup_external_logger_safety()")
    else:
        print("\n⚠️  Some tests failed. Please check the configuration.")

    print("=" * 60)


if __name__ == "__main__":
    test_angle_bracket_logging()
