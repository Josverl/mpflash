"""Flash PSoC6 boards using OpenOCD

PSoC6 (Infineon/Cypress) boards typically require OpenOCD for programming via SWD/JTAG.
This module provides flashing support for PSoC6 boards using OpenOCD with the KitProg3
interface which is common on Infineon development boards.

Supported firmware formats:
- .hex files: Intel HEX format
- .elf files: ELF executable format  
- .bin files: Raw binary format (flashed at 0x10000000)

Requirements:
- OpenOCD must be installed and available in PATH
- KitProg3 or compatible SWD/JTAG interface
- Appropriate OpenOCD configuration files for PSoC6
"""

import subprocess
import platform
from pathlib import Path
from typing import Optional

from loguru import logger as log

from mpflash.mpremoteboard import MPRemoteBoard


def flash_psoc6(
    mcu: MPRemoteBoard,
    fw_file: Path,
    *,
    erase: bool = True,
) -> Optional[MPRemoteBoard]:
    """
    Flash PSoC6 microcontroller using OpenOCD.

    Args:
        mcu (MPRemoteBoard): The remote board to flash.
        fw_file (Path): The path to the firmware file (.hex, .elf, or .bin).
        erase (bool, optional): Whether to erase the memory before flashing. Defaults to True.

    Returns:
        Optional[MPRemoteBoard]: The flashed remote board if successful, None otherwise.
    """
    log.info(f"Flashing PSoC6 {mcu.board} on {mcu.serialport} with {fw_file}")

    if not fw_file.exists():
        log.error(f"Firmware file {fw_file} not found")
        return None

    if fw_file.suffix not in [".hex", ".elf", ".bin"]:
        log.error(f"Unsupported firmware file format: {fw_file.suffix}")
        return None

    # Check if OpenOCD is available
    if not _check_openocd_available():
        log.error("OpenOCD not found. Please install OpenOCD to flash PSoC6 boards.")
        return None

    try:
        success = _flash_with_openocd(mcu, fw_file, erase=erase)
        if success:
            log.success(f"Successfully flashed {mcu.board} on {mcu.serialport}")
            return mcu
        else:
            log.error(f"Failed to flash {mcu.board} on {mcu.serialport}")
            return None
    except Exception as e:
        log.error(f"Error flashing PSoC6 board: {e}")
        return None


def _check_openocd_available() -> bool:
    """Check if OpenOCD is available in the system."""
    try:
        result = subprocess.run(
            ["openocd", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _flash_with_openocd(
    mcu: MPRemoteBoard,
    fw_file: Path,
    erase: bool = True
) -> bool:
    """
    Flash firmware using OpenOCD.

    Args:
        mcu: The MicroPython remote board
        fw_file: Path to firmware file
        erase: Whether to erase before flashing

    Returns:
        bool: True if successful, False otherwise
    """
    # Build OpenOCD command
    cmd = ["openocd"]
    
    # Add interface configuration - default to KitProg3 which is common for PSoC6 dev boards
    cmd.extend(["-f", "interface/kitprog3.cfg"])
    
    # Add target configuration - PSoC6 family
    cmd.extend(["-f", "target/psoc6.cfg"])
    
    # Build the flash commands
    flash_commands = []
    
    if erase:
        flash_commands.append("psoc6 mass_erase 0")
    
    # Determine the programming command based on file type
    if fw_file.suffix == ".hex":
        flash_commands.append(f"program {fw_file} verify reset")
    elif fw_file.suffix == ".elf":
        flash_commands.append(f"program {fw_file} verify reset")
    elif fw_file.suffix == ".bin":
        # For .bin files, we need to specify the address (typically 0x10000000 for PSoC6)
        flash_commands.append(f"program {fw_file} 0x10000000 verify reset")
    
    flash_commands.append("exit")
    
    # Add the commands to OpenOCD
    for cmd_str in flash_commands:
        cmd.extend(["-c", cmd_str])
    
    log.debug(f"Running OpenOCD command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # OpenOCD can take some time
        )
        
        if result.returncode == 0:
            log.debug("OpenOCD flashing successful")
            log.trace(f"OpenOCD stdout: {result.stdout}")
            return True
        else:
            log.error(f"OpenOCD failed with return code {result.returncode}")
            log.debug(f"OpenOCD stderr: {result.stderr}")
            log.debug(f"OpenOCD stdout: {result.stdout}")
            return False
            
    except subprocess.TimeoutExpired:
        log.error("OpenOCD command timed out")
        return False
    except Exception as e:
        log.error(f"Error running OpenOCD: {e}")
        return False


def _get_psoc6_board_config(board: str) -> str:
    """
    Get the appropriate OpenOCD configuration for a specific PSoC6 board.
    
    Args:
        board: Board identifier
        
    Returns:
        str: OpenOCD target configuration file name
    """
    # Map board names to OpenOCD configurations
    board_configs = {
        "CY8CPROTO-062-4343W": "psoc6.cfg",
        "CY8CKIT-062-BLE": "psoc6.cfg", 
        "CY8CKIT-062-WIFI-BT": "psoc6.cfg",
        "CY8CPROTO-063-BLE": "psoc6.cfg",
        # Add more board-specific configurations as needed
    }
    
    return board_configs.get(board.upper(), "psoc6.cfg")  # Default to generic PSoC6 config