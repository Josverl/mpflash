"""Manifest, artifact and path validation for backup bundles."""

from types import SimpleNamespace

import pytest

from mpflash.backup.models import (
    Artifact,
    ArtifactRole,
    ComponentKind,
    DeviceIdentity,
    Exactness,
    Manifest,
    validate_relative_path,
)
from mpflash.errors import MPFlashError

SHA = "a" * 64


def make_artifact(**overrides) -> Artifact:
    fields = dict(
        component=ComponentKind.VFS,
        role=ArtifactRole.LOGICAL_FILES,
        exactness=Exactness.LOGICAL,
        path="artifacts/vfs.zip",
        size=5,
        sha256=SHA,
        provider="fake",
    )
    fields.update(overrides)
    return Artifact(**fields)  # type: ignore[arg-type]


def make_manifest_dict(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "complete": True,
        "created_utc": "2026-10-03T21:00:00Z",
        "tool_version": "1.0",
        "host": {"system": "Windows"},
        "device": {"port": "esp32", "board_id": "ESP32_GENERIC"},
        "artifacts": [make_artifact().to_dict()],
        "files_tree": None,
        "notes": [],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("value", ["artifacts/a.bin", "files/dir/sub/x.py"])
def test_validate_relative_path_accepts_normal_paths(value):
    assert validate_relative_path(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "/etc/passwd", "../x", "a/../b", "a\\b", "C:/x", "a//b", "a/./b", "artifacts/", "a\x00b", ".."],
)
def test_validate_relative_path_rejects_unsafe_paths(value):
    with pytest.raises(MPFlashError, match="path"):
        validate_relative_path(value)


def test_validate_relative_path_enforces_prefix():
    with pytest.raises(MPFlashError, match="inside 'artifacts'"):
        validate_relative_path("files/x", prefix="artifacts")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"role": ArtifactRole.REFERENCE}, "cannot have exactness"),
        ({"exactness": Exactness.EXACT}, "cannot have exactness"),
        ({"sha256": "xyz"}, "invalid size or SHA-256"),
        ({"size": -1}, "invalid size or SHA-256"),
        ({"address": 0}, "address and length together"),
        ({"path": "elsewhere/vfs.zip"}, "inside 'artifacts'"),
        ({"covers": (ComponentKind.ROMFS,)}, "only device-read artifacts can cover"),
    ],
)
def test_artifact_rejects_inconsistent_metadata(overrides, message):
    with pytest.raises(MPFlashError, match=message):
        make_artifact(**overrides)


def test_raw_flash_artifact_requires_an_address_range():
    with pytest.raises(MPFlashError, match="must declare its address range"):
        make_artifact(component=ComponentKind.FLASH, role=ArtifactRole.DEVICE_READ, exactness=Exactness.EXACT)


def test_device_read_size_must_match_declared_length():
    with pytest.raises(MPFlashError, match="does not match declared length"):
        make_artifact(
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            address=0,
            length=10,
        )


def test_artifact_cannot_cover_its_own_component():
    with pytest.raises(MPFlashError, match="cannot cover its own component"):
        make_artifact(
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            address=0,
            length=5,
            covers=(ComponentKind.FLASH,),
        )


def test_reference_artifacts_are_not_restorable():
    reference = make_artifact(role=ArtifactRole.REFERENCE, exactness=Exactness.REFERENCE)

    assert not reference.restorable
    assert make_artifact().restorable


def test_manifest_round_trips_through_dict():
    flash = make_artifact(
        component=ComponentKind.FLASH,
        role=ArtifactRole.DEVICE_READ,
        exactness=Exactness.EXACT,
        path="artifacts/flash.bin",
        address=0x1000,
        length=5,
        covers=(ComponentKind.ROMFS,),
        exclusions=("eFuses",),
    )
    manifest = Manifest.from_dict(make_manifest_dict(artifacts=[flash.to_dict(), make_artifact().to_dict()], files_tree="files"))

    assert Manifest.from_dict(manifest.to_dict()) == manifest
    assert manifest.components == (ComponentKind.FLASH, ComponentKind.VFS)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"schema_version": 2}, "Unsupported bundle schema version 2"),
        ({"schema_version": "1"}, "schema_version"),
        ({"complete": False}, "incomplete"),
        ({"device": []}, "missing device"),
        ({"artifacts": "nope"}, "missing device"),
        ({"artifacts": [5]}, "JSON objects"),
        ({"notes": [1]}, "notes"),
        ({"host": {"system": 1}}, "host information"),
        ({"files_tree": "elsewhere"}, "inside 'files'"),
        ({"files_tree": 5}, "files_tree"),
        ({"created_utc": ""}, "created_utc"),
    ],
)
def test_manifest_rejects_invalid_content(overrides, message):
    with pytest.raises(MPFlashError, match=message):
        Manifest.from_dict(make_manifest_dict(**overrides))


def test_manifest_rejects_non_object():
    with pytest.raises(MPFlashError, match="JSON object"):
        Manifest.from_dict([])  # type: ignore[arg-type]


def test_manifest_rejects_duplicate_artifact_paths():
    item = make_artifact().to_dict()

    with pytest.raises(MPFlashError, match="more than once"):
        Manifest.from_dict(make_manifest_dict(artifacts=[item, item]))


@pytest.mark.parametrize("field, value", [("component", "bogus"), ("role", None), ("size", True), ("size", "5")])
def test_artifact_from_dict_rejects_invalid_fields(field, value):
    data = make_artifact().to_dict()
    data[field] = value

    with pytest.raises(MPFlashError):
        Artifact.from_dict(data)


def test_device_identity_requires_port_and_board_id():
    with pytest.raises(MPFlashError, match="Cannot identify the board"):
        DeviceIdentity.from_mcu(SimpleNamespace(serialport="COM1", port="", board_id=""))


def test_device_identity_mismatch_reports_each_difference():
    bundle = DeviceIdentity(port="esp32", board_id="ESP32_GENERIC", cpu="ESP32")
    target = DeviceIdentity(port="rp2", board_id="RPI_PICO", cpu="RP2040")

    problems = bundle.mismatches(target)

    assert len(problems) == 3
    assert bundle.mismatches(bundle) == []
    assert bundle.mismatches(DeviceIdentity(port="esp32", board_id="ESP32_GENERIC", serial_number="other")) == []
