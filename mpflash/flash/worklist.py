"""Worklist for updating boards.

This module provides functionality for creating worklists - collections of board-firmware
pairs that need to be flashed.

The API provides a clean, maintainable interface:

```python
from mpflash.flash.worklist import create_worklist, WorklistConfig

# Simple auto-detection
config = WorklistConfig.for_auto_detection("1.22.0")
tasks = create_auto_worklist(connected_boards, config)

# Or use the high-level function
tasks = create_worklist("1.22.0", connected_boards=boards)

# Manual board specification
tasks = create_worklist("1.22.0", serial_ports=["COM1"], board_id="ESP32_GENERIC")

# Filtered boards
tasks = create_worklist("1.22.0", connected_boards=all_boards, include_ports=["COM*"])
```

"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from loguru import logger as log
from serial.tools.list_ports_common import ListPortInfo
from typing_extensions import TypeAlias

from mpflash.common import filtered_portinfos
from mpflash.db.models import Firmware
from mpflash.downloaded import find_downloaded_firmware
from mpflash.errors import MPFlashError
from mpflash.list import show_mcus
from mpflash.mpboard_id import find_known_board
from mpflash.mpremoteboard import MPRemoteBoard

# #########################################################################################################


@dataclass
class FlashTask:
    """Represents a single board-firmware flashing task."""

    board: MPRemoteBoard
    firmware: Optional[Firmware]

    @property
    def is_valid(self) -> bool:
        """Check if the task has both board and firmware."""
        return self.firmware is not None

    @property
    def board_id(self) -> str:
        """Get the board ID for this task."""
        return self.board.board_id

    @property
    def firmware_version(self) -> str:
        """Get the firmware version for this task."""
        return self.firmware.version if self.firmware else "unknown"


@dataclass
class WorklistConfig:
    """Configuration for creating worklists."""

    version: str
    include_ports: Optional[List[str]] = None
    ignore_ports: Optional[List[str]] = None
    board_id: Optional[str] = None
    custom_firmware: bool = False

    def __post_init__(self):
        if self.include_ports is None:
            self.include_ports = []
        if self.ignore_ports is None:
            self.ignore_ports = []

    @classmethod
    def for_auto_detection(cls, version: str) -> "WorklistConfig":
        """Create config for automatic board detection."""
        return cls(version=version)

    @classmethod
    def for_manual_boards(cls, version: str, board_id: str, custom_firmware: bool = False) -> "WorklistConfig":
        """Create config for manually specified boards."""
        return cls(version=version, board_id=board_id, custom_firmware=custom_firmware)

    @classmethod
    def for_filtered_boards(
        cls, version: str, include_ports: Optional[List[str]] = None, ignore_ports: Optional[List[str]] = None
    ) -> "WorklistConfig":
        """Create config for filtered board selection."""
        return cls(version=version, include_ports=include_ports or [], ignore_ports=ignore_ports or [])


# FIXME: Legacy type aliases - kept for compatibility with deprecated functions
FlashItem: TypeAlias = Tuple[MPRemoteBoard, Optional[Firmware]]
WorkList: TypeAlias = List[FlashItem]
FlashTaskList: TypeAlias = List[FlashTask]

# #########################################################################################################


def _create_flash_task(board: MPRemoteBoard, firmware: Optional[Firmware]) -> FlashTask:
    """Create a FlashTask from board and firmware."""
    return FlashTask(board=board, firmware=firmware)


def _find_firmware_for_board(board: MPRemoteBoard, version: str, custom: bool = False) -> Optional[Firmware]:
    """Find appropriate firmware for a board."""
    board_id = f"{board.board}-{board.variant}" if board.variant else board.board
    firmwares = find_downloaded_firmware(board_id=board_id, version=version, port=board.port, custom=custom)

    if not firmwares:
        log.warning(f"No {version} firmware found for {board.board} on {board.serialport}.")
        return None

    if len(firmwares) > 1:
        log.warning(f"Multiple {version} firmwares found for {board.board} on {board.serialport}.")

    # Use the most recent matching firmware
    firmware = firmwares[-1]
    log.info(f"Found {version} firmware {firmware.firmware_file} for {board.board} on {board.serialport}.")
    return firmware


def _create_manual_board(serial_port: str, board_id: str, version: str, custom: bool = False) -> FlashTask:
    """Create a FlashTask for manually specified board parameters."""
    log.debug(f"Creating manual board task: {serial_port} {board_id} {version}")

    board = MPRemoteBoard(serial_port)

    # Look up board information
    try:
        info = find_known_board(board_id)
        board.port = info.port
        board.cpu = info.mcu  # Need CPU type for esptool
    except (LookupError, MPFlashError) as e:
        log.error(f"Board {board_id} not found in board database")
        log.exception(e)
        return _create_flash_task(board, None)

    board.board = board_id
    firmware = _find_firmware_for_board(board, version, custom)
    return _create_flash_task(board, firmware)


def _filter_connected_boards(
    all_boards: List[MPRemoteBoard],
    include: List[str],
    ignore: List[str],
) -> List[MPRemoteBoard]:
    """Filter connected boards based on include/ignore patterns."""
    try:
        allowed_ports = [
            p.device
            for p in filtered_portinfos(
                ignore=ignore,
                include=include,
                bluetooth=False,
            )
        ]
        return [board for board in all_boards if board.serialport in allowed_ports]
    except ConnectionError as e:
        log.error(f"Error connecting to boards: {e}")
        return []


# #########################################################################################################


# High-level API functions
# #########################################################################################################


def create_worklist(
    version: str,
    *,
    connected_boards: Optional[List[MPRemoteBoard]] = None,
    serial_ports: Optional[List[str]] = None,
    board_id: Optional[str] = None,
    include_ports: Optional[List[str]] = None,
    ignore_ports: Optional[List[str]] = None,
    custom_firmware: bool = False,
) -> FlashTaskList:
    """High-level function to create a worklist based on different scenarios.

    This function automatically determines the appropriate worklist creation method
    based on the provided parameters.

    Args:
        version: Target firmware version
        connected_boards: Pre-detected connected boards (for auto mode)
        serial_ports: Specific serial ports to use (for manual mode)
        board_id: Board ID to use with serial_ports (required for manual mode)
        include_ports: Port patterns to include (for filtered mode)
        ignore_ports: Port patterns to ignore (for filtered mode)
        custom_firmware: Whether to use custom firmware

    Returns:
        List of FlashTask objects

    Raises:
        ValueError: If parameters are inconsistent or missing required values

    Examples:
        # Auto-detect firmware for connected boards
        tasks = create_worklist("1.22.0", connected_boards=boards)

        # Manual specification
        tasks = create_worklist("1.22.0", serial_ports=["COM1"], board_id="ESP32_GENERIC")

        # Filtered boards
        tasks = create_worklist("1.22.0", connected_boards=all_boards, include_ports=["COM*"])
    """
    # Manual mode: specific serial ports with board_id
    if serial_ports and board_id:
        config = WorklistConfig.for_manual_boards(version, board_id, custom_firmware)
        return create_manual_worklist(serial_ports, config)

    # Auto mode with filtering
    if connected_boards and (include_ports or ignore_ports):
        config = WorklistConfig.for_filtered_boards(version, include_ports, ignore_ports)
        return create_filtered_worklist(connected_boards, config)

    # Simple auto mode
    if connected_boards:
        config = WorklistConfig.for_auto_detection(version)
        return create_auto_worklist(connected_boards, config)

    # Error cases
    if serial_ports and not board_id:
        raise ValueError("board_id is required when specifying serial_ports for manual mode")

    if not connected_boards and not serial_ports:
        raise ValueError("Either connected_boards or serial_ports must be provided")

    raise ValueError("Invalid combination of parameters")


# New, simplified API functions
# #########################################################################################################


def create_auto_worklist(
    connected_boards: List[MPRemoteBoard],
    config: WorklistConfig,
) -> FlashTaskList:
    """Create a worklist by automatically detecting firmware for connected boards.

    Args:
        connected_boards: List of connected MicroPython boards
        config: Configuration for the worklist creation

    Returns:
        List of FlashTask objects
    """
    log.debug(f"Creating auto worklist for {len(connected_boards)} boards, target version: {config.version}")

    tasks: FlashTaskList = []
    for board in connected_boards:
        if board.family not in ("micropython", "unknown"):
            log.warning(
                f"Skipping flashing {board.family} {board.port} {board.board} on {board.serialport} as it is not a MicroPython firmware"
            )
            continue

        firmware = _find_firmware_for_board(board, config.version, config.custom_firmware)
        tasks.append(_create_flash_task(board, firmware))

    return tasks


def create_manual_worklist(
    serial_ports: List[str],
    config: WorklistConfig,
) -> FlashTaskList:
    """Create a worklist for manually specified boards and firmware.

    Args:
        serial_ports: List of serial port identifiers
        config: Configuration including board_id and version

    Returns:
        List of FlashTask objects
    """
    if not config.board_id:
        raise ValueError("board_id must be specified for manual worklist creation")

    log.debug(f"Creating manual worklist for {len(serial_ports)} ports, board_id: {config.board_id}, version: {config.version}")

    tasks: FlashTaskList = []
    for port in serial_ports:
        log.trace(f"Manual updating {port} to {config.board_id} {config.version}")
        task = _create_manual_board(port, config.board_id, config.version, config.custom_firmware)
        tasks.append(task)

    return tasks


def create_filtered_worklist(
    all_boards: List[MPRemoteBoard],
    config: WorklistConfig,
) -> FlashTaskList:
    """Create a worklist for filtered connected boards.

    Args:
        all_boards: All available connected boards
        config: Configuration including include/ignore patterns and version

    Returns:
        List of FlashTask objects
    """
    log.debug(
        f"Creating filtered worklist from {len(all_boards)} boards, include: {config.include_ports}, ignore: {config.ignore_ports}, version: {config.version}"
    )

    filtered_boards = _filter_connected_boards(all_boards, config.include_ports or [], config.ignore_ports or [])
    if not filtered_boards:
        log.warning("No boards match the filtering criteria")
        return []

    return create_auto_worklist(filtered_boards, config)


def create_single_board_worklist(
    serial_port: str,
    config: WorklistConfig,
) -> FlashTaskList:
    """Create a worklist for a single serial port with automatic detection.

    Args:
        serial_port: Serial port identifier
        config: Configuration with version information

    Returns:
        List of FlashTask objects (typically containing one item)
    """
    log.debug(f"Creating single board worklist: {serial_port} version: {config.version}")
    log.trace(f"Auto updating {serial_port} to {config.version}")

    connected_boards = [MPRemoteBoard(serial_port)]
    tasks = create_auto_worklist(connected_boards, config)
    show_mcus(connected_boards)
    return tasks


# End of worklist.py module
