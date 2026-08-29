"""Convert Intel HEX firmware to the UF2 format.

Some boards (mostly nrf) only publish a .hex firmware on micropython.org while
their bootloader expects a .uf2 file. The conversion itself is done by the
vendored ``uf2conv`` module from the MicroPython repo (the Microsoft UF2
reference implementation); this module only resolves the UF2 family id and
handles the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from mpflash.errors import MPFlashError
from mpflash.logger import log

# Default UF2 family (short name from uf2families.json) per port.
# The nRF5x MCUs with a UF2 bootloader are all nRF52840 based,
# as the other nRF5x MCUs have no USB support.
PORT_FAMILIES = {
    "nrf": "NRF52840",
}


def family_id(family: Union[str, int, None], port: str = "") -> int:
    """Resolve a family name, hex string or number to a UF2 family id.

    Args:
        family: Family short name ('NRF52840'), a '0x...' string or an integer
        port: MicroPython port used to look up the default family

    Returns:
        The numeric UF2 family id
    """
    # Just in time import
    from mpflash.vendor import uf2conv

    if isinstance(family, int):
        return family
    if not family:
        if port not in PORT_FAMILIES:
            raise MPFlashError(f"No default UF2 family known for port: {port or '?'}")
        family = PORT_FAMILIES[port]
    families = uf2conv.load_families()
    if family.upper() in families:
        return families[family.upper()]
    try:
        return int(family, 0)
    except ValueError as e:
        raise MPFlashError(f"Unknown UF2 family: {family}") from e


def hex_to_uf2(
    hex_file: Path,
    uf2_file: Optional[Path] = None,
    family: Union[str, int, None] = None,
    port: str = "nrf",
) -> Path:
    """Convert an Intel HEX firmware file to a UF2 file.

    The flash addresses are read from the hex records, so no per board base
    address is needed.

    Args:
        hex_file: Path to the .hex firmware file
        uf2_file: Path of the .uf2 file to write, defaults to hex_file with a .uf2 suffix
        family: UF2 family short name or id, defaults to the family of the port
        port: MicroPython port, used to determine the default family

    Returns:
        The path of the written .uf2 file

    Raises:
        MPFlashError: If the hex file is invalid or the uf2 file cannot be written
    """
    # Just in time import
    from mpflash.vendor import uf2conv

    hex_file = Path(hex_file)
    if hex_file.suffix.lower() != ".hex":
        raise MPFlashError(f"Not an Intel HEX file: {hex_file}")
    uf2_file = Path(uf2_file) if uf2_file else hex_file.with_suffix(".uf2")

    familyid = family_id(family, port)
    try:
        hex_data = hex_file.read_bytes()
    except OSError as e:
        raise MPFlashError(f"Could not read Intel HEX file {hex_file}: {e}") from e
    if not uf2conv.is_hex(hex_data):
        raise MPFlashError(f"Not a valid Intel HEX file: {hex_file}")

    uf2conv.familyid = familyid
    try:
        uf2_data = uf2conv.convert_from_hex_to_uf2(hex_data.decode("utf-8"))
    except (ValueError, IndexError) as e:
        raise MPFlashError(f"Could not convert {hex_file} to UF2: {e}") from e
    if not uf2_data:
        raise MPFlashError(f"No firmware data found in {hex_file}")

    try:
        uf2_file.write_bytes(uf2_data)
    except OSError as e:
        raise MPFlashError(f"Could not write UF2 file {uf2_file}: {e}") from e
    log.debug(f"Converted {hex_file.name} to {uf2_file.name} (family 0x{familyid:08X})")
    return uf2_file
