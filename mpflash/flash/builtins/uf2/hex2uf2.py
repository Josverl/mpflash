"""Convert Intel HEX firmware to the UF2 format.

Some boards (mostly nrf) only publish a .hex firmware on micropython.org while
their bootloader expects a .uf2 file. As the .hex file contains the absolute
flash addresses, no per board base address is needed; only the UF2 family id of
the target MCU is required.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from mpflash.errors import MPFlashError
from mpflash.logger import log

UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID = 0x2000
UF2_PAYLOAD_SIZE = 256

# UF2 family ids, see https://github.com/microsoft/uf2/blob/master/utils/uf2families.json
UF2_FAMILY_IDS = {
    "NRF52": 0x1B57745F,
    "NRF52833": 0x621E937A,
    "NRF52840": 0xADA52840,
}

# Default family id per port; the nrf boards with a UF2 bootloader are all
# nRF52840 based, as the other nRF5x MCUs have no USB support.
PORT_FAMILY_IDS = {
    "nrf": UF2_FAMILY_IDS["NRF52840"],
}


def family_id(family: Union[str, int, None], port: str = "") -> int:
    """Resolve a family name, hex string or number to a UF2 family id.

    Args:
        family: Family name ('NRF52840'), a '0x...' string or an integer
        port: MicroPython port used to look up the default family id

    Returns:
        The numeric UF2 family id
    """
    if isinstance(family, int):
        return family
    if isinstance(family, str) and family:
        if family.upper() in UF2_FAMILY_IDS:
            return UF2_FAMILY_IDS[family.upper()]
        try:
            return int(family, 0)
        except ValueError as e:
            raise MPFlashError(f"Unknown UF2 family: {family}") from e
    if port in PORT_FAMILY_IDS:
        return PORT_FAMILY_IDS[port]
    raise MPFlashError(f"No default UF2 family id known for port: {port or '?'}")


def _uf2_block(address: int, data: bytes, block_no: int, num_blocks: int, familyid: int) -> bytes:
    """Build a single 512 byte UF2 block for the given payload."""
    header = struct.pack(
        "<IIIIIIII",
        UF2_MAGIC_START0,
        UF2_MAGIC_START1,
        UF2_FLAG_FAMILY_ID,
        address,
        UF2_PAYLOAD_SIZE,
        block_no,
        num_blocks,
        familyid,
    )
    payload = data.ljust(UF2_PAYLOAD_SIZE, b"\x00")[:UF2_PAYLOAD_SIZE]
    return header + payload.ljust(476, b"\x00") + struct.pack("<I", UF2_MAGIC_END)


def _hex_chunks(hex_file: Path) -> List[Tuple[int, bytes]]:
    """Read an Intel HEX file and return (address, data) pages of 256 bytes.

    Data from all segments is merged into 256-byte aligned pages, so that
    segments that share a page do not overwrite each other.
    """
    # Just in time import
    import bincopy

    binfile = bincopy.BinFile()
    try:
        binfile.add_ihex_file(str(hex_file))
    except Exception as e:
        raise MPFlashError(f"Could not read Intel HEX file {hex_file}: {e}") from e

    pages: Dict[int, bytearray] = {}
    for segment in binfile.segments:
        data = bytes(segment.data)
        pos = 0
        while pos < len(data):
            address = segment.address + pos
            page = address & ~(UF2_PAYLOAD_SIZE - 1)
            offset = address - page
            size = min(UF2_PAYLOAD_SIZE - offset, len(data) - pos)
            buffer = pages.setdefault(page, bytearray(b"\xff" * UF2_PAYLOAD_SIZE))
            buffer[offset : offset + size] = data[pos : pos + size]
            pos += size
    return [(page, bytes(pages[page])) for page in sorted(pages)]


def hex_to_uf2(
    hex_file: Path,
    uf2_file: Optional[Path] = None,
    family: Union[str, int, None] = None,
    port: str = "nrf",
) -> Path:
    """Convert an Intel HEX firmware file to a UF2 file.

    Args:
        hex_file: Path to the .hex firmware file
        uf2_file: Path of the .uf2 file to write, defaults to hex_file with a .uf2 suffix
        family: UF2 family name or id, defaults to the family id of the port
        port: MicroPython port, used to determine the default family id

    Returns:
        The path of the written .uf2 file

    Raises:
        MPFlashError: If the hex file cannot be read or contains no data
    """
    hex_file = Path(hex_file)
    if hex_file.suffix.lower() != ".hex":
        raise MPFlashError(f"Not an Intel HEX file: {hex_file}")
    uf2_file = Path(uf2_file) if uf2_file else hex_file.with_suffix(".uf2")
    familyid = family_id(family, port)

    chunks = _hex_chunks(hex_file)
    if not chunks:
        raise MPFlashError(f"No firmware data found in {hex_file}")

    blocks = bytearray()
    for block_no, (address, data) in enumerate(chunks):
        blocks += _uf2_block(address, data, block_no, len(chunks), familyid)
    try:
        uf2_file.write_bytes(bytes(blocks))
    except OSError as e:
        raise MPFlashError(f"Could not write UF2 file {uf2_file}: {e}") from e
    log.debug(f"Converted {hex_file.name} to {uf2_file.name} ({len(chunks)} blocks, family 0x{familyid:08X})")
    return uf2_file
