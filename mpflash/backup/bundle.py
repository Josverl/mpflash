"""Atomic writer, strict reader and README renderer for MPFlash backup bundles.

Layout of a finished bundle::

    <name>/
      README.md       human readable summary
      manifest.json   machine readable, versioned description
      artifacts/      hashed files that restore reads
      files/          optional, informational copy of the VFS tree

Bundles are first assembled in ``<name>.incomplete`` and renamed only after the
manifest is written, so a crash can never leave something that looks finished.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from mpflash.errors import MPFlashError

from .models import (
    ARTIFACT_DIR,
    Artifact,
    ArtifactRole,
    ComponentKind,
    DeviceIdentity,
    Exactness,
    Manifest,
    validate_relative_path,
)

MANIFEST_NAME = "manifest.json"
README_NAME = "README.md"
INCOMPLETE_SUFFIX = ".incomplete"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of ``path``, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_name(device: DeviceIdentity, *, now: Optional[datetime] = None) -> str:
    """Return a filesystem-safe, sortable folder name for a new bundle."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    raw = f"{device.board_id}-{device.port}-{stamp}"
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw).lstrip("._-") or f"backup-{stamp}"


def _restrict(path: Path, mode: int) -> None:
    """Keep backups private on POSIX hosts; Windows ACLs are inherited."""
    if os.name == "posix":
        try:
            path.chmod(mode)
        except OSError:
            pass


class BundleWriter:
    """Assemble a bundle in a staging folder and publish it atomically."""

    def __init__(self, parent: Path, name: str):
        if not _NAME_RE.match(name) or name.endswith(INCOMPLETE_SUFFIX):
            raise MPFlashError(f"Invalid backup folder name {name!r}")
        self.parent = Path(parent)
        self.name = name
        self.final = self.parent / name
        self.staging = self.parent / f"{name}{INCOMPLETE_SUFFIX}"
        self._artifacts: list[Artifact] = []
        self._committed = False
        self._entered = False

    def __enter__(self) -> "BundleWriter":
        if self.final.exists() or self.staging.exists():
            raise MPFlashError(f"Backup folder {self.final} already exists; refusing to overwrite it")
        self.parent.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(mode=0o700)
        _restrict(self.staging, 0o700)
        (self.staging / ARTIFACT_DIR).mkdir(mode=0o700)
        self._entered = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._entered and not self._committed:
            shutil.rmtree(self.staging, ignore_errors=True)

    # -- staging helpers -------------------------------------------------

    @property
    def artifacts(self) -> Tuple[Artifact, ...]:
        """Artifacts registered so far, in registration order."""
        return tuple(self._artifacts)

    def artifact_path(self, filename: str) -> Path:
        """Return the staging path a provider should write ``filename`` to."""
        if not self._entered:
            raise MPFlashError("BundleWriter must be used as a context manager")
        validate_relative_path(f"{ARTIFACT_DIR}/{filename}", prefix=ARTIFACT_DIR)
        if "/" in filename:
            raise MPFlashError(f"Artifact filename {filename!r} must not contain folders")
        return self.staging / ARTIFACT_DIR / filename

    def register_artifact(
        self,
        filename: str,
        *,
        component: ComponentKind,
        role: ArtifactRole,
        exactness: Exactness,
        provider: str,
        address: Optional[int] = None,
        length: Optional[int] = None,
        covers: Sequence[ComponentKind] = (),
        exclusions: Sequence[str] = (),
    ) -> Artifact:
        """Hash an already staged file and record it in the manifest."""
        path = self.artifact_path(filename)
        if not path.is_file() or path.is_symlink():
            raise MPFlashError(f"Provider {provider!r} did not stage artifact {filename!r}")
        _restrict(path, 0o600)
        artifact = Artifact(
            component=component,
            role=role,
            exactness=exactness,
            path=f"{ARTIFACT_DIR}/{filename}",
            size=path.stat().st_size,
            sha256=sha256_file(path),
            provider=provider,
            address=address,
            length=length,
            covers=tuple(covers),
            exclusions=tuple(exclusions),
        )
        if any(existing.path == artifact.path for existing in self._artifacts):
            raise MPFlashError(f"Artifact {artifact.path!r} was registered twice")
        self._artifacts.append(artifact)
        return artifact

    def add_artifact_bytes(self, filename: str, data: bytes, **metadata: Any) -> Artifact:
        """Write ``data`` as an artifact and register it."""
        self.artifact_path(filename).write_bytes(data)
        return self.register_artifact(filename, **metadata)

    def add_artifact_copy(self, filename: str, source: Path, **metadata: Any) -> Artifact:
        """Copy ``source`` into the bundle and register it."""
        shutil.copyfile(source, self.artifact_path(filename))
        return self.register_artifact(filename, **metadata)

    # -- publish ---------------------------------------------------------

    def commit(self, device: DeviceIdentity, *, tree_text: str = "", notes: Iterable[str] = ()) -> Path:
        """Write the manifest and README, then publish the finished bundle."""
        if not self._entered or self._committed:
            raise MPFlashError("BundleWriter cannot be committed in its current state")
        if not self._artifacts:
            raise MPFlashError("Refusing to publish a backup bundle without artifacts")
        manifest = Manifest(
            created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            tool_version=_tool_version(),
            host=_host_info(),
            device=device,
            artifacts=tuple(self._artifacts),
            notes=tuple(notes),
        )
        # newline="\n": the same bundle must be byte-identical on every host (Windows would otherwise write CRLF).
        (self.staging / MANIFEST_NAME).write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8", newline="\n")
        (self.staging / README_NAME).write_text(render_readme(manifest, self.name, tree_text), encoding="utf-8", newline="\n")
        _restrict(self.staging / MANIFEST_NAME, 0o600)
        _restrict(self.staging / README_NAME, 0o600)
        if self.final.exists():
            raise MPFlashError(f"Backup folder {self.final} appeared while the backup was running; refusing to overwrite it")
        self.staging.rename(self.final)
        self._committed = True
        return self.final


class Bundle:
    """A validated bundle on disk. Call :meth:`verify` before trusting artifact bytes."""

    def __init__(self, root: Path, manifest: Manifest):
        self.root = root
        self.manifest = manifest

    def artifact_path(self, artifact: Artifact) -> Path:
        return self.root.joinpath(*artifact.path.split("/"))

    def verify(self) -> None:
        """Check that every artifact exists, matches its size/hash, and nothing else is hiding in ``artifacts/``."""
        listed = {artifact.path for artifact in self.manifest.artifacts}
        artifacts_root = self.root / ARTIFACT_DIR
        for found in artifacts_root.rglob("*"):
            relative = found.relative_to(self.root).as_posix()
            if found.is_symlink():
                raise MPFlashError(f"Bundle contains a symbolic link: {relative}")
            if found.is_file() and relative not in listed:
                raise MPFlashError(f"Bundle contains an unlisted artifact file: {relative}")
        for artifact in self.manifest.artifacts:
            path = self.artifact_path(artifact)
            _require_regular_file(self.root, path, artifact.path)
            if path.stat().st_size != artifact.size:
                raise MPFlashError(f"Artifact {artifact.path} has size {path.stat().st_size}, expected {artifact.size}")
            if sha256_file(path) != artifact.sha256:
                raise MPFlashError(f"Artifact {artifact.path} failed SHA-256 verification; the bundle was modified or is corrupt")


def read_bundle(path: Path) -> Bundle:
    """Open and structurally validate a bundle folder (hashes are checked by :meth:`Bundle.verify`)."""
    root = Path(path)
    if root.name.endswith(INCOMPLETE_SUFFIX):
        raise MPFlashError(f"{root} is an incomplete backup and cannot be used")
    if not root.is_dir() or root.is_symlink():
        raise MPFlashError(f"Backup bundle {root} is not a folder")
    manifest_path = root / MANIFEST_NAME
    _require_regular_file(root, manifest_path, MANIFEST_NAME)
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise MPFlashError("Bundle manifest is unreasonably large")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MPFlashError(f"Bundle manifest is not valid JSON: {exc}") from exc
    manifest = Manifest.from_dict(data)
    for artifact in manifest.artifacts:
        _require_regular_file(root, root.joinpath(*artifact.path.split("/")), artifact.path)
    return Bundle(root, manifest)


def _require_regular_file(root: Path, path: Path, label: str) -> None:
    """Reject missing files, symlinks (including parents) and paths escaping ``root``."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise MPFlashError(f"Bundle path {label} passes through a symbolic link")
    if not path.is_file():
        raise MPFlashError(f"Bundle file {label} is missing")


def _tool_version() -> str:
    from mpflash.config import __version__

    return str(__version__)


def _host_info() -> dict[str, str]:
    return {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": sys.version.split()[0]}


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

_STANDING_EXCLUSIONS = (
    "Raw flash images contain only the address ranges listed above. OTP/eFuses, option bytes, UICR, security keys, "
    "calibration data, external memories and protected regions are not included unless an artifact lists them.",
    "Logical file backups contain file contents only: no firmware, bootloader, partition table, filesystem allocation "
    "or wear-levelling state.",
    "Reference artifacts were not read from this device.",
)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _span(artifact: Artifact) -> str:
    if artifact.address is None or artifact.length is None:
        return ""
    return f"0x{artifact.address:08X}+0x{artifact.length:X}"


def render_readme(manifest: Manifest, folder_name: str, tree_text: str = "") -> str:
    """Render the human readable summary stored beside ``manifest.json``."""
    device = manifest.device
    lines = [
        f"# MPFlash backup: {device.board_id} ({device.port})",
        "",
        f"Created {manifest.created_utc} by MPFlash {manifest.tool_version} on "
        f"{manifest.host.get('system', '?')} {manifest.host.get('release', '')}.".rstrip(),
        "",
        "## Security warning",
        "",
        "This folder can contain credentials, Wi-Fi passwords, keys and deleted data. Store it privately and do not share or upload it.",
        "",
        "## Device",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Board | {_cell(device.board_id)} |",
        f"| Port | {_cell(device.port)} |",
        f"| CPU | {_cell(device.cpu)} |",
        f"| Description | {_cell(device.description)} |",
        f"| Firmware | {_cell(device.family)} {_cell(device.version)} |",
        f"| USB | {device.usb_vid:04X}:{device.usb_pid:04X} |",
        f"| Serial number | {_cell(device.serial_number)} |",
        "",
        "## Contents",
        "",
        "| Component | File | Role | Exactness | Range | Size | SHA-256 |",
        "|---|---|---|---|---|---|---|",
    ]
    for artifact in manifest.artifacts:
        lines.append(
            f"| {artifact.component.value} | `{_cell(artifact.path)}` | {artifact.role.value} | {artifact.exactness.value} "
            f"| {_span(artifact)} | {artifact.size} | `{artifact.sha256}` |"
        )
    lines += ["", "## Not included", ""]
    lines += [f"- {text}" for text in _STANDING_EXCLUSIONS]
    listed: dict[str, list[str]] = {}
    for artifact in manifest.artifacts:
        for exclusion in artifact.exclusions:
            listed.setdefault(exclusion, []).append(f"`{artifact.path}`")
    lines += [f"- {', '.join(paths)}: {exclusion}" for exclusion, paths in listed.items()]
    for artifact in manifest.artifacts:
        if artifact.covers:
            covered = ", ".join(kind.value for kind in artifact.covers)
            lines.append(f"- `{artifact.path}` already contains: {covered}. Restoring it replaces those components.")
    if manifest.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in manifest.notes]
    lines += [
        "",
        "## Restore",
        "",
        "```text",
        f"mpflash restore {folder_name} --serial <PORT> --dry-run",
        f"mpflash restore {folder_name} --serial <PORT>",
        "```",
        "",
        "Restore verifies every file hash and refuses boards that do not match the device above.",
    ]
    if tree_text.strip():
        lines += ["", "## Filesystem tree", "", "```text", tree_text.rstrip(), "```"]
    return "\n".join(lines) + "\n"


__all__ = [
    "Bundle",
    "BundleWriter",
    "INCOMPLETE_SUFFIX",
    "MANIFEST_NAME",
    "README_NAME",
    "bundle_name",
    "read_bundle",
    "render_readme",
    "sha256_file",
]
