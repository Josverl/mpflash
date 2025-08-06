"""CLI to add a custom MicroPython firmware."""

from pathlib import Path
from typing import Union

import rich_click as click
from loguru import logger as log

from mpflash.connected import connected_ports_boards
from mpflash.custom import Firmware, add_firmware, custom_fw_from_path
from mpflash.downloaded import clean_downloaded_firmwares
from mpflash.errors import MPFlashError
from mpflash.mpboard_id import find_known_board
from mpflash.mpboard_id.alternate import add_renamed_boards
from mpflash.versions import clean_version

from .ask_input import ask_missing_params
from .cli_group import cli
from .config import config
from .download import download


@cli.command(
    "add",
    help="Add a custom MicroPython firmware.",
)
# @click.option(
#     "--version",
#     "-v",
#     "versions",
#     default=["stable"],
#     multiple=False,
#     show_default=True,
#     help="The version of MicroPython to to download.",
#     metavar="SEMVER, 'stable', 'preview' or '?'",
# )
@click.option(
    "--path",
    "-p",
    "fw_path",
    multiple=False,
    default="",
    show_default=False,
    help="a local path to the firmware file to add.",
    metavar="FIRMWARE_PATH",
)
@click.option(
    "--description",
    "-d",
    "description",
    default="",
    help="An Optional description for the firmware.",
    metavar="TXT",
)
# @click.option(
#     "--board",
#     "-b",
#     "boards",
#     multiple=True,
#     default=[],
#     show_default=True,
#     help="The board(s) to download the firmware for.",
#     metavar="BOARD_ID or ?",
# )
# @click.option(
#     "--serial",
#     "--serial-port",
#     "-s",
#     "serial",
#     default=["*"],
#     show_default=True,
#     multiple=True,
#     help="Which serial port(s) (or globs) to flash",
#     metavar="SERIALPORT",
# )
# @click.option(
#     "--ignore",
#     "-i",
#     is_eager=True,
#     help="Serial port(s) to ignore. Defaults to MPFLASH_IGNORE.",
#     multiple=True,
#     default=[],
#     envvar="MPFLASH_IGNORE",
#     show_default=True,
#     metavar="SERIALPORT",
# )
# @click.option(
#     "--clean/--no-clean",
#     default=True,
#     show_default=True,
#     help="""Remove dates and hashes from the downloaded firmware filenames.""",
# )
@click.option(
    "--force",
    "-f",
    default=False,
    is_flag=True,
    show_default=True,
    help="""Overwrite existing firmware.""",
)
def cli_add_custom(
    fw_path: Union[Path, str],
    force: bool = False,
    description: str = "",
) -> int:
    """Add a custom MicroPython firmware from a local file."""
    if not fw_path:
        log.error("No firmware path provided. Use --path to specify a firmware file.")
        return 1
    fw_path = Path(fw_path).expanduser().resolve()
    if not fw_path.exists():
        log.error(f"Firmware file does not exist: {fw_path}")
        return 1

    try:
        fw_dict = custom_fw_from_path(fw_path)
        if description:
            fw_dict["description"] = description
        if add_firmware(
            source=fw_path,
            fw_info=fw_dict,
            custom=True,
            force=force,
        ):
            log.success(f"Added custom firmware: {fw_dict['custom_id']} for {fw_dict['firmware_file']}")
            return 0
        else:
            return 1
    except MPFlashError as e:
        log.error(f"{e}")
        return 1
