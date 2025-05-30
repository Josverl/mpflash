import json
import time
from typing import List

import rich_click as click
from rich import print

from .cli_group import cli
from .connected import list_mcus
from .list import show_mcus
from .logger import make_quiet


@cli.command(
    "list",
    help="List the connected MCU boards. alias: devs",
    aliases=["devs"],
)
@click.option(
    "--json",
    "-j",
    "as_json",
    is_flag=True,
    default=False,
    show_default=True,
    help="""Output in json format""",
)
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    default=["*"],
    multiple=True,
    show_default=True,
    help="Serial port(s) (or globs) to list. ",
    metavar="SERIALPORT",
)
@click.option(
    "--ignore",
    "-i",
    is_eager=True,
    help="Serial port(s) (or globs) to ignore. Defaults to MPFLASH_IGNORE.",
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
    "--progress/--no-progress",
    # "-p/-np", -p is already used for --port
    "progress",
    is_flag=True,
    default=True,
    show_default=True,
    help="""Show progress""",
)
def cli_list_mcus(serial: List[str], ignore: List[str], bluetooth: bool, as_json: bool, progress: bool = True) -> int:
    """List the connected MCU boards, and output in a nice table or json."""
    serial = list(serial)
    ignore = list(ignore)
    if as_json:
        # avoid noise in json output
        make_quiet()
    # TODO? Ask user to select a serialport if [?] is given ?

    conn_mcus = list_mcus(ignore=ignore, include=serial, bluetooth=bluetooth)
    # ignore boards that have the [mpflash] ignore flag set
    conn_mcus = [item for item in conn_mcus if not (item.toml.get("mpflash", {}).get("ignore", False))]
    if as_json:
        print(json.dumps([mcu.to_dict() for mcu in conn_mcus], indent=4))

    if progress:
        show_mcus(conn_mcus, refresh=False)
    for mcu in conn_mcus:
        # reset the board so it can continue to whatever it was running before
        if mcu.family == "circuitpython":
            # CircuitPython boards need a special reset command
            mcu.run_command(["exec", "--no-follow", "import microcontroller,time;time.sleep(0.01);microcontroller.reset()"], resume=False)
        else:
            mcu.run_command("reset")
    return 0 if conn_mcus else 1
