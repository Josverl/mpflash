"""
The micropython git repo contains many 'board.json' files.

This is an example:
ports/stm32/boards/PYBV11/board.json

{
    "deploy": [
        "../PYBV10/deploy.md"
    ],
    "docs": "",
    "features": [],
    "images": [
        "PYBv1_1.jpg",
        "PYBv1_1-C.jpg",
        "PYBv1_1-E.jpg"
    ],
    "mcu": "stm32f4",
    "product": "Pyboard v1.1",
    "thumbnail": "",
    "url": "https://store.micropython.org/product/PYBv1.1",
    "variants": {
        "DP": "Double-precision float",
        "DP_THREAD": "Double precision float + Threads",
        "NETWORK": "Wiznet 5200 Driver",
        "THREAD": "Threading"
    },
    "vendor": "George Robotics"
}

This module implements `class Database` which reads all 'board.json' files and
provides a way to browse it's data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from glob import glob
from os import path
from pathlib import Path
import re


@dataclass(order=True)
class Variant:
    name: str
    """
    Example: "DP_THREAD"
    """
    text: str
    """
    Example: "Double precision float + Threads"
    """
    board: Board = field(repr=False)

    @property
    def description(self) -> str:
        """
        Description of the board, if available.
        Example: "Pyboard v1.1 with STM32F4"
        """
        return description_from_source(self.board.path, self.name) or self.board.description
        # f"{self.board.description}-{self.name}"


@dataclass(order=True)
class Board:
    name: str
    """
    Example: "PYBV11"
    """
    variants: list[Variant]
    """
    List of variants available for this board.
    Variants are sorted. May be an empty list if no variants are available.
    Example key: "DP_THREAD"
    """
    url: str
    """
    Primary URL to link to this board.
    """
    mcu: str
    """
    Example: "stm32f4"
    """
    product: str
    """
    Example: "Pyboard v1.1"
    """
    vendor: str
    """
    Example: "George Robotics"
    """
    images: list[str]
    """
    Images of this board, stored in the micropython-media repository.
    Example: ["PYBv1_1.jpg", "PYBv1_1-C.jpg", "PYBv1_1-E.jpg"]
    """
    deploy: list[str]
    """
    Files that explain how to deploy for this board:
    Example: ["../PYBV10/deploy.md"]
    """
    port: Port | None = field(default=None, compare=False)

    path: str = ""
    """
    the relative path to the boards files.
    Example: "ports/stm32/boards/PYBV11"
    """

    @staticmethod
    def factory(filename_json: Path) -> Board:
        with filename_json.open() as f:
            board_json = json.load(f)

        board = Board(
            name=filename_json.parent.name,
            variants=[],
            url=board_json["url"] if "url" in board_json else "",  # fix missing url
            mcu=board_json["mcu"],
            product=board_json["product"],
            vendor=board_json["vendor"],
            images=board_json["images"],
            deploy=board_json["deploy"],
            path=filename_json.parent.as_posix(),
        )
        board.variants.extend(
            sorted([Variant(*v, board) for v in board_json.get("variants", {}).items()])  # type: ignore
        )
        return board

    @property
    def description(self) -> str:
        """
        Description of the board, if available.
        Example: "Pyboard v1.1 with STM32F4"
        """
        return description_from_source(self.path, "") or self.name


@dataclass(order=True)
class Port:
    name: str
    """
    Example: "stm32"
    """
    boards: dict[str, Board] = field(default_factory=dict, repr=False)
    """
    Example key: "PYBV11"
    """


@dataclass
class Database:
    """
    This database contains all information retrieved from all 'board.json' files.
    """

    mpy_root_directory: Path = field(repr=False)
    port_filter: str = field(default="", repr=False)

    ports: dict[str, Port] = field(default_factory=dict)
    boards: dict[str, Board] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mpy_dir = self.mpy_root_directory
        if not mpy_dir.is_dir():
            raise ValueError(f"Invalid path to micropython directory: {mpy_dir}")
        # Take care to avoid using Path.glob! Performance was 15x slower.
        for p in glob(f"{mpy_dir}/ports/**/boards/**/board.json"):
            filename_json = Path(p)
            port_name = filename_json.parent.parent.parent.name
            if self.port_filter and self.port_filter != port_name:
                continue

            # Create a port
            port = self.ports.get(port_name, None)
            if port is None:
                port = Port(port_name)
                self.ports[port_name] = port

            # Load board.json and attach it to the board
            board = Board.factory(filename_json)
            board.port = port

            port.boards[board.name] = board
            self.boards[board.name] = board

        # Add 'special' ports, that don't have boards
        # TODO(mst) Tidy up later (variant descriptions etc)
        for special_port_name in ["unix", "webassembly", "windows"]:
            if self.port_filter and self.port_filter != special_port_name:
                continue
            path = Path(mpy_dir, "ports", special_port_name)
            variant_names = [var.name for var in path.glob("variants/*") if var.is_dir()]
            board = Board(
                special_port_name,
                [],
                f"https://github.com/micropython/micropython/blob/master/ports/{special_port_name}/README.md",
                "",
                "",
                "",
                [],
                [],
                path=path.as_posix(),
            )
            board.variants = [Variant(v, "", board) for v in variant_names]
            port = Port(special_port_name, {special_port_name: board})
            board.port = port

            self.ports[special_port_name] = port
            self.boards[board.name] = board


# look for all mpconfigboard.h files and extract the board name
# from the #define MICROPY_HW_BOARD_NAME "PYBD_SF6"
# and the #define MICROPY_HW_MCU_NAME "STM32F767xx"
RE_H_MICROPY_HW_BOARD_NAME = re.compile(r"#define\s+MICROPY_HW_BOARD_NAME\s+\"(.+)\"")
RE_H_MICROPY_HW_MCU_NAME = re.compile(r"#define\s+MICROPY_HW_MCU_NAME\s+\"(.+)\"")
# find boards and variants in the mpconfigboard*.cmake files
RE_CMAKE_MICROPY_HW_BOARD_NAME = re.compile(r"MICROPY_HW_BOARD_NAME\s?=\s?\"(?P<variant>[\w\s\S]*)\"")
RE_CMAKE_MICROPY_HW_MCU_NAME = re.compile(r"MICROPY_HW_MCU_NAME\s?=\s?\"(?P<variant>[\w\s\S]*)\"")


def description_from_source(board_path: str | Path, variant: str = "") -> str:
    """Get the board's description from the header or make files."""
    return description_from_header(board_path, variant) or description_from_cmake(board_path, variant)


def description_from_header(board_path: str | Path, variant: str = "") -> str:
    """Get the board's description from the mpconfigboard.h file."""

    mpconfig_path = path.join(board_path, f"mpconfigboard_{variant}.h" if variant else "mpconfigboard.h")
    if not path.exists(mpconfig_path):
        return f""

    with open(mpconfig_path, "r") as f:
        board_name = mcu_name = "-"
        found = 0
        for line in f:
            if match := RE_H_MICROPY_HW_BOARD_NAME.match(line):
                board_name = match[1]
                found += 1
            elif match := RE_H_MICROPY_HW_MCU_NAME.match(line):
                mcu_name = match[1]
                found += 1
            if found == 2:
                return f"{board_name} with {mcu_name}" if mcu_name != "-" else board_name
    return board_name if found == 1 else ""


def description_from_cmake(board_path: str | Path, variant: str = "") -> str:
    """Get the board's description from the mpconfig[board|variant].cmake file."""

    cmake_path = path.join(board_path, f"mpconfigvariant_{variant}.cmake" if variant else "mpconfigboard.cmake")
    if not path.exists(cmake_path):
        return f""
    with open(cmake_path, "r") as f:
        board_name = mcu_name = "-"
        for line in f:
            line = line.strip()
            if match := RE_CMAKE_MICROPY_HW_BOARD_NAME.match(line):
                description = match["variant"]
                return description
            elif match := RE_CMAKE_MICROPY_HW_MCU_NAME.match(line):
                description = match["variant"]
                return description
    return ""
