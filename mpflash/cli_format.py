"""CLI command to reformat the filesystem of connected MicroPython boards.

Runs the on-device format script via ``mpremote`` on each selected board,
recreating an empty filesystem of the same type without flashing new firmware.
"""

from typing import List

import rich_click as click

from .cli_group import cli
from .config import config
from .errors import MPFlashError
from .logger import log


@cli.command(
    "format",
    short_help="Reformat the filesystem of connected MicroPython boards (erases all files).",
)
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    default=["*"],
    multiple=True,
    show_default=True,
    help="Which serial port(s) (or globs) to format.",
    metavar="SERIALPORT",
)
@click.option(
    "--ignore",
    "-i",
    is_eager=True,
    help="Serial port(s) to ignore. Defaults to MPFLASH_IGNORE.",
    multiple=True,
    default=[],
    envvar="MPFLASH_IGNORE",
    show_default=True,
    metavar="SERIALPORT",
)
@click.option(
    "--bluetooth/--no-bluetooth",
    "--bt/--no-bt",
    is_flag=True,
    default=False,
    show_default=True,
    help="""Include bluetooth ports in the list""",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    show_default=True,
    help="""Do not ask for confirmation before formatting.""",
)
@click.pass_context
def cli_format_board(
    ctx: click.Context,
    serial: List[str],
    ignore: List[str],
    bluetooth: bool,
    assume_yes: bool,
) -> int:
    """Reformat the filesystem of connected MicroPython boards without flashing firmware."""
    from rich.prompt import Confirm

    from .connected import list_mcus
    from .flash.format_fs import SUPPORTED_FORMAT_PORTS, format_filesystem
    from .list import show_mcus

    serial = list(serial)
    ignore = list(ignore)

    conn_mcus = [mcu for mcu in list_mcus(ignore=ignore, include=serial, bluetooth=bluetooth) if mcu.connected]
    # ignore boards that have the [mpflash] ignore flag set
    conn_mcus = [mcu for mcu in conn_mcus if not (mcu.toml.get("mpflash", {}).get("ignore", False))]

    if not conn_mcus:
        log.error("No connected MicroPython boards found to format.")
        ctx.exit(1)

    # Only boards on a port with a known filesystem block device can be formatted.
    to_format = [mcu for mcu in conn_mcus if mcu.port in SUPPORTED_FORMAT_PORTS]
    for mcu in conn_mcus:
        if mcu.port not in SUPPORTED_FORMAT_PORTS:
            log.warning(f"Skipping {mcu.board} on {mcu.serialport}: format is not supported for port {mcu.port!r}")

    if not to_format:
        log.error(f"None of the connected boards support formatting (supported: {', '.join(sorted(SUPPORTED_FORMAT_PORTS))}).")
        ctx.exit(1)

    show_mcus(to_format, title="Boards to format", refresh=False)

    if not assume_yes and config.interactive:
        if not Confirm.ask("Formatting erases ALL files on the selected board(s). Continue?", default=False):
            log.info("Format cancelled by user.")
            ctx.exit(2)

    formatted = []
    for mcu in to_format:
        try:
            if format_filesystem(mcu):
                formatted.append(mcu)
        except MPFlashError as e:
            log.error(f"Failed to format {mcu.board} on {mcu.serialport}: {e}")

    if formatted:
        log.info(f"Formatted {len(formatted)} board(s)")
        ctx.exit(0)
    log.error("No boards were formatted")
    ctx.exit(1)
