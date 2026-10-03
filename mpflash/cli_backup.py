"""CLI command to back up connected MicroPython boards into a validated folder.

Each board gets its own timestamped bundle (``README.md``, ``manifest.json`` and
hashed artifacts). Only data that a registered provider can read is included;
unsupported requests fail explicitly.
"""

from pathlib import Path
from typing import List

import rich_click as click

from .cli_group import cli
from .logger import log


@cli.command(
    "backup",
    short_help="Back up connected MicroPython boards into a folder that `mpflash restore` can validate and restore.",
    hidden=True,  # No providers are registered yet; unhidden by mpflash-ckb.4
)
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    default=["*"],
    multiple=True,
    show_default=True,
    help="Which serial port(s) (or globs) to back up.",
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
    "--output",
    "-o",
    "output",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("mpflash-backups"),
    show_default=True,
    help="Folder in which a new timestamped backup folder is created for each board.",
    metavar="DIR",
)
@click.option(
    "--component",
    "-c",
    "components",
    type=click.Choice(["flash", "vfs", "romfs"]),
    multiple=True,
    help="Component(s) to back up. By default everything MPFlash can both read and restore on the board is included.",
)
@click.pass_context
def cli_backup_board(
    ctx: click.Context,
    serial: List[str],
    ignore: List[str],
    bluetooth: bool,
    output: Path,
    components: List[str],
) -> int:
    """Back up connected MicroPython boards into validated bundle folders."""
    from .backup.models import ComponentKind
    from .backup.service import plan_backup, run_backup
    from .connected import list_mcus
    from .errors import MPFlashError

    requested = [ComponentKind(name) for name in components]
    conn_mcus = [mcu for mcu in list_mcus(ignore=list(ignore), include=list(serial), bluetooth=bluetooth) if mcu.connected]
    # ignore boards that have the [mpflash] ignore flag set
    conn_mcus = [mcu for mcu in conn_mcus if not (mcu.toml.get("mpflash", {}).get("ignore", False))]
    if not conn_mcus:
        log.error("No connected MicroPython boards found to back up.")
        ctx.exit(1)

    created: List[Path] = []
    failed = 0
    for mcu in conn_mcus:
        try:
            plan = plan_backup(mcu, requested)
            for note in plan.notes:
                log.warning(note)
            created.append(run_backup(mcu, plan, output))
        except MPFlashError as error:
            failed += 1
            log.error(f"Backup of {mcu.board} on {mcu.serialport} failed: {error}")

    for folder in created:
        log.success(f"Backup created: {folder}")
    if created:
        log.warning("Backups can contain credentials and deleted data. Store them privately and do not share them.")
    ctx.exit(1 if failed or not created else 0)
