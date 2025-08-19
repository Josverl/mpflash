"""Worklist for updating boards"""

from typing import List, Optional, Tuple

from loguru import logger as log
from typing_extensions import TypeAlias

from mpflash.common import filtered_portinfos, FlashMethod
from mpflash.db.models import Firmware
from mpflash.downloaded import find_downloaded_firmware
from mpflash.errors import MPFlashError
from mpflash.list import show_mcus
from mpflash.mpboard_id import find_known_board
from mpflash.mpremoteboard import MPRemoteBoard

# #########################################################################################################
FlashItem: TypeAlias = Tuple[MPRemoteBoard, Optional[Firmware]]
WorkList: TypeAlias = List[FlashItem]


def select_firmware_for_method(firmwares: List[Firmware], method: FlashMethod) -> Firmware:
    """
    Select the best firmware file based on the flash method.
    
    Args:
        firmwares: List of available firmware files for the board
        method: Flash method to be used
        
    Returns:
        Best firmware file for the specified method
    """
    if not firmwares:
        raise MPFlashError("No firmware files available")
    
    if len(firmwares) == 1:
        return firmwares[0]
    
    # Define preferred file extensions for each method
    method_preferences = {
        FlashMethod.PYOCD: ['.hex', '.bin', '.elf'],
        FlashMethod.DFU: ['.dfu'],
        FlashMethod.UF2: ['.uf2'],
        FlashMethod.ESPTOOL: ['.bin'],
        FlashMethod.SERIAL: ['.dfu', '.hex', '.bin', '.uf2'],  # Allow any for serial methods
        FlashMethod.AUTO: ['.dfu', '.hex', '.bin', '.uf2', '.elf']  # Default order
    }
    
    preferred_extensions = method_preferences.get(method, method_preferences[FlashMethod.AUTO])
    
    # Try to find firmware with preferred extensions in order
    for ext in preferred_extensions:
        for fw in firmwares:
            if fw.firmware_file.lower().endswith(ext):
                log.debug(f"Selected {fw.firmware_file} for method {method.value} (preferred extension: {ext})")
                return fw
    
    # If no preferred format found, use the last one (original behavior)
    log.debug(f"No preferred format found for method {method.value}, using default: {firmwares[-1].firmware_file}")
    return firmwares[-1]


# #########################################################################################################


def auto_update_worklist(
    conn_boards: List[MPRemoteBoard],
    target_version: str,
    method: FlashMethod = FlashMethod.AUTO,
) -> WorkList:
    """Builds a list of boards to update based on the connected boards and the firmwares available locally in the firmware folder.

    Args:
        conn_boards (List[MPRemoteBoard]): List of connected boards
        target_version (str): Target firmware version
        selector (Optional[Dict[str, str]], optional): Selector for filtering firmware. Defaults to None.

    Returns:
        WorkList: List of boards and firmware information to update
    """
    log.debug(f"auto_update_worklist: {len(conn_boards)} boards, target version: {target_version}")
    wl: WorkList = []
    for mcu in conn_boards:
        if mcu.family not in ("micropython", "unknown"):
            log.warning(f"Skipping flashing {mcu.family} {mcu.port} {mcu.board} on {mcu.serialport} as it is not a MicroPython firmware")
            continue
        board_firmwares = find_downloaded_firmware(
            board_id=f"{mcu.board}-{mcu.variant}" if mcu.variant else mcu.board,
            version=target_version,
            port=mcu.port,
        )

        if not board_firmwares:
            log.warning(f"No {target_version} firmware found for {mcu.board} on {mcu.serialport}.")
            wl.append((mcu, None))
            continue

        if len(board_firmwares) > 1:
            log.warning(f"Multiple {target_version} firmwares found for {mcu.board} on {mcu.serialport}.")

        # Select firmware based on flash method
        fw_info = select_firmware_for_method(board_firmwares, method)
        log.info(f"Found {target_version} firmware {fw_info.firmware_file} for {mcu.board} on {mcu.serialport}.")
        wl.append((mcu, fw_info))
    return wl


def manual_worklist(
    serial: List[str],
    *,
    board_id: str,
    version: str,
    custom: bool = False,
    method: FlashMethod = FlashMethod.AUTO,
) -> WorkList:
    """Create a worklist for manually specified boards."""
    log.debug(f"manual_worklist: {len(serial)} serial ports, board_id: {board_id}, version: {version}")
    wl: WorkList = []
    for comport in serial:
        log.trace(f"Manual updating {comport} to {board_id} {version}")
        wl.append(manual_board(comport, board_id=board_id, version=version, custom=custom, method=method))
    return wl


def manual_board(
    serial: str,
    *,
    board_id: str,
    version: str,
    custom: bool = False,
    method: FlashMethod = FlashMethod.AUTO,
) -> FlashItem:
    """Create a Flash work item for a single board specified manually.

    Args:
        serial (str): Serial port of the board
        board (str): Board_ID
        version (str): Firmware version

    Returns:
        FlashItem: Board and firmware information to update
    """
    log.debug(f"manual_board: {serial} {board_id} {version}")
    mcu = MPRemoteBoard(serial)
    # Lookup the matching port and cpu in board_info based in the board name
    try:
        info = find_known_board(board_id)
        mcu.port = info.port
        # need the CPU type for the esptool
        mcu.cpu = info.mcu
    except (LookupError, MPFlashError) as e:
        log.error(f"Board {board_id} not found in board database")
        log.exception(e)
        return (mcu, None)
    mcu.board = board_id
    firmwares = find_downloaded_firmware(board_id=board_id, version=version, port=mcu.port, custom=custom)
    if not firmwares:
        log.trace(f"No firmware found for {mcu.port} {board_id} version {version}")
        return (mcu, None)
    # Select firmware based on flash method
    fw_info = select_firmware_for_method(firmwares, method)
    return (mcu, fw_info)


def single_auto_worklist(
    serial: str,
    *,
    version: str,
    method: FlashMethod = FlashMethod.AUTO,
) -> WorkList:
    """Create a worklist for a single serial-port.

    Args:
        serial_port (str): Serial port of the board
        version (str): Firmware version

    Returns:
        WorkList: List of boards and firmware information to update
    """
    log.debug(f"single_auto_worklist: {serial} version: {version}")
    log.trace(f"Auto updating {serial} to {version}")
    conn_boards = [MPRemoteBoard(serial)]
    todo = auto_update_worklist(conn_boards, version, method)  # type: ignore # List / list
    show_mcus(conn_boards)
    return todo


def full_auto_worklist(
    all_boards: List[MPRemoteBoard],
    *,
    include: List[str],
    ignore: List[str],
    version: str,
    method: FlashMethod = FlashMethod.AUTO,
) -> WorkList:
    """
    Create a worklist for all connected micropython boards based on the information retrieved from the board.
    This allows the firmware version of one or more boards to be changed without needing to specify the port or board_id manually.

    Args:
        version (str): Firmware version

    Returns:
        WorkList: List of boards and firmware information to update
    """
    log.debug(f"full_auto_worklist: {len(all_boards)} boards, include: {include}, ignore: {ignore}, version: {version}")
    if selected_boards := filter_boards(all_boards, include=include, ignore=ignore):
        return auto_update_worklist(selected_boards, version, method)
    else:
        return []


def filter_boards(
    all_boards: List[MPRemoteBoard],
    *,
    include: List[str],
    ignore: List[str],
):
    try:
        comports = [
            p.device
            for p in filtered_portinfos(
                ignore=ignore,
                include=include,
                bluetooth=False,
            )
        ]
        selected_boards = [b for b in all_boards if b.serialport in comports]
        # [MPRemoteBoard(port.device, update=True) for port in comports]
    except ConnectionError as e:
        log.error(f"Error connecting to boards: {e}")
        return []
    return selected_boards  # type: ignore
