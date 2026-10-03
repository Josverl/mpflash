import struct
from pathlib import Path

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.nrf_dfu.artifacts import inspect_application_uf2, inspect_dfu_package
from mpflash.flash.builtins.nrf_dfu.profiles import get_profile, get_profiles, profile_package_path


def _uf2_block(
    *,
    target: int,
    block_no: int,
    num_blocks: int,
    family_id: int = 0xADA52840,
    payload_size: int = 256,
    flags: int = 0x00002000,
) -> bytes:
    block = bytearray(512)
    struct.pack_into(
        "<8I",
        block,
        0,
        0x0A324655,
        0x9E5D5157,
        flags,
        target,
        payload_size,
        block_no,
        num_blocks,
        family_id,
    )
    block[32 : 32 + min(payload_size, 476)] = bytes([block_no]) * min(payload_size, 476)
    struct.pack_into("<I", block, 508, 0x0AB16F30)
    return bytes(block)


def test_packaged_profiles_have_valid_pinned_dfu_packages():
    assert set(get_profiles()) == {"s140-6.1.1", "s140-7.3.0"}

    for profile in get_profiles().values():
        with profile_package_path(profile) as path:
            package = inspect_dfu_package(path, profile)

        assert package.sha256 == profile.sha256
        assert package.sd_size == profile.dfu.sd_size
        assert package.bl_size == profile.dfu.bl_size
        assert profile.source_bootloader_versions


def test_get_profile_rejects_unknown_name():
    with pytest.raises(MPFlashError, match="Unknown nRF SoftDevice profile"):
        get_profile("s140-latest")


def test_inspect_application_uf2_accepts_matching_layout(tmp_path: Path):
    profile = get_profile("s140-7.3.0")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(target=profile.application_start, block_no=0, num_blocks=2)
        + _uf2_block(target=profile.application_start + 256, block_no=1, num_blocks=2)
    )

    inspected = inspect_application_uf2(firmware, profile)

    assert inspected.first_address == 0x27000
    assert inspected.end_address == 0x27200
    assert inspected.block_count == 2


def test_inspect_application_uf2_rejects_wrong_softdevice_layout(tmp_path: Path):
    profile = get_profile("s140-7.3.0")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(_uf2_block(target=0x26000, block_no=0, num_blocks=1))

    with pytest.raises(MPFlashError, match="outside the s140-7.3.0 application range"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_wrong_family(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(
            target=profile.application_start,
            block_no=0,
            num_blocks=1,
            family_id=0xD663823C,
        )
    )

    with pytest.raises(MPFlashError, match="UF2 family"):
        inspect_application_uf2(firmware, profile)


@pytest.mark.parametrize("flags", [0, 0x00002001, 0x00006000])
def test_inspect_application_uf2_rejects_unsupported_flags(tmp_path: Path, flags: int):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(
            target=profile.application_start,
            block_no=0,
            num_blocks=1,
            flags=flags,
        )
    )

    with pytest.raises(MPFlashError, match="unsupported UF2 flags"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_overlapping_target_ranges(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(target=profile.application_start, block_no=0, num_blocks=2)
        + _uf2_block(target=profile.application_start + 128, block_no=1, num_blocks=2)
    )

    with pytest.raises(MPFlashError, match="overlapping UF2 target ranges"):
        inspect_application_uf2(firmware, profile)


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (0, 0, "invalid UF2 magic"),
        (508, 0, "invalid UF2 end magic"),
    ],
)
def test_inspect_application_uf2_rejects_invalid_magic(tmp_path: Path, offset: int, value: int, message: str):
    profile = get_profile("s140-6.1.1")
    block = bytearray(_uf2_block(target=profile.application_start, block_no=0, num_blocks=1))
    struct.pack_into("<I", block, offset, value)
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(block)

    with pytest.raises(MPFlashError, match=message):
        inspect_application_uf2(firmware, profile)


@pytest.mark.parametrize("payload_size", [0, 477])
def test_inspect_application_uf2_rejects_invalid_payload_size(tmp_path: Path, payload_size: int):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(
            target=profile.application_start,
            block_no=0,
            num_blocks=1,
            payload_size=payload_size,
        )
    )

    with pytest.raises(MPFlashError, match="invalid UF2 payload size"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_range_crossing_application_end(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(
            target=profile.application_end - 128,
            block_no=0,
            num_blocks=1,
        )
    )

    with pytest.raises(MPFlashError, match="outside the s140-6.1.1 application range"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_inconsistent_declared_counts(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(target=profile.application_start, block_no=0, num_blocks=2)
        + _uf2_block(target=profile.application_start + 256, block_no=1, num_blocks=3)
    )

    with pytest.raises(MPFlashError, match="inconsistent UF2 block counts"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_duplicate_block_numbers(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(target=profile.application_start, block_no=0, num_blocks=2)
        + _uf2_block(target=profile.application_start + 256, block_no=0, num_blocks=2)
    )

    with pytest.raises(MPFlashError, match="repeats UF2 block 0"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_missing_declared_block(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(_uf2_block(target=profile.application_start, block_no=0, num_blocks=2))

    with pytest.raises(MPFlashError, match="declares 2 UF2 blocks but contains 1"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_rejects_out_of_range_block_number(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(
        _uf2_block(target=profile.application_start, block_no=0, num_blocks=2)
        + _uf2_block(target=profile.application_start + 256, block_no=2, num_blocks=2)
    )

    with pytest.raises(MPFlashError, match="missing or out-of-range UF2 block numbers"):
        inspect_application_uf2(firmware, profile)


def test_inspect_application_uf2_requires_exact_application_start(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(_uf2_block(target=profile.application_start + 256, block_no=0, num_blocks=1))

    with pytest.raises(MPFlashError, match="expected 0x00026000"):
        inspect_application_uf2(firmware, profile)


def test_inspect_dfu_package_rejects_modified_blob(tmp_path: Path):
    profile = get_profile("s140-6.1.1")
    package = tmp_path / profile.package
    with profile_package_path(profile) as packaged:
        package.write_bytes(packaged.read_bytes() + b"changed")

    with pytest.raises(MPFlashError, match="size"):
        inspect_dfu_package(package, profile)
