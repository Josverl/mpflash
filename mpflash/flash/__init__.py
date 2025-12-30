from pathlib import Path

from loguru import logger as log
from mpflash.common import PORT_FWTYPES, UF2_PORTS, BootloaderMethod
from mpflash.config import config
from mpflash.errors import MPFlashError

from .esp import flash_esp
from .psoc6 import flash_psoc6
from .stm32 import flash_stm32
from .uf2 import flash_uf2
from .worklist import FlashTaskList

# #########################################################################################################


def flash_tasks(
    tasks: FlashTaskList,
    erase: bool,
    bootloader: BootloaderMethod,
    **kwargs,
):
    """Flash a list of FlashTask items directly."""
    flashed = []
    for task in tasks:
        mcu = task.board
        fw_info = task.firmware
        if not fw_info:
            log.error(f"Firmware not found for {mcu.board} on {mcu.serialport}, skipping")
            continue
        fw_file = config.firmware_folder / fw_info.firmware_file
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
            if fw_info.custom:
                mcu.get_board_info_toml()
                if fw_info.description:
                    mcu.toml["description"] = fw_info.description
                mcu.toml.setdefault("mpflash", {})
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
        **kwargs
    ):
        """Flash a single MCU with the specified firmware."""
        from mpflash.bootloader.activate import enter_bootloader
        
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
            elif mcu.port in ["psoc6"]:
                # PSoC6 flashing via OpenOCD - no separate bootloader activation needed
                updated = flash_psoc6(mcu, fw_file=fw_file, erase=erase)
            else:
                raise MPFlashError(f"Don't (yet) know how to flash {mcu.port}-{mcu.board} on {mcu.serialport}")
        except Exception as e:
            raise MPFlashError(f"Failed to flash {mcu.board} on {mcu.serialport}") from e
        return updated