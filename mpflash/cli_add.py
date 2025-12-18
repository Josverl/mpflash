"""CLI to add a custom MicroPython firmware."""

from pathlib import Path
from typing import Union

import rich_click as click
from loguru import logger as log

from mpflash.errors import MPFlashError

from .cli_group import cli
from mpflash.custom import add_custom_firmware


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

    try:
        return add_custom_firmware(
            fw_path=Path(fw_path),
            force=force,
            description=description,
        )
    except MPFlashError as e:
        log.error(e)
        return 1


