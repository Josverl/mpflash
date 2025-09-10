"""Example demonstrating the worklist API.

This example shows how to use the modern, clean API for creating worklists.
"""

from mpflash.flash.worklist import (
    # New API
    create_worklist,
    WorklistConfig,
    create_auto_worklist,
    create_manual_worklist,
    FlashTask,
)
from mpflash.mpremoteboard import MPRemoteBoard


def example_api():
    """Demonstrate the modern API."""
    print("=== Modern API Examples ===")

    # Create some mock boards for demonstration
    boards = [
        MPRemoteBoard("COM1"),
        MPRemoteBoard("COM2"),
    ]

    # Example 1: High-level API for auto-detection
    print("\n1. Auto-detection with high-level API:")
    try:
        tasks = create_worklist("1.22.0", connected_comports=boards)
        print(f"Created {len(tasks)} tasks")
        for task in tasks:
            print(f"  - {task.board.serialport}: {task.board_id} -> {task.firmware_version}")
    except Exception as e:
        print(f"  Would create tasks (mocked): {e}")

    # Example 2: Manual specification
    print("\n2. Manual board specification:")
    try:
        tasks = create_worklist("1.22.0", serial_ports=["COM1"], board_id="ESP32_GENERIC")
        print(f"Created {len(tasks)} manual tasks")
    except Exception as e:
        print(f"  Would create manual tasks (mocked): {e}")

    # Example 3: Configuration-based approach
    print("\n3. Using configuration objects:")
    config = WorklistConfig.for_manual_boards("1.22.0", "ESP32_GENERIC")
    try:
        tasks = create_manual_worklist(["COM1", "COM2"], config)
        print(f"Created {len(tasks)} configured tasks")
    except Exception as e:
        print(f"  Would create configured tasks (mocked): {e}")

    # Example 4: Working with FlashTask objects
    print("\n4. FlashTask objects provide better structure:")
    print("   - task.is_valid: Check if firmware is available")
    print("   - task.board_id: Easy access to board identifier")
    print("   - task.firmware_version: Clear firmware version info")


def advanced_usage():
    """Show advanced usage patterns."""
    print("\n=== Advanced Usage Patterns ===")

    print("\n1. Different configuration approaches:")
    print("""
    # Auto-detection configuration
    config = WorklistConfig.for_auto_detection("1.22.0")
    tasks = create_auto_worklist(connected_comports, config)
    
    # Manual boards configuration
    config = WorklistConfig.for_manual_boards("1.22.0", "ESP32_GENERIC")
    tasks = create_manual_worklist(["COM1", "COM2"], config)
    
    # Filtered boards configuration
    config = WorklistConfig.for_filtered_boards("1.22.0", include_ports=["COM*"])
    tasks = create_filtered_worklist(all_boards, config)
    """)

    print("\n2. Working with FlashTask objects:")
    print("""
    # Clear configuration object
    config = WorklistConfig.for_manual_boards("1.22.0", "ESP32_GENERIC")
    tasks = create_manual_worklist(["COM1", "COM2"], config)
    
    # Working with descriptive objects
    for task in tasks:
        if task.is_valid:
            print(f"{task.board.serialport} -> {task.firmware_version}")
        else:
            print(f"{task.board.serialport} -> No firmware")
    """)

    print("\n3. High-level API for common cases:")
    print("""
    # Auto-detect firmware for connected boards
    tasks = create_worklist("1.22.0", connected_comports=boards)
    
    # Manual specification
    tasks = create_worklist("1.22.0", serial_ports=["COM1"], board_id="ESP32_GENERIC")
    
    # Filtered boards
    tasks = create_worklist("1.22.0", connected_comports=all_boards, include_ports=["COM*"])
    """)


if __name__ == "__main__":
    print("MPFlash Worklist API Example")
    print("=" * 50)

    example_api()
    advanced_usage()

    print("\n" + "=" * 50)
    print("Key Features:")
    print("1. ✅ Descriptive types (FlashTask vs tuple)")
    print("2. ✅ Configuration objects (WorklistConfig)")
    print("3. ✅ Consistent function naming")
    print("4. ✅ High-level API for common cases")
    print("5. ✅ Better error handling and validation")
    print("6. ✅ Clean, maintainable code patterns")
    print("7. ✅ Comprehensive documentation and examples")
