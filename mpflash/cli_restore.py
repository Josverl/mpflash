"""CLI command to restore a backup bundle onto exactly one connected board.

Restore is destructive. It verifies the bundle, checks the target board and asks
every provider to describe its writes before anything is changed; ``--dry-run``
stops after that validation.
"""

from pathlib import Path
from typing import List

import rich_click as click

from .cli_group import cli
from .config import config
from .logger import log


@cli.command(
    "restore",
    short_help="Restore a backup folder created by `mpflash backup` onto one connected board (overwrites data).",
)
@click.argument("bundle", type=click.Path(exists=True, file_okay=False, path_type=Path), metavar="BACKUP_FOLDER")
@click.option(
    "--serial",
    "--serial-port",
    "-s",
    "serial",
    required=True,
    help="Serial port of the single board to restore. Wildcards are not accepted.",
    metavar="SERIALPORT",
)
@click.option(
    "--component",
    "-c",
    "components",
    type=click.Choice(["flash", "vfs", "romfs"]),
    multiple=True,
    help="Component(s) to restore. By default everything in the backup that this board supports is restored.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Validate the backup and the board and show what would be written, without changing anything.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    show_default=True,
    help="""Do not ask for confirmation before overwriting the board.""",
)
@click.option(
    "--bluetooth/--no-bluetooth",
    "--bt/--no-bt",
    is_flag=True,
    default=False,
    show_default=True,
    help="""Include bluetooth ports in the list""",
)
@click.pass_context
def cli_restore_board(
    ctx: click.Context,
    bundle: Path,
    serial: str,
    components: List[str],
    dry_run: bool,
    assume_yes: bool,
    bluetooth: bool,
) -> int:
    """Restore a backup onto one board after verifying the backup and the board."""
    from rich.prompt import Confirm

    from .backup.bundle import read_bundle
    from .backup.models import ComponentKind
    from .backup.service import plan_restore, run_restore
    from .connected import list_mcus
    from .errors import MPFlashError

    if any(char in serial for char in "*?[]"):
        raise click.UsageError("--serial must name exactly one serial port; wildcards are not accepted for restore.")

    conn_mcus = [mcu for mcu in list_mcus(ignore=[], include=[serial], bluetooth=bluetooth) if mcu.connected]
    if len(conn_mcus) != 1:
        log.error(f"Expected exactly one responsive board on {serial}, found {len(conn_mcus)}.")
        ctx.exit(1)
    mcu = conn_mcus[0]

    try:
        plan = plan_restore(read_bundle(bundle), mcu, [ComponentKind(name) for name in components])
    except MPFlashError as error:
        log.error(f"Cannot restore {bundle}: {error}")
        ctx.exit(1)

    click.echo(f"Restore {bundle} to {mcu.board} on {mcu.serialport}:")
    for line in plan.lines:
        click.echo(f"  {line}")
    for warning in plan.warnings:
        log.warning(warning)
    if dry_run:
        log.info("Dry run: nothing was changed.")
        ctx.exit(0)

    if not assume_yes:
        if not config.interactive:
            raise click.UsageError("Restore overwrites the board; pass --yes when running non-interactively.")
        if not Confirm.ask("This overwrites the selected data on the board. Continue?", default=False):
            log.info("Restore cancelled by user.")
            ctx.exit(2)

    try:
        restored = run_restore(plan, mcu)
    except MPFlashError as error:
        log.error(str(error))
        ctx.exit(1)
    log.success(f"Restored {', '.join(kind.value for kind in restored)} to {mcu.serialport}")
    ctx.exit(0)
