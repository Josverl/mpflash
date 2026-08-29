"""Tests for the Intel HEX to UF2 conversion used for nrf boards."""

import struct
from pathlib import Path

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.uf2.hex2uf2 import (
    UF2_FAMILY_IDS,
    UF2_MAGIC_END,
    UF2_MAGIC_START0,
    UF2_MAGIC_START1,
    family_id,
    hex_to_uf2,
)

pytestmark = [pytest.mark.mpflash]

HEX_ADDRESS = 0x26000


@pytest.fixture
def hex_file(tmp_path: Path) -> Path:
    """Create a small Intel HEX file with 2 blocks of firmware data."""
    import bincopy

    binfile = bincopy.BinFile()
    binfile.add_binary(bytes(range(256)) * 2, address=HEX_ADDRESS)
    file = tmp_path / "FEATHER52-v1.26.0.hex"
    file.write_text(binfile.as_ihex())
    return file


def unpack_block(data: bytes, block_no: int):
    """Return the header fields of the requested UF2 block."""
    offset = block_no * 512
    return struct.unpack("<IIIIIIII", data[offset : offset + 32])


def test_hex_to_uf2_creates_valid_uf2(hex_file: Path):
    """Converted file has valid UF2 blocks with the addresses from the hex file."""
    uf2_file = hex_to_uf2(hex_file)

    assert uf2_file == hex_file.with_suffix(".uf2")
    data = uf2_file.read_bytes()
    assert len(data) == 2 * 512

    for block_no in range(2):
        start0, start1, flags, address, payload, no, total, family = unpack_block(data, block_no)
        assert (start0, start1) == (UF2_MAGIC_START0, UF2_MAGIC_START1)
        assert flags == 0x2000
        assert address == HEX_ADDRESS + block_no * 256
        assert payload == 256
        assert (no, total) == (block_no, 2)
        assert family == UF2_FAMILY_IDS["NRF52840"]
        end = struct.unpack("<I", data[block_no * 512 + 508 : block_no * 512 + 512])[0]
        assert end == UF2_MAGIC_END


def test_hex_to_uf2_output_and_family(hex_file: Path, tmp_path: Path):
    """The output file and the family id can be specified."""
    uf2_file = hex_to_uf2(hex_file, tmp_path / "firmware.uf2", family="NRF52833")

    assert uf2_file.exists()
    assert unpack_block(uf2_file.read_bytes(), 0)[7] == UF2_FAMILY_IDS["NRF52833"]


def test_hex_to_uf2_errors(tmp_path: Path):
    """Invalid input raises an MPFlashError."""
    with pytest.raises(MPFlashError):
        hex_to_uf2(tmp_path / "firmware.bin")

    empty = tmp_path / "empty.hex"
    empty.write_text(":00000001FF\n")
    with pytest.raises(MPFlashError):
        hex_to_uf2(empty)


@pytest.mark.parametrize(
    "family, port, expected",
    [
        ("NRF52840", "", UF2_FAMILY_IDS["NRF52840"]),
        ("nrf52", "", UF2_FAMILY_IDS["NRF52"]),
        ("0x621e937a", "", UF2_FAMILY_IDS["NRF52833"]),
        (0x1234, "", 0x1234),
        (None, "nrf", UF2_FAMILY_IDS["NRF52840"]),
    ],
)
def test_family_id(family, port, expected):
    """Family names, hex strings and numbers all resolve to a family id."""
    assert family_id(family, port) == expected


@pytest.mark.parametrize("family, port", [("SOMETHING", ""), (None, "rp2")])
def test_family_id_unknown(family, port):
    """Unknown families and ports without a default raise an MPFlashError."""
    with pytest.raises(MPFlashError):
        family_id(family, port)
