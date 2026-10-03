"""Typed models and strict manifest validation for MPFlash backup bundles.

A bundle is described by a versioned ``manifest.json``. Everything read from a
manifest is untrusted input, so parsing validates every field and raises
:class:`~mpflash.errors.MPFlashError` instead of returning partial data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from mpflash.errors import MPFlashError

SCHEMA_VERSION = 1
ARTIFACT_DIR = "artifacts"
FILES_DIR = "files"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ComponentKind(str, Enum):
    """Independently restorable parts of a device."""

    FLASH = "flash"
    VFS = "vfs"
    ROMFS = "romfs"


class ArtifactRole(str, Enum):
    """How an artifact was obtained."""

    DEVICE_READ = "device-read"
    LOGICAL_FILES = "logical-files"
    REFERENCE = "reference"


class Exactness(str, Enum):
    """How faithfully an artifact represents the device."""

    EXACT = "exact"  # byte-exact read of the declared address range
    PARTIAL = "partial"  # read from the device, but known to be incomplete
    LOGICAL = "logical"  # file contents only, not the raw storage
    REFERENCE = "reference"  # not read from the device


_ROLE_EXACTNESS: Dict[ArtifactRole, Tuple[Exactness, ...]] = {
    ArtifactRole.DEVICE_READ: (Exactness.EXACT, Exactness.PARTIAL),
    ArtifactRole.LOGICAL_FILES: (Exactness.LOGICAL,),
    ArtifactRole.REFERENCE: (Exactness.REFERENCE,),
}


def validate_relative_path(value: str, *, prefix: Optional[str] = None) -> str:
    """Return ``value`` if it is a safe, normalised, relative POSIX path.

    Rejects absolute paths, drive letters, backslashes, empty/``.``/``..``
    segments, control characters and (optionally) paths outside ``prefix``.
    """
    if not isinstance(value, str) or not value:
        raise MPFlashError("Bundle path must be a non-empty string")
    if "\\" in value or ":" in value or any(ord(char) < 32 for char in value):
        raise MPFlashError(f"Unsafe bundle path {value!r}")
    if value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")):
        raise MPFlashError(f"Unsafe bundle path {value!r}")
    if prefix is not None and PurePosixPath(value).parts[0] != prefix:
        raise MPFlashError(f"Bundle path {value!r} must be inside {prefix!r}")
    return value


@dataclass(frozen=True)
class DeviceIdentity:
    """Stable properties used to decide whether a bundle fits a target board."""

    port: str
    board_id: str
    cpu: str = ""
    family: str = ""
    version: str = ""
    description: str = ""
    sys_platform: str = ""
    usb_vid: int = 0
    usb_pid: int = 0
    serial_number: str = ""

    @classmethod
    def from_mcu(cls, mcu: Any) -> "DeviceIdentity":
        """Build an identity from a probed ``MPRemoteBoard``."""
        port = str(getattr(mcu, "port", "") or "")
        board_id = str(getattr(mcu, "board_id", "") or "")
        if not port or not board_id:
            raise MPFlashError(
                f"Cannot identify the board on {getattr(mcu, 'serialport', '?')}; a backup bundle requires a known port and board ID"
            )
        return cls(
            port=port,
            board_id=board_id,
            cpu=str(getattr(mcu, "cpu", "") or ""),
            family=str(getattr(mcu, "family", "") or ""),
            version=str(getattr(mcu, "version", "") or ""),
            description=str(getattr(mcu, "description", "") or ""),
            sys_platform=str(getattr(mcu, "sys_platform", "") or ""),
            usb_vid=int(getattr(mcu, "vid", 0) or 0),
            usb_pid=int(getattr(mcu, "pid", 0) or 0),
            serial_number=str(getattr(mcu, "serial_number", "") or ""),
        )

    def mismatches(self, target: "DeviceIdentity") -> List[str]:
        """Describe hard identity differences between this (bundle) identity and a ``target``."""
        problems = []
        for name in ("port", "board_id"):
            if getattr(self, name) != getattr(target, name):
                problems.append(f"{name}: bundle has {getattr(self, name)!r}, target has {getattr(target, name)!r}")
        if self.cpu and target.cpu and self.cpu != target.cpu:
            problems.append(f"cpu: bundle has {self.cpu!r}, target has {target.cpu!r}")
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "board_id": self.board_id,
            "cpu": self.cpu,
            "family": self.family,
            "version": self.version,
            "description": self.description,
            "sys_platform": self.sys_platform,
            "usb_vid": self.usb_vid,
            "usb_pid": self.usb_pid,
            "serial_number": self.serial_number,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeviceIdentity":
        return cls(
            port=_text(data, "port", required=True),
            board_id=_text(data, "board_id", required=True),
            cpu=_text(data, "cpu"),
            family=_text(data, "family"),
            version=_text(data, "version"),
            description=_text(data, "description"),
            sys_platform=_text(data, "sys_platform"),
            usb_vid=_integer(data, "usb_vid", default=0),
            usb_pid=_integer(data, "usb_pid", default=0),
            serial_number=_text(data, "serial_number"),
        )


@dataclass(frozen=True)
class Artifact:
    """One file inside a bundle's ``artifacts/`` folder."""

    component: ComponentKind
    role: ArtifactRole
    exactness: Exactness
    path: str
    size: int
    sha256: str
    provider: str
    address: Optional[int] = None
    length: Optional[int] = None
    covers: Tuple[ComponentKind, ...] = ()
    exclusions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_relative_path(self.path, prefix=ARTIFACT_DIR)
        if self.exactness not in _ROLE_EXACTNESS[self.role]:
            raise MPFlashError(f"Artifact {self.path!r}: role {self.role.value!r} cannot have exactness {self.exactness.value!r}")
        if self.size < 0 or not _SHA256_RE.match(self.sha256):
            raise MPFlashError(f"Artifact {self.path!r} has an invalid size or SHA-256")
        if (self.address is None) != (self.length is None):
            raise MPFlashError(f"Artifact {self.path!r} must declare address and length together")
        if self.address is not None and self.length is not None:
            if self.address < 0 or self.length <= 0:
                raise MPFlashError(f"Artifact {self.path!r} has an invalid address range")
            if self.role is ArtifactRole.DEVICE_READ and self.size != self.length:
                raise MPFlashError(f"Artifact {self.path!r} size {self.size} does not match declared length {self.length}")
        if self.component is ComponentKind.FLASH and self.role is ArtifactRole.DEVICE_READ and self.address is None:
            raise MPFlashError(f"Raw flash artifact {self.path!r} must declare its address range")
        if self.component in self.covers:
            raise MPFlashError(f"Artifact {self.path!r} cannot cover its own component")
        if self.covers and self.role is not ArtifactRole.DEVICE_READ:
            raise MPFlashError(f"Artifact {self.path!r}: only device-read artifacts can cover other components")

    @property
    def restorable(self) -> bool:
        """Reference artifacts document the device but are never written back."""
        return self.role is not ArtifactRole.REFERENCE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component.value,
            "role": self.role.value,
            "exactness": self.exactness.value,
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "provider": self.provider,
            "address": self.address,
            "length": self.length,
            "covers": [kind.value for kind in self.covers],
            "exclusions": list(self.exclusions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Artifact":
        covers_raw = data.get("covers", [])
        exclusions_raw = data.get("exclusions", [])
        if not isinstance(covers_raw, list) or not isinstance(exclusions_raw, list):
            raise MPFlashError("Artifact covers and exclusions must be lists")
        if not all(isinstance(item, str) for item in exclusions_raw):
            raise MPFlashError("Artifact exclusions must be strings")
        return cls(
            component=_enum(ComponentKind, data, "component"),
            role=_enum(ArtifactRole, data, "role"),
            exactness=_enum(Exactness, data, "exactness"),
            path=_text(data, "path", required=True),
            size=_integer(data, "size"),
            sha256=_text(data, "sha256", required=True),
            provider=_text(data, "provider", required=True),
            address=_integer(data, "address", default=None),
            length=_integer(data, "length", default=None),
            covers=tuple(_enum_value(ComponentKind, item, "covers") for item in covers_raw),
            exclusions=tuple(exclusions_raw),
        )


@dataclass(frozen=True)
class Manifest:
    """Validated contents of ``manifest.json``."""

    created_utc: str
    tool_version: str
    host: Mapping[str, str]
    device: DeviceIdentity
    artifacts: Tuple[Artifact, ...]
    files_tree: Optional[str] = None
    schema_version: int = SCHEMA_VERSION
    complete: bool = True
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        paths = [artifact.path for artifact in self.artifacts]
        if len(set(paths)) != len(paths):
            raise MPFlashError("Bundle manifest lists the same artifact path more than once")
        if self.files_tree is not None:
            validate_relative_path(self.files_tree, prefix=FILES_DIR)

    @property
    def components(self) -> Tuple[ComponentKind, ...]:
        """Components present in the bundle, in a stable order."""
        present = {artifact.component for artifact in self.artifacts}
        return tuple(kind for kind in ComponentKind if kind in present)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "complete": self.complete,
            "created_utc": self.created_utc,
            "tool_version": self.tool_version,
            "host": dict(self.host),
            "device": self.device.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "files_tree": self.files_tree,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Manifest":
        if not isinstance(data, Mapping):
            raise MPFlashError("Bundle manifest must be a JSON object")
        version = _integer(data, "schema_version")
        if version != SCHEMA_VERSION:
            raise MPFlashError(
                f"Unsupported bundle schema version {version}; this MPFlash supports version {SCHEMA_VERSION}. "
                "Upgrade MPFlash to read newer bundles."
            )
        if data.get("complete") is not True:
            raise MPFlashError("Bundle is marked incomplete and cannot be restored")
        device = data.get("device")
        artifacts = data.get("artifacts")
        host = data.get("host")
        notes = data.get("notes", [])
        if not isinstance(device, Mapping) or not isinstance(artifacts, list) or not isinstance(host, Mapping):
            raise MPFlashError("Bundle manifest is missing device, host or artifacts")
        if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
            raise MPFlashError("Bundle notes must be a list of strings")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in host.items()):
            raise MPFlashError("Bundle host information must contain strings")
        files_tree = data.get("files_tree")
        if files_tree is not None and not isinstance(files_tree, str):
            raise MPFlashError("Bundle files_tree must be a string or null")
        for item in artifacts:
            if not isinstance(item, Mapping):
                raise MPFlashError("Bundle artifacts must be JSON objects")
        return cls(
            created_utc=_text(data, "created_utc", required=True),
            tool_version=_text(data, "tool_version", required=True),
            host=dict(host),
            device=DeviceIdentity.from_dict(device),
            artifacts=tuple(Artifact.from_dict(item) for item in artifacts),
            files_tree=files_tree,
            notes=tuple(notes),
        )


@dataclass(frozen=True)
class ProviderCapability:
    """What one provider can do for one component of the connected device.

    ``can_restore`` is separate from ``can_backup`` because several transports
    can read data they cannot safely write back.
    """

    component: ComponentKind
    can_backup: bool
    can_restore: bool
    exactness: Exactness
    covers: Tuple[ComponentKind, ...] = ()
    exclusions: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Strict field helpers
# ---------------------------------------------------------------------------

_REQUIRED: Any = object()


def _text(data: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = data.get(key, "")
    if not isinstance(value, str) or (required and not value):
        raise MPFlashError(f"Bundle field {key!r} is missing or not a string")
    return value


def _integer(data: Mapping[str, Any], key: str, *, default: Any = _REQUIRED) -> Any:
    if key not in data or data[key] is None:
        if default is _REQUIRED:
            raise MPFlashError(f"Bundle field {key!r} is missing or not an integer")
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise MPFlashError(f"Bundle field {key!r} is missing or not an integer")
    return value


def _enum_value(enum_type: Any, value: Any, key: str) -> Any:
    try:
        return enum_type(value)
    except ValueError:
        raise MPFlashError(f"Bundle field {key!r} has unknown value {value!r}") from None


def _enum(enum_type: Any, data: Mapping[str, Any], key: str) -> Any:
    return _enum_value(enum_type, data.get(key), key)
