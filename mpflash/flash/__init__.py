from pathlib import Path

from loguru import logger as log

from mpflash.bootloader.activate import enter_bootloader
from mpflash.common import PORT_FWTYPES, UF2_PORTS, BootloaderMethod, FlashMethod
from mpflash.config import config
from mpflash.errors import MPFlashError

from .esp import flash_esp
from .stm32 import flash_stm32
from .uf2 import flash_uf2
from .worklist import WorkList

# Import debug probe support
from .debug_probe import is_debug_programming_available
from .pyocd_flash import flash_pyocd, pyocd_info
from .pyocd_core import is_pyocd_supported as is_pyocd_supported_from_mcu, is_pyocd_available as pyocd_available

# #########################################################################################################

def flash_list(
    todo: WorkList,
    erase: bool,
    bootloader: BootloaderMethod,
    method: FlashMethod = FlashMethod.AUTO,
    **kwargs
):  # sourcery skip: use-named-expression
    """Flash a list of boards with the specified firmware."""
    flashed = []
    for mcu, fw_info in todo:
        if not fw_info:
            log.error(f"Firmware not found for {mcu.board} on {mcu.serialport}, skipping")
            continue

        fw_file = config.firmware_folder / fw_info.firmware_file
        if not fw_file.exists():
            log.error(f"File {fw_file} does not exist, skipping {mcu.board} on {mcu.serialport}")
            continue

        log.info(f"Updating {mcu.board} on {mcu.serialport} to {fw_info.version}")
        try:
            updated = flash_mcu(mcu, fw_file=fw_file, erase=erase, bootloader=bootloader, method=method, **kwargs)
        except MPFlashError as e:
            log.error(f"Failed to flash {mcu.board} on {mcu.serialport}: {e}")
            continue
        if updated:
            if fw_info.custom:
                # Add / Update board_info.toml with the custom_id and Description
                mcu.get_board_info_toml()
                if fw_info.description:
                    mcu.toml["description"] = fw_info.description
                mcu.toml["mpflash"]["board_id"] = fw_info.board_id
                mcu.toml["mpflash"]["custom_id"] = fw_info.custom_id
                mcu.set_board_info_toml()

            flashed.append(updated)
        else:
            log.error(f"Failed to flash {mcu.board} on {mcu.serialport}")
    return flashed


def flash_mcu(
        mcu, 
        *, 
        fw_file: Path,
        erase: bool = False,
        bootloader: BootloaderMethod = BootloaderMethod.AUTO,
        method: FlashMethod = FlashMethod.AUTO,
        **kwargs
    ):
        """Flash a single MCU with the specified firmware."""
        
        # Determine the actual flash method to use
        flash_method = _select_flash_method(mcu, method, fw_file)
        
        log.debug(f"Using flash method: {flash_method.value} for {mcu.board_id}")
        
        try:
            if flash_method == FlashMethod.PYOCD:
                # PyOCD SWD/JTAG programming
                if not is_debug_programming_available():
                    raise MPFlashError("Debug probe programming not available. Install with: uv sync --extra pyocd")
                updated = flash_pyocd(mcu, fw_file=fw_file, erase=erase, **kwargs)
                
            elif flash_method == FlashMethod.UF2:
                # UF2 file copy method (RP2040, SAMD)
                if not enter_bootloader(mcu, bootloader):
                    raise MPFlashError(f"Failed to enter bootloader for {mcu.board} on {mcu.serialport}")
                updated = flash_uf2(mcu, fw_file=fw_file, erase=erase)
                
            elif flash_method == FlashMethod.DFU:
                # STM32 DFU method
                if not enter_bootloader(mcu, bootloader):
                    raise MPFlashError(f"Failed to enter bootloader for {mcu.board} on {mcu.serialport}")
                updated = flash_stm32(mcu, fw_file, erase=erase)
                
            elif flash_method == FlashMethod.ESPTOOL:
                # ESP32/ESP8266 esptool method (bootloader handled by esptool)
                updated = flash_esp(mcu, fw_file=fw_file, erase=erase, **kwargs)
                
            else:
                raise MPFlashError(f"Unsupported flash method: {flash_method.value}")
                
        except Exception as e:
            raise MPFlashError(f"Failed to flash {mcu.board} on {mcu.serialport}") from e
            
        return updated


def _select_flash_method(mcu, requested_method: FlashMethod, fw_file: Path) -> FlashMethod:
    """
    Select the appropriate flash method based on board type and user preference.
    
    Args:
        mcu: MPRemoteBoard instance
        requested_method: User-requested flash method
        fw_file: Firmware file path
        
    Returns:
        FlashMethod to use
        
    Raises:
        MPFlashError: If no suitable method available
    """
    # If user specified a specific method, validate and use it
    if requested_method != FlashMethod.AUTO:
        if requested_method == FlashMethod.PYOCD:
            if not is_debug_programming_available():
                raise MPFlashError("Debug probe programming not available. Install with: uv sync --extra pyocd")
            if not is_pyocd_supported_from_mcu(mcu):
                raise MPFlashError(f"pyOCD does not support {mcu.board_id} ({mcu.cpu})")
            return FlashMethod.PYOCD
            
        elif requested_method == FlashMethod.UF2:
            if mcu.port not in UF2_PORTS or fw_file.suffix != ".uf2":
                raise MPFlashError(f"UF2 method not suitable for {mcu.port} with {fw_file.suffix}")
            return FlashMethod.UF2
            
        elif requested_method == FlashMethod.DFU:
            if mcu.port != "stm32":
                raise MPFlashError(f"DFU method not suitable for {mcu.port}")
            return FlashMethod.DFU
            
        elif requested_method == FlashMethod.ESPTOOL:
            if mcu.port not in ["esp32", "esp8266"]:
                raise MPFlashError(f"esptool method not suitable for {mcu.port}")
            return FlashMethod.ESPTOOL
            
        elif requested_method == FlashMethod.SERIAL:
            # Use traditional serial-based methods
            return _select_serial_method(mcu, fw_file)
            
    # Auto-select the best method
    return _auto_select_flash_method(mcu, fw_file)


def _auto_select_flash_method(mcu, fw_file: Path) -> FlashMethod:
    """
    Automatically select the best flash method for a board.
    
    Priority order (maintains existing behavior as default):
    1. Platform-specific serial methods (UF2, DFU, esptool) - no extra hardware needed
    2. Fall back to serial bootloader methods
    
    Note: PyOCD is NOT included in auto-selection as it requires debug probe hardware.
    Use --method pyocd to explicitly enable SWD/JTAG programming.
    """
    
    # First priority: Platform-specific serial methods (existing behavior)
    if mcu.port in UF2_PORTS and fw_file.suffix == ".uf2":
        return FlashMethod.UF2
    elif mcu.port == "stm32":
        return FlashMethod.DFU
    elif mcu.port in ["esp32", "esp8266"]:
        return FlashMethod.ESPTOOL
    
    # Fall back to serial method selection
    return _select_serial_method(mcu, fw_file)


def _select_serial_method(mcu, fw_file: Path) -> FlashMethod:
    """Select appropriate serial-based flash method."""
    if mcu.port in UF2_PORTS and fw_file.suffix == ".uf2":
        return FlashMethod.UF2
    elif mcu.port == "stm32":
        return FlashMethod.DFU
    elif mcu.port in ["esp32", "esp8266"]:
        return FlashMethod.ESPTOOL
    else:
        raise MPFlashError(f"Don't know how to flash {mcu.port}-{mcu.board} on {mcu.serialport}")