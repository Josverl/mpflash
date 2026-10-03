"""Validation for curated Nordic DFU ZIPs and matching application UF2 files."""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from mpflash.errors import MPFlashError

from .profiles import NrfDfuProfile

_UF2_MAGIC_START0 = 0x0A324655
_UF2_MAGIC_START1 = 0x9E5D5157
_UF2_MAGIC_END = 0x0AB16F30
_UF2_FLAG_FAMILY_ID = 0x00002000
_UF2_BLOCK_SIZE = 512
_UF2_DATA_OFFSET = 32
_UF2_MAX_PAYLOAD = 476


@dataclass(frozen=True)
class DfuPackage:
    """Validated metadata from a legacy Nordic DFU package."""

    path: Path
    sha256: str
    size: int
    sd_size: int
    bl_size: int


@dataclass(frozen=True)
class ApplicationUf2:
    """Validated address and family information from an application UF2."""

    path: Path
    family_id: int
    first_address: int
    end_address: int
    block_count: int


def _expect_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise MPFlashError(f"DFU package manifest field {key!r} is missing or invalid")
    return value


def inspect_dfu_package(path: Path, profile: NrfDfuProfile) -> DfuPackage:
    """Validate a DFU ZIP against its pinned profile."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MPFlashError(f"Could not read nRF DFU package {path}: {exc}") from exc

    digest = hashlib.sha256(data).hexdigest()
    if len(data) != profile.package_size:
        raise MPFlashError(f"nRF DFU package {path.name} has size {len(data)}, expected {profile.package_size}; refusing to flash")
    if digest.casefold() != profile.sha256.casefold():
        raise MPFlashError(f"nRF DFU package {path.name} failed SHA-256 verification; refusing to flash")

    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
            expected_names = {"manifest.json", "sd_bl.dat", "sd_bl.bin"}
            if names != expected_names:
                raise MPFlashError(f"nRF DFU package {path.name} contains unexpected files: {sorted(names)}")
            manifest = json.loads(package.read("manifest.json"))
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise MPFlashError(f"Invalid nRF DFU package {path.name}: {exc}") from exc

    if not isinstance(manifest, dict) or not isinstance(manifest.get("manifest"), dict):
        raise MPFlashError(f"DFU package {path.name} has no manifest object")
    root = manifest["manifest"]
    assert isinstance(root, dict)
    if root.get("dfu_version") != profile.dfu.dfu_version:
        raise MPFlashError(f"DFU package {path.name} has an unexpected DFU version")
    entry = root.get("softdevice_bootloader")
    if not isinstance(entry, dict):
        raise MPFlashError(f"DFU package {path.name} is not a SoftDevice+bootloader package")
    if entry.get("bin_file") != "sd_bl.bin" or entry.get("dat_file") != "sd_bl.dat":
        raise MPFlashError(f"DFU package {path.name} has unexpected payload names")

    init_data = entry.get("init_packet_data")
    if not isinstance(init_data, dict):
        raise MPFlashError(f"DFU package {path.name} has no init packet metadata")
    softdevice_req = init_data.get("softdevice_req")
    if softdevice_req != list(profile.dfu.softdevice_req):
        raise MPFlashError(f"DFU package {path.name} has unexpected SoftDevice requirements")

    expected = {
        "device_type": profile.dfu.device_type,
        "device_revision": profile.dfu.device_revision,
    }
    for key, value in expected.items():
        if _expect_int(init_data, key) != value:
            raise MPFlashError(f"DFU package {path.name} has unexpected {key}")

    sd_size = _expect_int(entry, "sd_size")
    bl_size = _expect_int(entry, "bl_size")
    if sd_size != profile.dfu.sd_size or bl_size != profile.dfu.bl_size:
        raise MPFlashError(f"DFU package {path.name} payload sizes do not match the profile")

    return DfuPackage(path=path, sha256=digest, size=len(data), sd_size=sd_size, bl_size=bl_size)


def inspect_application_uf2(path: Path, profile: NrfDfuProfile) -> ApplicationUf2:
    """Validate that a UF2 contains only an application for ``profile``."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MPFlashError(f"Could not inspect application UF2 {path}: {exc}") from exc
    if size == 0 or size % _UF2_BLOCK_SIZE:
        raise MPFlashError(f"Application file {path.name} is not a valid UF2 block stream")

    block_numbers: set[int] = set()
    target_ranges: list[tuple[int, int]] = []
    declared_count: Optional[int] = None
    first_address: Optional[int] = None
    end_address = 0

    try:
        with path.open("rb") as stream:
            while block := stream.read(_UF2_BLOCK_SIZE):
                if len(block) != _UF2_BLOCK_SIZE:
                    raise MPFlashError(f"Application file {path.name} has a truncated UF2 block")
                magic0, magic1, flags, target, payload_size, block_no, num_blocks, family_id = struct.unpack_from("<8I", block)
                if magic0 != _UF2_MAGIC_START0 or magic1 != _UF2_MAGIC_START1:
                    raise MPFlashError(f"Application file {path.name} has invalid UF2 magic")
                if struct.unpack_from("<I", block, 508)[0] != _UF2_MAGIC_END:
                    raise MPFlashError(f"Application file {path.name} has invalid UF2 end magic")
                if flags != _UF2_FLAG_FAMILY_ID:
                    raise MPFlashError(f"Application file {path.name} has unsupported UF2 flags 0x{flags:08X}")
                if family_id != profile.uf2_family_id:
                    raise MPFlashError(
                        f"Application file {path.name} has UF2 family 0x{family_id:08X}, expected 0x{profile.uf2_family_id:08X}"
                    )
                if payload_size <= 0 or payload_size > _UF2_MAX_PAYLOAD:
                    raise MPFlashError(f"Application file {path.name} has invalid UF2 payload size {payload_size}")
                if target < profile.application_start or target + payload_size > profile.application_end:
                    raise MPFlashError(
                        f"Application file {path.name} writes 0x{target:08X}-0x{target + payload_size:08X}, "
                        f"outside the {profile.name} application range "
                        f"0x{profile.application_start:08X}-0x{profile.application_end:08X}"
                    )
                target_end = target + payload_size
                if any(target < existing_end and target_end > existing_start for existing_start, existing_end in target_ranges):
                    raise MPFlashError(f"Application file {path.name} contains overlapping UF2 target ranges")
                target_ranges.append((target, target_end))
                if declared_count is None:
                    declared_count = num_blocks
                elif declared_count != num_blocks:
                    raise MPFlashError(f"Application file {path.name} has inconsistent UF2 block counts")
                if block_no in block_numbers:
                    raise MPFlashError(f"Application file {path.name} repeats UF2 block {block_no}")
                block_numbers.add(block_no)
                first_address = target if first_address is None else min(first_address, target)
                end_address = max(end_address, target_end)
    except OSError as exc:
        raise MPFlashError(f"Could not read application UF2 {path}: {exc}") from exc

    if declared_count is None or declared_count != len(block_numbers):
        raise MPFlashError(f"Application file {path.name} declares {declared_count or 0} UF2 blocks but contains {len(block_numbers)}")
    if block_numbers != set(range(declared_count)):
        raise MPFlashError(f"Application file {path.name} has missing or out-of-range UF2 block numbers")
    if first_address != profile.application_start:
        raise MPFlashError(
            f"Application file {path.name} starts at 0x{first_address or 0:08X}, "
            f"expected 0x{profile.application_start:08X} for {profile.name}"
        )
    assert first_address is not None

    return ApplicationUf2(
        path=path,
        family_id=profile.uf2_family_id,
        first_address=first_address,
        end_address=end_address,
        block_count=declared_count,
    )
