# MPFlash API Reference

## Overview

This document provides a comprehensive API reference for using MPFlash as a library in your own projects.

## Core Classes and Functions

### Configuration

#### `mpflash.config.MPFlashConfig`

Centralized configuration management for MPFlash.

```python
from mpflash.config import config

# Properties
config.firmware_folder: Path        # Firmware storage directory
config.verbose: bool                # Enable verbose logging
config.quiet: bool                  # Suppress output
config.interactive: bool            # Enable interactive prompts
config.ignore_ports: List[str]      # Ports to ignore
```

**Example:**
```python
from mpflash.config import config

# Set custom firmware directory
config.firmware_folder = Path("/custom/firmware/path")

# Disable interactive mode
config.interactive = False
```

### Board Management

#### `mpflash.connected.get_connected_boards()`

Get list of connected MicroPython boards.

```python
def get_connected_boards(
    serial_ports: Optional[List[str]] = None,
    ignore_ports: Optional[List[str]] = None,
    include_bluetooth: bool = False
) -> List[ConnectedBoard]
```

**Parameters:**
- `serial_ports`: Specific ports to check (default: all)
- `ignore_ports`: Ports to ignore
- `include_bluetooth`: Include Bluetooth ports

**Returns:**
- List of `ConnectedBoard` objects

**Example:**
```python
from mpflash.connected import get_connected_boards

# Get all connected boards
boards = get_connected_boards()

for board in boards:
    print(f"Board: {board.board_name} on {board.port}")
    print(f"Version: {board.version}")
    print(f"MCU: {board.mcu}")
```

#### `mpflash.connected.ConnectedBoard`

Represents a connected MicroPython board.

**Properties:**
```python
port: str                    # Serial port (e.g., "COM3", "/dev/ttyUSB0")
board_id: str               # Board identifier
board_name: str             # Human-readable board name
mcu: str                    # MCU type
version: str                # MicroPython version
build: Optional[str]        # Build number
family: str                 # Board family (usually "micropython")
description: str            # Board description
```

### Database Operations

#### `mpflash.db.core.get_database_session()`

Get SQLAlchemy database session.

```python
from mpflash.db.core import get_database_session
from mpflash.db.models import Board, Firmware

with get_database_session() as session:
    boards = session.query(Board).all()
    for board in boards:
        print(f"Board: {board.board_name}")
```

#### `mpflash.db.models.Board`

SQLAlchemy model for board information.

**Fields:**
```python
board_id: str               # Unique board identifier
version: str                # MicroPython version
board_name: str             # Display name
mcu: str                    # MCU type
variant: str                # Board variant
port: str                   # MicroPython port
path: str                   # Repository path
description: str            # Description
family: str                 # Board family
custom: bool               # Custom board flag
```

#### `mpflash.db.models.Firmware`

SQLAlchemy model for firmware information.

**Fields:**
```python
board_id: str               # Associated board ID
version: str                # MicroPython version
firmware_file: str          # Path to firmware file
port: str                   # MicroPython port
description: str            # Description
source: str                 # Download source
build: int                  # Build number
custom: bool               # Custom firmware flag
```

### Firmware Download

#### `mpflash.download.from_web.download_firmware()`

Download firmware for specified boards.

```python
def download_firmware(
    board_ids: List[str],
    version: str = "stable",
    firmware_dir: Optional[Path] = None
) -> List[Path]
```

**Parameters:**
- `board_ids`: List of board identifiers
- `version`: Version to download ("stable", "preview", or specific version)
- `firmware_dir`: Custom download directory

**Returns:**
- List of paths to downloaded firmware files

**Example:**
```python
from mpflash.download.from_web import download_firmware

# Download stable firmware for specific boards
firmware_files = download_firmware([
    "ESP32_GENERIC",
    "RPI_PICO_W"
], version="stable")

for file_path in firmware_files:
    print(f"Downloaded: {file_path}")
```

### Board Flashing

#### `mpflash.flash.flash_board()`

Flash firmware to a specific board.

```python
def flash_board(
    port: str,
    firmware_path: Path,
    board_type: Optional[str] = None,
    bootloader_method: str = "auto"
) -> bool
```

**Parameters:**
- `port`: Serial port of the board
- `firmware_path`: Path to firmware file
- `board_type`: Board type for platform-specific flashing
- `bootloader_method`: Bootloader activation method

**Returns:**
- True if flashing succeeded, False otherwise

**Example:**
```python
from pathlib import Path
from mpflash.flash import flash_board

firmware_path = Path("firmware/esp32/ESP32_GENERIC-v1.25.0.bin")
success = flash_board(
    port="COM3",
    firmware_path=firmware_path,
    board_type="esp32"
)

if success:
    print("Flashing completed successfully")
else:
    print("Flashing failed")
```

### Board Identification

#### `mpflash.mpboard_id.board_id()`

Identify board connected to a serial port.

```python
def board_id(
    port: str,
    timeout: float = 10.0
) -> Optional[dict]
```

**Parameters:**
- `port`: Serial port to check
- `timeout`: Connection timeout in seconds

**Returns:**
- Dictionary with board information or None if identification fails

**Example:**
```python
from mpflash.mpboard_id import board_id

board_info = board_id("COM3")
if board_info:
    print(f"Board ID: {board_info['board_id']}")
    print(f"MCU: {board_info['mcu']}")
    print(f"Version: {board_info['version']}")
```

### Version Management

#### `mpflash.versions.get_stable_version()`

Get the latest stable MicroPython version.

```python
def get_stable_version() -> str
```

**Returns:**
- Latest stable version string (e.g., "v1.25.0")

#### `mpflash.versions.get_preview_version()`

Get the latest preview MicroPython version.

```python
def get_preview_version() -> str
```

**Returns:**
- Latest preview version string

**Example:**
```python
from mpflash.versions import get_stable_version, get_preview_version

stable = get_stable_version()
preview = get_preview_version()

print(f"Stable: {stable}")
print(f"Preview: {preview}")
```

### Logging

#### `mpflash.logger.log`

Loguru logger instance for MPFlash.

```python
from mpflash.logger import log

log.debug("Debug message")
log.info("Info message")
log.warning("Warning message")
log.error("Error message")
```

#### `mpflash.logger.set_loglevel()`

Set global log level.

```python
def set_loglevel(level: str) -> None
```

**Parameters:**
- `level`: Log level ("TRACE", "DEBUG", "INFO", "WARNING", "ERROR")

## High-Level API Examples

### Complete Board Management Workflow

```python
from pathlib import Path
from mpflash.connected import get_connected_boards
from mpflash.download.from_web import download_firmware
from mpflash.flash import flash_board
from mpflash.logger import log, set_loglevel

# Enable debug logging
set_loglevel("DEBUG")

# Get connected boards
boards = get_connected_boards()
log.info(f"Found {len(boards)} connected boards")

for board in boards:
    log.info(f"Processing {board.board_name} on {board.port}")
    
    try:
        # Download firmware if needed
        firmware_files = download_firmware(
            [board.board_id],
            version="stable"
        )
        
        if firmware_files:
            firmware_path = firmware_files[0]
            log.info(f"Downloaded firmware: {firmware_path}")
            
            # Flash the board
            success = flash_board(
                port=board.port,
                firmware_path=firmware_path,
                board_type=board.port  # Use port as board type
            )
            
            if success:
                log.info(f"Successfully flashed {board.board_name}")
            else:
                log.error(f"Failed to flash {board.board_name}")
        else:
            log.warning(f"No firmware found for {board.board_id}")
            
    except Exception as e:
        log.error(f"Error processing {board.board_name}: {e}")
```

### Custom Firmware Management

```python
from pathlib import Path
from mpflash.db.core import get_database_session
from mpflash.db.models import Board, Firmware

def add_custom_firmware(
    board_id: str,
    version: str,
    firmware_path: Path,
    description: str = ""
):
    """Add custom firmware to database."""
    
    with get_database_session() as session:
        # Check if board exists
        board = session.query(Board).filter_by(
            board_id=board_id,
            version=version
        ).first()
        
        if not board:
            # Create board entry
            board = Board(
                board_id=board_id,
                version=version,
                board_name=f"Custom {board_id}",
                mcu="Unknown",
                port="custom",
                path="custom",
                description=description,
                custom=True
            )
            session.add(board)
        
        # Add firmware
        firmware = Firmware(
            board_id=board_id,
            version=version,
            firmware_file=str(firmware_path),
            description=description,
            source="custom",
            custom=True
        )
        session.add(firmware)
        session.commit()

# Usage
custom_firmware = Path("/path/to/custom/firmware.bin")
add_custom_firmware(
    board_id="CUSTOM_BOARD",
    version="v1.0.0",
    firmware_path=custom_firmware,
    description="Custom firmware build"
)
```

### Board Filtering and Selection

```python
from mpflash.connected import get_connected_boards

def filter_boards_by_criteria(
    min_version: str = "v1.20.0",
    port_types: list = None,
    exclude_patterns: list = None
):
    """Filter boards by various criteria."""
    
    if port_types is None:
        port_types = ["esp32", "rp2"]
    
    if exclude_patterns is None:
        exclude_patterns = ["bluetooth"]
    
    boards = get_connected_boards()
    filtered_boards = []
    
    for board in boards:
        # Check version
        if board.version and board.version < min_version:
            continue
            
        # Check port type
        if board.port not in port_types:
            continue
            
        # Check exclusion patterns
        if any(pattern in board.port.lower() for pattern in exclude_patterns):
            continue
            
        filtered_boards.append(board)
    
    return filtered_boards

# Get ESP32 and RP2 boards with modern firmware
modern_boards = filter_boards_by_criteria(
    min_version="v1.20.0",
    port_types=["esp32", "rp2"]
)
```

## Error Handling

### Exception Classes

#### `mpflash.errors.MPFlashError`

Base exception class for MPFlash operations.

```python
from mpflash.errors import MPFlashError

try:
    # MPFlash operations
    pass
except MPFlashError as e:
    print(f"MPFlash error: {e}")
```

### Common Error Scenarios

```python
from mpflash.errors import MPFlashError
from mpflash.connected import get_connected_boards
from mpflash.logger import log

def safe_board_operation():
    """Example of safe board operations with error handling."""
    
    try:
        boards = get_connected_boards()
        
        if not boards:
            log.warning("No boards connected")
            return
            
        for board in boards:
            try:
                # Perform board-specific operations
                log.info(f"Processing {board.board_name}")
                
            except MPFlashError as e:
                log.error(f"Board operation failed for {board.port}: {e}")
                continue
                
            except Exception as e:
                log.error(f"Unexpected error for {board.port}: {e}")
                continue
                
    except Exception as e:
        log.error(f"Failed to get connected boards: {e}")
        raise
```

## Configuration Examples

### Environment-Based Configuration

```python
import os
from pathlib import Path
from mpflash.config import config

# Configure based on environment
if os.getenv("CI"):
    # CI environment
    config.interactive = False
    config.quiet = True
elif os.getenv("DEBUG"):
    # Development environment
    config.verbose = True
    config.interactive = True

# Custom firmware directory
firmware_dir = os.getenv("MPFLASH_FIRMWARE")
if firmware_dir:
    config.firmware_folder = Path(firmware_dir)
```

### Project-Specific Configuration

```python
from pathlib import Path
from mpflash.config import config

class ProjectConfig:
    """Project-specific MPFlash configuration."""
    
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.firmware_dir = project_dir / "firmware"
        self.setup_mpflash()
    
    def setup_mpflash(self):
        """Configure MPFlash for this project."""
        # Ensure firmware directory exists
        self.firmware_dir.mkdir(exist_ok=True)
        
        # Configure MPFlash
        config.firmware_folder = self.firmware_dir
        config.interactive = False  # Non-interactive for automation
        
        # Project-specific port ignoring
        config.ignore_ports.extend([
            "bluetooth*",  # Ignore Bluetooth ports
            "COM1",        # Ignore COM1 (often used by system)
        ])

# Usage in your project
project = ProjectConfig(Path(__file__).parent)
```

This API reference provides comprehensive coverage of MPFlash's programmatic interface, enabling developers to integrate MPFlash functionality into their own projects effectively.
