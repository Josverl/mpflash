from typing import List

import rich_click as click
from loguru import logger as log

import mpflash.download.jid as jid
import mpflash.mpboard_id as mpboard_id
from mpflash.ask_input import ask_missing_params
from mpflash.cli_download import connected_ports_boards_variants
from mpflash.cli_group import cli
from mpflash.cli_list import show_mcus
from mpflash.common import BootloaderMethod, FlashMethod, FlashParams, filtered_comports
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
    "--method",
    "--flash-method",
    "flash_method",
    type=click.Choice([e.value for e in FlashMethod]),
    default="auto",
    show_default=True,
    help="""Flash programming method. 'auto' uses serial bootloader methods (existing behavior). Use 'pyocd' for SWD/JTAG programming via debug probe.""",
)
@click.option(
    "--probe",
    "--probe-id",  # Keep as alias for backwards compatibility
    "probe_id", 
    help="""Specific pyOCD probe ID to use (partial match). Required when multiple probes are connected.""",
    metavar="PROBE_ID",
)
@click.option(
    "--auto-install-packs/--no-auto-install-packs",
    default=True,
    help="""Automatically install CMSIS packs for missing pyOCD targets. Default: enabled.""",
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
    "--build",
    default=False,
    is_flag=True,
    help="""Build MicroPython firmware locally using mpbuild before flashing. Generates all formats (.dfu, .hex, .bin, .elf). Requires Docker.""",
)
@click.option(
    "--flash_mode",
    "--fm",
    type=click.Choice(["keep", "qio", "qout", "dio", "dout"]),
    default="keep",
    show_default=True,
    help="""Flash mode for ESP boards. (default: keep)""",
)
@click.option(
    "--custom",
    "-c",
    default=False,
    is_flag=True,
    show_default=True,
    help="""Flash a custom firmware""",
)
def cli_flash_board(**kwargs) -> int:
    # version to versions, board to boards
    kwargs["versions"] = [kwargs.pop("version")] if kwargs["version"] is not None else []
    if kwargs["board"] is None:
        kwargs["boards"] = []
        kwargs.pop("board")
    else:
        kwargs["boards"] = [kwargs.pop("board")]
        
    # Convert flash_method to method and convert to enum
    flash_method_str = kwargs.pop("flash_method", "auto")
    flash_method = FlashMethod(flash_method_str)
    
    # Extract pyOCD options
    probe_id = kwargs.pop("probe_id", None)
    auto_install_packs = kwargs.pop("auto_install_packs", True)
    
    # Extract build option
    build_firmware = kwargs.pop("build", False)

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
        # Use params.serial if specified, otherwise use params.ports
        include_ports = params.serial if params.serial != ["*"] else params.ports
        params.ports, params.boards, variants, all_boards = connected_ports_boards_variants(
            include=include_ports,
            ignore=params.ignore,
            bluetooth=params.bluetooth,
        )
        if variants and len(variants) >= 1:
            params.variant = variants[0]
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
    
    # Handle --build flag: build firmware locally before flashing
    if build_firmware:
        from mpflash.build import build_firmware as build_fw, is_build_available, get_build_unavailable_reason, import_firmware_to_database
        
        if not is_build_available():
            reason = get_build_unavailable_reason()
            log.error(f"Build functionality not available: {reason}")
            return 1
        
        # Build firmware for each requested board
        for board_id in params.boards:
            full_board_id = f"{board_id}-{params.variant}" if params.variant else board_id
            version = params.versions[0] if params.versions else "latest"
            
            try:
                log.info(f"Building firmware for {full_board_id} version {version}")
                firmware_files = build_fw(full_board_id, version, force=params.force)
                log.info(f"Build complete: {len(firmware_files)} files generated")
                
                # Import built firmware files into mpflash database
                if firmware_files:
                    imported_count = import_firmware_to_database(firmware_files, full_board_id, version)
                    log.info(f"Imported {imported_count} firmware files into database")
                else:
                    log.warning(f"No firmware files generated for {full_board_id}")
                    
            except Exception as e:
                log.error(f"Build failed for {full_board_id}: {e}")
                return 1
    
    worklist: WorkList = []

    if len(params.versions) == 1 and len(params.boards) == 1 and params.serial == ["*"]:
        # A one or more serial port including the board / variant
        comports = filtered_comports(
            ignore=params.ignore,
            include=params.serial,
            bluetooth=params.bluetooth,
        )
        board_id = f"{params.boards[0]}-{params.variant}" if params.variant else params.boards[0]
        log.info(f"Flashing {board_id} {params.versions[0]} to {len(comports)} serial ports")
        log.info(f"Target ports: {', '.join(comports)}")
        worklist = manual_worklist(
            comports,
            board_id=board_id,
            version=params.versions[0],
            custom=params.custom,
            method=flash_method,
        )
    # if serial port == auto and there are one or more specified/detected boards
    elif params.serial == ["*"] and params.boards:
        if not all_boards:
            log.trace("No boards detected yet, scanning for connected boards")
            _, _, _, all_boards = connected_ports_boards_variants(include=params.ports, ignore=params.ignore)
        # if variant id provided on the cmdline, treat is as an override
        if params.variant:
            for b in all_boards:
                b.variant = params.variant if (params.variant.lower() not in {"-", "none"}) else ""

        worklist = full_auto_worklist(
            all_boards=all_boards,
            version=params.versions[0],
            include=params.serial,
            ignore=params.ignore,
            method=flash_method,
        )
    elif params.versions[0] and params.boards[0] and params.serial:
        # A one or more serial port including the board / variant
        comports = filtered_comports(
            ignore=params.ignore,
            include=params.serial,
            bluetooth=params.bluetooth,
        )
        worklist = manual_worklist(
            comports,
            board_id=params.boards[0],
            version=params.versions[0],
            method=flash_method,
        )
    else:
        # just this serial port on auto
        worklist = single_auto_worklist(
            serial=params.serial[0],
            version=params.versions[0],
            method=flash_method,
        )
    if not params.custom:
        jid.ensure_firmware_downloaded(worklist, version=params.versions[0], force=params.force)
    if flashed := flash_list(
        worklist,
        params.erase,
        params.bootloader,
        method=flash_method,
        probe_id=probe_id,
        auto_install_packs=auto_install_packs,
        flash_mode=params.flash_mode,
    ):
        log.info(f"Flashed {len(flashed)} boards")
        show_mcus(flashed, title="Updated boards after flashing")
        return 0
    else:
        log.error("No boards were flashed")
        return 1
