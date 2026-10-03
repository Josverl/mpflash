"""Curated nRF DFU migration profiles and packaged resource access."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Generator, Mapping

from mpflash.errors import MPFlashError

_RESOURCE_PACKAGE = "mpflash.resources.nrf_dfu"


@dataclass(frozen=True)
class DfuManifestExpectation:
    """Expected legacy Nordic DFU package metadata."""

    dfu_version: float
    device_type: int
    device_revision: int
    softdevice_req: tuple[int, ...]
    sd_size: int
    bl_size: int


@dataclass(frozen=True)
class NrfDfuProfile:
    """A complete allowlisted SoftDevice, bootloader, and application layout."""

    name: str
    mcu: str
    softdevice: str
    bootloader_version: str
    source_bootloader_versions: tuple[str, ...]
    board_id: str
    usb_vid: int
    usb_pid: int
    volume_label: str
    package: str
    package_size: int
    sha256: str
    source: str
    uf2_family_id: int
    application_start: int
    application_end: int
    dfu: DfuManifestExpectation

    @property
    def usb_id(self) -> tuple[int, int]:
        """Return the bootloader USB VID/PID tuple."""
        return self.usb_vid, self.usb_pid


def _required_str(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise MPFlashError(f"Invalid nRF DFU profile field {key!r}")
    return value


def _required_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise MPFlashError(f"Invalid nRF DFU profile field {key!r}")
    return value


def _required_number(mapping: Mapping[str, object], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)):
        raise MPFlashError(f"Invalid nRF DFU profile field {key!r}")
    return float(value)


def _required_dict(mapping: Mapping[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value):
        raise MPFlashError(f"Invalid nRF DFU profile field {key!r}")
    return value


def _required_list(mapping: Mapping[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise MPFlashError(f"Invalid nRF DFU profile field {key!r}")
    return value


def _parse_profile(name: str, raw: Mapping[str, object]) -> NrfDfuProfile:
    dfu_raw = _required_dict(raw, "dfu")
    softdevice_req_raw = _required_list(dfu_raw, "softdevice_req")
    if not softdevice_req_raw or not all(isinstance(item, int) for item in softdevice_req_raw):
        raise MPFlashError(f"Invalid nRF DFU profile field {name}.dfu.softdevice_req")
    softdevice_req = tuple(item for item in softdevice_req_raw if isinstance(item, int))
    source_bootloader_versions_raw = _required_list(raw, "source_bootloader_versions")
    if not source_bootloader_versions_raw or not all(isinstance(item, str) and item for item in source_bootloader_versions_raw):
        raise MPFlashError(f"Invalid nRF DFU profile field {name}.source_bootloader_versions")
    source_bootloader_versions = tuple(item for item in source_bootloader_versions_raw if isinstance(item, str))

    return NrfDfuProfile(
        name=name,
        mcu=_required_str(raw, "mcu"),
        softdevice=_required_str(raw, "softdevice"),
        bootloader_version=_required_str(raw, "bootloader_version"),
        source_bootloader_versions=source_bootloader_versions,
        board_id=_required_str(raw, "board_id"),
        usb_vid=_required_int(raw, "usb_vid"),
        usb_pid=_required_int(raw, "usb_pid"),
        volume_label=_required_str(raw, "volume_label"),
        package=_required_str(raw, "package"),
        package_size=_required_int(raw, "package_size"),
        sha256=_required_str(raw, "sha256"),
        source=_required_str(raw, "source"),
        uf2_family_id=_required_int(raw, "uf2_family_id"),
        application_start=_required_int(raw, "application_start"),
        application_end=_required_int(raw, "application_end"),
        dfu=DfuManifestExpectation(
            dfu_version=_required_number(dfu_raw, "dfu_version"),
            device_type=_required_int(dfu_raw, "device_type"),
            device_revision=_required_int(dfu_raw, "device_revision"),
            softdevice_req=softdevice_req,
            sd_size=_required_int(dfu_raw, "sd_size"),
            bl_size=_required_int(dfu_raw, "bl_size"),
        ),
    )


@lru_cache(maxsize=1)
def get_profiles() -> Mapping[str, NrfDfuProfile]:
    """Load and validate the packaged nRF migration profile manifest."""
    manifest = resources.files(_RESOURCE_PACKAGE).joinpath("manifest.json")
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MPFlashError(f"Could not read packaged nRF DFU profiles: {exc}") from exc

    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise MPFlashError("Unsupported packaged nRF DFU profile schema")
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise MPFlashError("Packaged nRF DFU profile manifest has no profiles")

    parsed: Dict[str, NrfDfuProfile] = {}
    for name, value in profiles.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise MPFlashError("Invalid packaged nRF DFU profile entry")
        parsed[name] = _parse_profile(name, value)
    return MappingProxyType(parsed)


def get_profile(name: str) -> NrfDfuProfile:
    """Return one allowlisted migration profile."""
    try:
        return get_profiles()[name.casefold()]
    except KeyError:
        choices = ", ".join(sorted(get_profiles()))
        raise MPFlashError(f"Unknown nRF SoftDevice profile {name!r}; choose one of: {choices}") from None


@contextmanager
def profile_package_path(profile: NrfDfuProfile) -> Generator[Path, None, None]:
    """Yield a filesystem path for a profile's packaged DFU ZIP."""
    package = resources.files(_RESOURCE_PACKAGE).joinpath(profile.package)
    if not package.is_file():
        raise MPFlashError(f"Packaged nRF DFU artifact is missing: {profile.package}")
    with resources.as_file(package) as path:
        yield path
