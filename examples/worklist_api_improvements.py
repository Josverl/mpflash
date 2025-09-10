"""Example demonstrating the worklist API improvements.

This example shows how the new API simplifies common tasks while maintaining
backward compatibility with the legacy API.
"""

from mpflash.flash.worklist import (
    # New API
    create_worklist,
    WorklistConfig,
    create_auto_worklist,
    create_manual_worklist,
    FlashTask,
    
    # Legacy API (still works)
    auto_update_worklist,
    manual_worklist,
    WorkList,
)
from mpflash.mpremoteboard import MPRemoteBoard


def example_new_api():
    """Demonstrate the new, simplified API."""
    print("=== New API Examples ===")
    
    # Create some mock boards for demonstration
    boards = [
        MPRemoteBoard("COM1"),
        MPRemoteBoard("COM2"),
    ]
    
    # Example 1: High-level API for auto-detection
    print("\n1. Auto-detection with high-level API:")
    try:
        tasks = create_worklist("1.22.0", connected_boards=boards)
        print(f"Created {len(tasks)} tasks")
        for task in tasks:
            print(f"  - {task.board.serialport}: {task.board_id} -> {task.firmware_version}")
    except Exception as e:
        print(f"  Would create tasks (mocked): {e}")
    
    # Example 2: Manual specification
    print("\n2. Manual board specification:")
    try:
        tasks = create_worklist(
            "1.22.0", 
            serial_ports=["COM1"], 
            board_id="ESP32_GENERIC"
        )
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


def example_legacy_api():
    """Demonstrate the legacy API (still supported)."""
    print("\n=== Legacy API Examples (still works) ===")
    
    # Create some mock boards
    boards = [
        MPRemoteBoard("COM1"),
        MPRemoteBoard("COM2"),
    ]
    
    # Legacy auto-detection
    print("\n1. Legacy auto-detection:")
    try:
        worklist = auto_update_worklist(boards, "1.22.0")
        print(f"Created legacy worklist with {len(worklist)} items")
        for board, firmware in worklist:
            version = firmware.version if firmware else "unknown"
            print(f"  - {board.serialport}: {board.board_id} -> {version}")
    except Exception as e:
        print(f"  Would create legacy worklist (mocked): {e}")
    
    # Legacy manual specification
    print("\n2. Legacy manual specification:")
    try:
        worklist = manual_worklist(
            ["COM1"], 
            board_id="ESP32_GENERIC", 
            version="1.22.0"
        )
        print(f"Created legacy manual worklist with {len(worklist)} items")
    except Exception as e:
        print(f"  Would create legacy manual worklist (mocked): {e}")


def comparison():
    """Show side-by-side comparison of old vs new approaches."""
    print("\n=== API Comparison ===")
    
    print("\nOLD WAY (still works):")
    print("""
    # Multiple parameters, unclear order
    worklist = manual_worklist(
        ["COM1", "COM2"],
        board_id="ESP32_GENERIC",
        version="1.22.0",
        custom=False
    )
    
    # Working with tuples
    for board, firmware in worklist:
        if firmware:
            print(f"{board.serialport} -> {firmware.version}")
        else:
            print(f"{board.serialport} -> No firmware")
    """)
    
    print("\nNEW WAY (recommended):")
    print("""
    # Clear configuration object
    config = WorklistConfig.for_manual_boards("1.22.0", "ESP32_GENERIC")
    tasks = create_manual_worklist(["COM1", "COM2"], config)
    
    # Or even simpler high-level API
    tasks = create_worklist("1.22.0", serial_ports=["COM1", "COM2"], board_id="ESP32_GENERIC")
    
    # Working with descriptive objects
    for task in tasks:
        if task.is_valid:
            print(f"{task.board.serialport} -> {task.firmware_version}")
        else:
            print(f"{task.board.serialport} -> No firmware")
    """)


if __name__ == "__main__":
    print("MPFlash Worklist API Improvements Example")
    print("=" * 50)
    
    example_new_api()
    example_legacy_api()
    comparison()
    
    print("\n" + "=" * 50)
    print("Key Improvements:")
    print("1. ✅ Descriptive types (FlashTask vs tuple)")
    print("2. ✅ Configuration objects (WorklistConfig)")
    print("3. ✅ Consistent function naming") 
    print("4. ✅ High-level API for common cases")
    print("5. ✅ Better error handling and validation")
    print("6. ✅ Full backward compatibility")
    print("7. ✅ Improved documentation and examples")