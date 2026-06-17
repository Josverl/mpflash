import platform
from pathlib import Path
from typing import Optional

from loguru import logger as log
from mpflash.mpremoteboard import MPRemoteBoard

# Module-level cached backend for Windows libusb
_libusb_backend = None


def init_libusb_windows():
    """
    Initializes the libusb backend on Windows and caches it module-wide.

    Uses libusb_package_tng which embeds pre-built libusb binaries and supports
    Python 3.14+ without requiring per-release package updates.

    Returns:
        The usb backend object if successful, None otherwise.
    """
    global _libusb_backend
    if _libusb_backend is not None:
        return _libusb_backend

    import libusb_package_tng  # type: ignore
    import usb.backend.libusb1 as libusb1

    _libusb_backend = libusb1.get_backend(find_library=libusb_package_tng.find_library)
    if _libusb_backend is None:
        # Fall back to any OS-provided libusb
        log.warning("Could not find libusb via libusb-package-tng, falling back to system libusb")
        _libusb_backend = libusb1.get_backend()
    if _libusb_backend is None:
        raise RuntimeError("Could not find a usable libusb backend")
    return _libusb_backend


try:
    from ..vendor import pydfu as pydfu
except ImportError:
    pydfu = None


def dfu_init():
    """
    Initializes the DFU (Device Firmware Upgrade) process.

    Returns:
        The usb backend on Windows, or None on other platforms.
    """
    if not pydfu:
        log.error("pydfu not found")
        return None
    if platform.system() == "Windows":
        log.debug("Initializing libusb backend on Windows...")
        return init_libusb_windows()
    return None


def flash_stm32_dfu(
    mcu: MPRemoteBoard,
    fw_file: Path,
    *,
    erase: bool = True,
    address: int = 0x08000000,
) -> Optional[MPRemoteBoard]:
    """
    Flashes the STM32 microcontroller using DFU (Device Firmware Upgrade).

    Args:
        mcu (MPRemoteBoard): The remote board to flash.
        fw_file (Path): The path to the firmware file (.dfu or .bin).
        erase (bool, optional): Whether to erase the memory before flashing. Defaults to True.
        address (int, optional): Target memory address for .bin files. Defaults to 0x08000000.

    Returns:
        Optional[MPRemoteBoard]: The flashed remote board if successful, None otherwise.
    """
    log.info("Using pydfu to flash STM32 boards")

    if not pydfu:
        log.error("pydfu not found, please install it with 'pip install pydfu' if supported")
        return None

    if not fw_file.exists():
        log.error(f"File {fw_file} not found")
        return None

    if fw_file.suffix not in (".dfu", ".bin"):
        log.error(f"File {fw_file} is not a .dfu or .bin file")
        return None

    backend = dfu_init()
    kwargs = {"idVendor": 0x0483, "idProduct": 0xDF11}
    if backend is not None:
        kwargs["backend"] = backend

    log.debug("List SPECIFIED DFU devices...")
    try:
        pydfu.list_dfu_devices(**kwargs)
    except ValueError as e:
        log.error(f"Insuffient permissions to access usb DFU devices: {e}")
        return None
    except Exception as e:
        if "Operation not supported" not in str(e):
            raise
        log.debug(f"Skipping DFU device detail listing on this backend: {e}")

    # Needs to be a list of serial ports
    log.debug("Inititialize pydfu...")
    pydfu.init(**kwargs)

    if erase:
        log.info("Mass erase...")
        pydfu.mass_erase()

    if fw_file.suffix == ".bin":
        log.debug(f"Read .bin file at address 0x{address:08x}...")
        elements = pydfu.read_bin_file(fw_file, address)
    else:
        log.debug("Read DFU file...")
        elements = pydfu.read_dfu_file(fw_file)
    if not elements:
        log.error("No data in firmware file")
        return None
    log.info("Writing memory...")
    pydfu.write_elements(elements, False, progress=pydfu.cli_progress)

    log.debug("Exiting DFU...")
    pydfu.exit_dfu()
    log.success("Done flashing, resetting the board and wait for it to restart")
    return mcu
