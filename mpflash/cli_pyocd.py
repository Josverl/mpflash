"""
CLI commands for pyOCD debug probe management and information.
"""

import rich_click as click
from rich.console import Console
from rich.table import Table
from loguru import logger as log

from mpflash.cli_group import cli
from mpflash.errors import MPFlashError

try:
    from mpflash.flash.pyocd_flash import (
        list_pyocd_probes, 
        pyocd_info, 
    )
    from mpflash.flash.pyocd_core import (
        is_pyocd_available,
        get_pyocd_targets
    )
    PYOCD_AVAILABLE = True
except ImportError:
    PYOCD_AVAILABLE = False
    
def list_supported_targets():
    """Get supported targets for CLI display."""
    try:
        targets = get_pyocd_targets()
        return {name: info.get("part_number", name) for name, info in targets.items()}
    except Exception:
        return {}

console = Console()

@cli.command(
    "list-probes",
    short_help="List available pyOCD debug probes and their target information.",
)
@click.option(
    "--detect-targets/--no-detect-targets",
    default=True,
    show_default=True,
    help="Attempt to auto-detect target types connected to probes.",
)
def cli_list_probes(detect_targets: bool) -> int:
    """
    List all connected pyOCD debug probes with their capabilities.
    
    This command discovers debug probes (ST-Link, DAP-Link, etc.) that can be used
    for SWD/JTAG programming with the --method pyocd option.
    """
    if not PYOCD_AVAILABLE:
        log.error("pyOCD is not installed. Install with: uv add pyocd")
        return 1
        
    if not is_pyocd_available():
        log.error("pyOCD is installed but not functioning properly")
        return 1
    
    try:
        probes = list_pyocd_probes()
        
        if not probes:
            console.print("No pyOCD debug probes found.")
            console.print("\nMake sure your debug probe is connected and recognized by the system.")
            console.print("Common debug probes include ST-Link, DAP-Link, J-Link, etc.")
            return 1
            
        table = Table(title="Available PyOCD Debug Probes")
        table.add_column("Probe ID", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Vendor", style="blue")
        table.add_column("Product", style="blue") 
        table.add_column("Target Type", style="green")
        table.add_column("Status", style="yellow")
        
        for probe in probes:
            # Optionally detect target type
            target_type = "Unknown"
            status = "Connected"
            
            if detect_targets:
                try:
                    detected = probe.detect_target_type()
                    if detected:
                        target_type = detected
                        status = "Target Detected"
                    else:
                        status = "No Target"
                except Exception as e:
                    target_type = "Detection Failed"
                    status = f"Error: {str(e)[:30]}..."
            else:
                status = "Not Checked"
                
            table.add_row(
                probe.unique_id,
                probe.description,
                probe.vendor_name,
                probe.product_name,
                target_type,
                status
            )
        
        console.print(table)
        
        console.print(f"\n[green]Found {len(probes)} debug probe(s)[/green]")
        console.print("\nTo use a specific probe with mpflash:")
        console.print("  mpflash flash --method pyocd --probe-id <PROBE_ID>")
        console.print("\nTo flash with automatic probe selection:")
        console.print("  mpflash flash --method pyocd")
        
        return 0
        
    except Exception as e:
        log.error(f"Failed to list pyOCD probes: {e}")
        return 1

@cli.command(
    "pyocd-info",
    short_help="Show pyOCD installation and target support information.",
)
def cli_pyocd_info() -> int:
    """
    Display information about pyOCD installation, version, and supported targets.
    
    This command shows the current pyOCD status, available debug probes,
    and information about target support for SWD/JTAG programming.
    """
    info = pyocd_info() if PYOCD_AVAILABLE else {"available": False}
    
    # PyOCD Installation Status
    console.print("[bold blue]PyOCD Installation Status[/bold blue]")
    if info["available"]:
        console.print(f"✅ pyOCD is installed (version: {info.get('version', 'unknown')})")
    else:
        console.print("❌ pyOCD is not installed")
        console.print("   Install with: uv add pyocd")
        return 1
    
    # Debug Probes
    console.print(f"\n[bold blue]Connected Debug Probes[/bold blue]")
    probes = info.get("probes", [])
    if probes:
        for probe in probes:
            console.print(f"🔌 {probe['unique_id']}: {probe['description']}")
            if probe.get('target_type'):
                console.print(f"   Target: {probe['target_type']}")
    else:
        console.print("No debug probes found")
    
    # Supported Targets  
    console.print(f"\n[bold blue]Built-in Target Support[/bold blue]")
    if PYOCD_AVAILABLE:
        targets = list_supported_targets()
        console.print(f"📋 {len(targets)} board mappings available")
        
        # Group by target family
        stm32_boards = [bid for bid in targets.keys() if targets[bid].startswith("stm32")]
        rp2040_boards = [bid for bid in targets.keys() if targets[bid].startswith("rp20")]
        samd_boards = [bid for bid in targets.keys() if targets[bid].startswith("samd")]
        
        console.print(f"   STM32 boards: {len(stm32_boards)}")
        console.print(f"   RP2040 boards: {len(rp2040_boards)}")
        console.print(f"   SAMD boards: {len(samd_boards)}")
        
        console.print(f"\n[dim]Note: ESP32/ESP8266 not supported (use esptool instead)[/dim]")
    
    # Usage Examples
    console.print(f"\n[bold blue]Usage Examples[/bold blue]")
    console.print("Flash with pyOCD (auto-detect probe and target):")
    console.print("  mpflash flash --method pyocd")
    console.print("\nFlash with specific probe:")
    console.print("  mpflash flash --method pyocd --probe-id <PROBE_ID>")
    console.print("\nList available probes:")
    console.print("  mpflash list-probes")
    
    return 0

@cli.command(
    "pyocd-targets", 
    short_help="List supported pyOCD target mappings.",
)
@click.option(
    "--board-filter",
    "-b",
    help="Filter targets by board name (case-insensitive substring match)",
    metavar="PATTERN"
)
@click.option(
    "--target-filter", 
    "-t",
    help="Filter by pyOCD target type (case-insensitive substring match)",
    metavar="PATTERN"
)
def cli_pyocd_targets(board_filter: str, target_filter: str) -> int:
    """
    Display the mapping between MPFlash board IDs and pyOCD target types.
    
    This shows which boards can be programmed using pyOCD SWD/JTAG interface
    and what target type pyOCD will use for each board.
    """
    if not PYOCD_AVAILABLE:
        log.error("pyOCD is not installed. Install with: uv add pyocd")
        return 1
        
    try:
        targets = list_supported_targets()
        
        # Apply filters
        filtered_targets = targets
        if board_filter:
            filtered_targets = {
                board_id: target for board_id, target in targets.items()
                if board_filter.lower() in board_id.lower()
            }
        if target_filter:
            filtered_targets = {
                board_id: target for board_id, target in filtered_targets.items()
                if target_filter.lower() in target.lower()
            }
        
        if not filtered_targets:
            console.print("No targets match the specified filters.")
            return 1
            
        table = Table(title="PyOCD Target Mappings")
        table.add_column("Board ID", style="cyan", no_wrap=True)
        table.add_column("PyOCD Target", style="green", no_wrap=True)
        table.add_column("Family", style="blue")
        
        # Sort by board ID for consistent output
        for board_id in sorted(filtered_targets.keys()):
            target = filtered_targets[board_id]
            
            # Determine family
            if target.startswith("stm32"):
                family = "STM32"
            elif target.startswith("rp20"):
                family = "RP2040/RP2350"
            elif target.startswith("samd"):
                family = "SAMD"
            else:
                family = "Other"
                
            table.add_row(board_id, target, family)
        
        console.print(table)
        console.print(f"\n[green]Showing {len(filtered_targets)} of {len(targets)} supported targets[/green]")
        
        if board_filter or target_filter:
            console.print(f"\nFilters applied:")
            if board_filter:
                console.print(f"  Board: {board_filter}")
            if target_filter:
                console.print(f"  Target: {target_filter}")
        
        return 0
        
    except Exception as e:
        log.error(f"Failed to list pyOCD targets: {e}")
        return 1