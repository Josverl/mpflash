import fnmatch
import glob
import os
import platform
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union

from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

# from mpflash.flash.esp import FlashMode
from .logger import log

PORT_FWTYPES = {
    "stm32": [".dfu"],  # need .dfu for pydfu.py - .hex for cube cli/GUI
    "esp32": [".bin"],
    "esp8266": [".bin"],
    "rp2": [".uf2"],
    "samd": [".uf2"],
    "psoc6": [".hex", ".elf", ".bin"],  # PSoC6 support via OpenOCD
    # below this not yet implemented / tested
    "mimxrt": [".hex"],
    "nrf": [".uf2"],
    "renesas-ra": [".hex"],
}

UF2_PORTS = [port for port, exts in PORT_FWTYPES.items() if ".uf2" in exts]
SA_PORTS = {"windows", "unix", "webassembly"}
"""Stand alone ports that  have no boards, just variants"""
@dataclass
class Params:
    """Common parameters for downloading and flashing firmware"""

    ports: List[str] = field(default_factory=list)
    boards: List[str] = field(default_factory=list)
    variant: str = ""
    versions: List[str] = field(default_factory=list)
    serial: List[str] = field(default_factory=list)
    ignore: List[str] = field(default_factory=list)
    bluetooth: bool = False
    force: bool = False


@dataclass
class DownloadParams(Params):
    """Parameters for downloading firmware"""

    clean: bool = False


class BootloaderMethod(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    MPY = "mpy"
    TOUCH_1200 = "touch1200"
    NONE = "none"


@dataclass
class FlashParams(Params):
    """Parameters for flashing a board"""

    erase: bool = True
    bootloader: BootloaderMethod = BootloaderMethod.NONE
    cpu: str = ""
    flash_mode: str = "keep"  # keep, qio, qout, dio, dout
    custom: bool = False

    def __post_init__(self):
        if isinstance(self.bootloader, str):
            self.bootloader = BootloaderMethod(self.bootloader)


ParamType = Union[DownloadParams, FlashParams]


def filtered_comports(
    ignore: Optional[List[str]] = None,
    include: Optional[List[str]] = None,
    bluetooth: bool = False,
) -> List[str]:
    """
    Get a list of filtered comports using the include and ignore lists.
    both can be globs (e.g. COM*) or exact port names (e.g. COM1)
    """
    return [p.device for p in filtered_portinfos(ignore, include, bluetooth)]


def filtered_portinfos(
    ignore: Optional[List[str]] = None,
    include: Optional[List[str]] = None,
    bluetooth: bool = False,
) -> List[ListPortInfo]:  # sourcery skip: assign-if-exp
    """
    Get a list of filtered comports using the include and ignore lists.
    both can be globs (e.g. COM*) or exact port names (e.g. COM1)
    """
    log.trace(f"filtered_portinfos: {ignore=}, {include=}, {bluetooth=}")
    if not ignore:
        ignore = []
    elif not isinstance(ignore, list):  # type: ignore
        ignore = list(ignore)
    if not include:
        include = ["*"]
    elif not isinstance(include, list):  # type: ignore
        include = list(include)

    if ignore == [] and platform.system() == "Darwin":
        # By default ignore some of the irrelevant ports on macOS
        ignore = [
            "/dev/*.debug-console",
        ]

    # remove ports that are to be ignored
    log.trace(f"{include=}, {ignore=}, {bluetooth=}")

    comports = [p for p in list_ports.comports() if not any(fnmatch.fnmatch(p.device, i) for i in ignore)]

    if platform.system() == "Linux":
        # use p.location to filter out the bogus ports on newer Linux kernels
        # filter out the bogus ports on newer Linux kernels
        comports = [p for p in comports if p.location]

    log.trace(f"comports: {[p.device for p in comports]}")
    # remove bluetooth ports

    if include != ["*"]:
        # if there are explicit ports to include, add them to the list
        explicit = [p for p in list_ports.comports() if any(fnmatch.fnmatch(p.device, i) for i in include)]
        log.trace(f"explicit: {[p.device for p in explicit]}")
        if ignore == []:
            # if nothing to ignore, just use the explicit list as a sinple sane default
            comports = explicit
        else:
            # if there are ports to ignore, add the explicit list to the filtered list
            comports = list(set(explicit) | set(comports))
    if platform.system() == "Darwin":
        # Failsafe: filter out debug-console ports
        comports = [p for p in comports if not p.description.endswith(".debug-console")]

    if not bluetooth:
        # filter out bluetooth ports
        comports = [p for p in comports if "bluetooth" not in p.description.lower()]
        comports = [p for p in comports if "BTHENUM" not in p.hwid]
        if platform.system() == "Darwin":
            comports = [p for p in comports if ".Bluetooth" not in p.device]
            # filter out ports with no hwid
            comports = [p for p in comports if p.hwid != "n/a"]
    log.debug(f"filtered_comports: {[p.device for p in comports]}")
    # sort
    if platform.system() == "Windows":
        # Windows sort of comports by number - but fallback to device name
        return sorted(
            comports,
            key=lambda x: int(x.device.split()[0][3:]) if x.device.split()[0][3:].isdigit() else x,
        )
    # sort by device name
    return sorted(comports, key=lambda x: x.device)


def find_serial_by_path(target_port: str):
    """Find the symbolic link path of a serial port by its device path."""
    # sourcery skip: use-next

    if platform.system() == "Windows":
        return None
    # List all available serial ports
    available_ports = list_ports.comports()
    # Filter to get the device path of the target port
    target_device_path = None
    for port in available_ports:
        if port.device == target_port:
            target_device_path = port.device
            break

    if not target_device_path:
        return None  # Target port not found among available ports

    # Search for all symbolic links in /dev/serial/by-path/
    for symlink in glob.glob("/dev/serial/by-path/*"):
        # Resolve the symbolic link to its target
        if os.path.realpath(symlink) == target_device_path:
            return symlink  # Return the matching symlink path

    return None  # Return None if no match is found
