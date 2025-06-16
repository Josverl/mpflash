from typing import List

import rich_click as click
from loguru import logger as log

import mpflash.download.jid as jid
import mpflash.mpboard_id as mpboard_id
from mpflash.ask_input import ask_missing_params
from mpflash.cli_download import connected_ports_boards
from mpflash.cli_group import cli
from mpflash.cli_list import show_mcus
from mpflash.common import BootloaderMethod, FlashParams, filtered_comports
from mpflash.errors import MPFlashError
from mpflash.flash import flash_list
from mpflash.flash.worklist import WorkList, full_auto_worklist, manual_worklist, single_auto_worklist
from mpflash.mpremoteboard import MPRemoteBoard
from mpflash.versions import clean_version

# #########################################################################################################
# CLI
# #########################################################################################################


@cli.command(
    "flash",
    short_help="Flash one or all connected MicroPython boards with a specific firmware and version.",
)
@click.option(
    "--version",
    "-v",
    "version",  # single version
    default="stable",
    multiple=False,
    show_default=True,
    help="The version of MicroPython to flash.",
    metavar="SEMVER, 'stable', 'preview' or '?'",
)
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    default=["*"],
    multiple=True,
    show_default=True,
    help="Which serial port(s) (or globs) to flash",
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
    "--port",
    "-p",
    "ports",
    help="The MicroPython port to flash",
    metavar="PORT",
    default=[],
    multiple=True,
)
@click.option(
    "--board",
    "-b",
    "board",  # single board
    multiple=False,
    help="The MicroPython board ID to flash. If not specified will try to read the BOARD_ID from the connected MCU.",
    metavar="BOARD_ID or ?",
)
@click.option(
    "--variant",
    "--var",
    "variant",  # single board
    multiple=False,
    help="The board VARIANT to flash or '-'. If not specified will try to read the variant from the connected MCU.",
    metavar="VARIANT",
)
@click.option(
    "--cpu",
    "--chip",
    "-c",
    "cpu",
    help="The CPU type to flash. If not specified will try to read the CPU from the connected MCU.",
    metavar="CPU",
)
@click.option(
    "--erase/--no-erase",
    default=False,
    show_default=True,
    help="""Erase flash before writing new firmware.""",
)
@click.option(
    "--bootloader",
    "--bl",
    "bootloader",
    type=click.Choice([e.value for e in BootloaderMethod]),
    default="auto",
    show_default=True,
    help="""How to enter the (MicroPython) bootloader before flashing.""",
)
@click.option(
    "--force",
    "-f",
    default=False,
    is_flag=True,
    show_default=True,
    help="""Force download of firmware even if it already exists.""",
)
@click.option(
    "--flash_mode",
    "--fm",
    type=click.Choice(["keep", "qio", "qout", "dio", "dout"]),
    default="keep",
    show_default=True,
    help="""Flash mode for ESP boards. (default: keep)""",
)
def cli_flash_board(**kwargs) -> int:
    # version to versions, board to boards
    kwargs["versions"] = [kwargs.pop("version")] if kwargs["version"] is not None else []
    if kwargs["board"] is None:
        kwargs["boards"] = []
        kwargs.pop("board")
    else:
        kwargs["boards"] = [kwargs.pop("board")]

    params = FlashParams(**kwargs)
    params.versions = list(params.versions)
    params.ports = list(params.ports)
    params.boards = list(params.boards)
    params.serial = list(params.serial)
    params.ignore = list(params.ignore)
    params.bootloader = BootloaderMethod(params.bootloader)

    # make it simple for the user to flash one board by asking for the serial port if not specified
    if params.boards == ["?"] or params.serial == "?":
        params.serial = ["?"]
        if params.boards == ["*"]:
            # No bard specified
            params.boards = ["?"]

    # Detect connected boards if not specified,
    # and ask for input if boards cannot be detected
    all_boards: List[MPRemoteBoard] = []
    if not params.boards:
        # nothing specified - detect connected boards
        params.ports, params.boards, all_boards = connected_ports_boards(
            include=params.ports, ignore=params.ignore, bluetooth=params.bluetooth
        )
        if params.boards == []:
            # No MicroPython boards detected, but it could be unflashed or in bootloader mode
            # Ask for serial port and board_id to flash
            params.serial = ["?"]
            params.boards = ["?"]
            # assume manual mode if no board is detected
            params.bootloader = BootloaderMethod("manual")
    else:
        mpboard_id.resolve_board_ids(params)

    # Ask for missing input if needed
    params = ask_missing_params(params)
    if not params:  # Cancelled by user
        return 2
    assert isinstance(params, FlashParams)

    if len(params.versions) > 1:
        log.error(f"Only one version can be flashed at a time, not {params.versions}")
        raise MPFlashError("Only one version can be flashed at a time")

    params.versions = [clean_version(v) for v in params.versions]
    worklist: WorkList = []

    if len(params.versions) == 1 and len(params.boards) == 1 and params.serial == ["*"]:
        # A one or more serial port including the board / variant
        comports = filtered_comports(
            ignore=params.ignore,
            include=params.ports,
            bluetooth=params.bluetooth,
        )
        board_id = f"{params.boards[0]}-{params.variant}" if params.variant else params.boards[0]
        log.info(f"Flashing {board_id} {params.versions[0]} to {len(comports)} serial ports")
        log.info(f"Target ports: {', '.join(comports)}")
        worklist = manual_worklist(
            comports,
            board_id=board_id,
            version=params.versions[0],
        )
    # if serial port == auto and there are one or more specified/detected boards
    elif params.serial == ["*"] and params.boards:
        if not all_boards:
            log.trace("No boards detected yet, scanning for connected boards")
            _, _, all_boards = connected_ports_boards(include=params.ports, ignore=params.ignore)
        # if variant id provided on the cmdline, treat is as an override
        if params.variant:
            for b in all_boards:
                b.variant = params.variant if (params.variant.lower() not in {"-", "none"}) else ""

        worklist = full_auto_worklist(
            all_boards=all_boards,
            version=params.versions[0],
            include=params.serial,
            ignore=params.ignore,
        )
    elif params.versions[0] and params.boards[0] and params.serial:
        # A one or more serial port including the board / variant
        comports = filtered_comports(
            ignore=params.ignore,
            include=params.ports,
            bluetooth=params.bluetooth,
        )
        worklist = manual_worklist(
            comports,
            board_id=params.boards[0],
            version=params.versions[0],
        )
    else:
        # just this serial port on auto
        worklist = single_auto_worklist(
            serial=params.serial[0],
            version=params.versions[0],
        )
    jid.ensure_firmware_downloaded(worklist, version=params.versions[0], force=params.force)
    if flashed := flash_list(
        worklist,
        params.erase,
        params.bootloader,
        flash_mode=params.flash_mode,
    ):
        log.info(f"Flashed {len(flashed)} boards")
        show_mcus(flashed, title="Updated boards after flashing")
        return 0
    else:
        log.error("No boards were flashed")
        return 1


