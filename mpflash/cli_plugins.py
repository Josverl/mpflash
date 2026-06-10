"""``mpflash plugins`` — show the registered flash backends and their support matrix."""

from __future__ import annotations

import rich_click as click
from rich.console import Console
from rich.table import Table

from mpflash.cli_group import cli
from mpflash.flash.registry import get_backends
from mpflash.flash.services import default_services

_console = Console()


@cli.command(
    "plugins",
    short_help="List registered flash backends and their support matrix.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "plain"]),
    default="table",
    show_default=True,
)
def cli_plugins(fmt: str) -> int:
    """List every flash backend that mpflash currently knows about.

    Built-ins are always shown; third-party plugins discovered via the
    ``mpflash.flash_plugins`` entry-point group are listed alongside.
    """
    backends = get_backends()
    platform = default_services.current_platform()

    if fmt == "plain":
        for b in backends:
            avail = "yes" if b.is_available() else "no"
            click.echo(
                f"{b.name}\tports={sorted(b.supported_ports) or '*'}\t"
                f"formats={list(b.supported_formats)}\tpriority={b.priority}\t"
                f"available={avail}"
            )
        return 0

    table = Table(title=f"Flash backends ({platform.value})")
    table.add_column("Name", style="bold")
    table.add_column("Ports")
    table.add_column("Formats")
    table.add_column("Platforms")
    table.add_column("Prio", justify="right")
    table.add_column("Bootloader", justify="center")
    table.add_column("Available", justify="center")

    for b in backends:
        ports = ", ".join(sorted(b.supported_ports)) or "*"
        formats = ", ".join(b.supported_formats) or "*"
        platforms = ", ".join(sorted(p.value for p in b.supported_platforms))
        available = "yes" if b.is_available() else "no"
        boot = "yes" if b.requires_bootloader else "no"
        table.add_row(b.name, ports, formats, platforms, str(b.priority), boot, available)

    _console.print(table)
    return 0
