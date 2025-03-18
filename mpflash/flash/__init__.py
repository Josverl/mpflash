from pathlib import Path

from loguru import logger as log

from mpflash.bootloader.activate import enter_bootloader
from mpflash.common import PORT_FWTYPES, BootloaderMethod, UF2_PORTS
from mpflash.errors import MPFlashError

from .esp import flash_esp
from .stm32 import flash_stm32
from .uf2 import flash_uf2
from .worklist import WorkList

# #########################################################################################################

def flash_list(
    todo: WorkList,
    fw_folder: Path,
    erase: bool,
    bootloader: BootloaderMethod,
    **kwargs
):  # sourcery skip: use-named-expression
    """Flash a list of boards with the specified firmware."""
    flashed = []
    for mcu, fw_info in todo:
        fw_file = fw_folder / fw_info.filename
        if not fw_file.exists():
            log.error(f"File {fw_file} does not exist, skipping {mcu.board} on {mcu.serialport}")
            continue

        log.info(f"Updating {mcu.board} on {mcu.serialport} to {fw_info.version}")
        try:
            updated = flash_mcu(mcu, fw_file=fw_file, erase=erase, bootloader=bootloader, **kwargs)
        except MPFlashError as e:
            log.error(f"Failed to flash {mcu.board} on {mcu.serialport}: {e}")
            continue
        if updated:
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
        **kwargs        
    ):
        """Flash a single MCU with the specified firmware."""
        updated = None
        try:
            if mcu.port in UF2_PORTS and fw_file.suffix == ".uf2":
                if not enter_bootloader(mcu, bootloader):
                    raise MPFlashError(f"Failed to enter bootloader for {mcu.board} on {mcu.serialport}")
                updated = flash_uf2(mcu, fw_file=fw_file, erase=erase)
            elif mcu.port in ["stm32"]:
                if not enter_bootloader(mcu, bootloader):
                    raise MPFlashError(f"Failed to enter bootloader for {mcu.board} on {mcu.serialport}")
                updated = flash_stm32(mcu, fw_file, erase=erase)
            elif mcu.port in ["esp32", "esp8266"]:
                #  bootloader is handled by esptool for esp32/esp8266
                updated = flash_esp(mcu, fw_file=fw_file, erase=erase, **kwargs)
            else:
                raise MPFlashError(f"Don't (yet) know how to flash {mcu.port}-{mcu.board} on {mcu.serialport}")
        except Exception as e:
            raise MPFlashError(f"Failed to flash {mcu.board} on {mcu.serialport}") from e
        return updated