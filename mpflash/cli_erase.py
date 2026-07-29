"""CLI command to erase the filesystem of connected MicroPython boards.

Reuses the ``--erase`` filesystem implementation: it runs the on-device erase
script via ``mpremote`` on each selected board, wiping the filesystem block
device and rebooting the board (``machine.reset()``) without flashing firmware.
"""

from typing import List

import rich_click as click

from .cli_group import cli
from .config import config
from .logger import log


@cli.command(
    "erase",
    short_help="Erase the filesystem of connected MicroPython boards and reboot (erases all files).",
)
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    default=["*"],
    multiple=True,
    show_default=True,
    help="Which serial port(s) (or globs) to erase.",
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
    help="""Do not ask for confirmation before erasing.""",
)
@click.pass_context
def cli_erase_board(
    ctx: click.Context,
    serial: List[str],
    ignore: List[str],
    bluetooth: bool,
    assume_yes: bool,
) -> int:
    """Erase the filesystem of connected MicroPython boards and reboot, without flashing firmware."""
    from rich.prompt import Confirm

    from .connected import list_mcus
    from .flash.builtins.uf2.erase import SUPPORTED_PORTS, erase_filesystem
    from .list import show_mcus

    serial = list(serial)
    ignore = list(ignore)

    conn_mcus = [mcu for mcu in list_mcus(ignore=ignore, include=serial, bluetooth=bluetooth) if mcu.connected]
    # ignore boards that have the [mpflash] ignore flag set
    conn_mcus = [mcu for mcu in conn_mcus if not (mcu.toml.get("mpflash", {}).get("ignore", False))]

    if not conn_mcus:
        log.error("No connected MicroPython boards found to erase.")
        ctx.exit(1)

    # Only boards on a port with a known filesystem block device can be erased.
    to_erase = [mcu for mcu in conn_mcus if mcu.port in SUPPORTED_PORTS]
    for mcu in conn_mcus:
        if mcu.port not in SUPPORTED_PORTS:
            log.warning(f"Skipping {mcu.board} on {mcu.serialport}: erase is not supported for port {mcu.port!r}")

    if not to_erase:
        log.error(f"None of the connected boards support erasing (supported: {', '.join(sorted(SUPPORTED_PORTS))}).")
        ctx.exit(1)

    show_mcus(to_erase, title="Boards to erase", refresh=False)

    if not assume_yes and config.interactive:
        if not Confirm.ask("Erasing wipes ALL files on the selected board(s) and reboots it. Continue?", default=False):
            log.info("Erase cancelled by user.")
            ctx.exit(2)

    erased = []
    for mcu in to_erase:
        if erase_filesystem(mcu):
            erased.append(mcu)
        else:
            log.error(f"Failed to erase {mcu.board} on {mcu.serialport}")

    if erased:
        log.info(f"Erased {len(erased)} board(s)")
        ctx.exit(0)
    log.error("No boards were erased")
    ctx.exit(1)
