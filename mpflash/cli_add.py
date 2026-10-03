"""CLI to add a custom MicroPython firmware."""

from pathlib import Path
from typing import Union

import rich_click as click
from loguru import logger as log

from mpflash.errors import MPFlashError

from .cli_group import cli


@cli.command(
    "add",
    help="Add a custom MicroPython firmware.",
)
@click.option(
    "--version",
    "-v",
    default="",
    help="Firmware version metadata. Inferred from the source checkout when omitted.",
    metavar="SEMVER",
)
@click.option(
    "--port",
    default="",
    help="MicroPython port metadata, for example nrf or rp2. Inferred from the path when omitted.",
    metavar="PORT",
)
@click.option(
    "--board",
    "board_id",
    default="",
    help="Board ID metadata. Inferred from the path when omitted.",
    metavar="BOARD_ID",
)
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
    board_id: str = "",
    port: str = "",
    version: str = "",
) -> int:
    """Add a custom MicroPython firmware from a local file."""
    from mpflash.custom import add_custom_firmware

    try:
        return add_custom_firmware(
            fw_path=Path(fw_path),
            force=force,
            description=description,
            board_id=board_id,
            port=port,
            version=version,
        )
    except MPFlashError as e:
        log.error(e)
        return 1
