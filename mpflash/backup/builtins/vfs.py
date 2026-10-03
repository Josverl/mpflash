"""Logical backup and restore of a MicroPython board's writable filesystem.

The backup is a deterministic ZIP of the files plus a JSON inventory (mounts, sizes and
SHA-256 of every entry). It is *logical*: only file contents and directories are kept, not
the firmware, bootloader, partition table or filesystem allocation state.

Restore mirrors the backup: afterwards the backed-up mounts hold exactly the backed-up
entries. Extra files are deleted first (freeing space), then missing directories are created,
changed files are written, and every file is verified by hash.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import zipfile
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from mpflash.backup.base import BackupContext, BackupOutput, BackupProvider
from mpflash.backup.bundle import Bundle
from mpflash.backup.devicefs import DeviceFs, Mount, mount_table_summary, open_device_fs
from mpflash.backup.models import Artifact, ArtifactRole, ComponentKind, Exactness, ProviderCapability
from mpflash.backup.registry import register
from mpflash.errors import MPFlashError
from mpflash.logger import log

ZIP_NAME = "vfs.zip"
INVENTORY_NAME = "vfs-inventory.json"
INVENTORY_SCHEMA = 1
#: A backup must leave this share of the filesystem free; LittleFS needs headroom for metadata.
MAX_FILL = 0.9
_SHOWN_PATHS = 5
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TREE_LINES = 400

EXCLUSIONS = (
    "Firmware, bootloader and partition table are not included.",
    "Filesystem allocation, free-space and wear-levelling state are not included.",
    "The read-only ROMFS (/rom) and removable storage (/sd*) are not included.",
)

Opener = Callable[..., "AbstractContextManager[DeviceFs]"]


@dataclass(frozen=True)
class Entry:
    """One file or directory of the backed-up tree."""

    path: str
    is_dir: bool
    size: int = 0
    sha256: str = ""


@dataclass(frozen=True)
class Inventory:
    """Validated description of what the archive contains."""

    mounts: Tuple[Mount, ...]
    entries: Tuple[Entry, ...]

    @property
    def files(self) -> Dict[str, Entry]:
        return {entry.path: entry for entry in self.entries if not entry.is_dir}

    @property
    def dirs(self) -> Set[str]:
        return {entry.path for entry in self.entries if entry.is_dir}

    def mount_for(self, path: str) -> Optional[Mount]:
        """Return the deepest backed-up mount that contains ``path``."""
        matches = [m for m in self.mounts if m.path == "/" or path == m.path or path.startswith(m.path + "/")]
        return max(matches, key=lambda m: len(m.path)) if matches else None


def _is_backed_up(mount: Mount) -> Optional[str]:
    """Return ``None`` when the mount is included, otherwise why it is skipped."""
    if "Rom" in mount.fstype:
        return "read-only ROMFS"
    if mount.path == "/sd" or mount.path.startswith("/sd/"):
        return "removable storage"
    return None


def _join(directory: str, name: str) -> str:
    return posixpath.join(directory, name)


def _walk(fs: DeviceFs, mount: Mount, other_mounts: Set[str]) -> List[Entry]:
    """List every directory and file below ``mount`` (sorted), without crossing into other mounts."""
    found: List[Entry] = []

    def visit(directory: str) -> None:
        for item in sorted(fs.listdir(directory), key=lambda entry: entry.name):
            path = _join(directory, item.name)
            if path in other_mounts:
                continue
            if item.is_dir:
                found.append(Entry(path, True))
                visit(path)
            else:
                found.append(Entry(path, False))

    visit(mount.path)
    return found


# ---------------------------------------------------------------------------
# Archive and inventory
# ---------------------------------------------------------------------------


def _member_name(path: str, is_dir: bool) -> str:
    return path.lstrip("/") + ("/" if is_dir else "")


def _inventory_json(mounts: Sequence[Mount], skipped: Dict[str, str], entries: Sequence[Entry], capacities: Dict[str, int]) -> str:
    return json.dumps(
        {
            "schema": INVENTORY_SCHEMA,
            "mounts": [
                {"path": m.path, "fstype": m.fstype, "included": m.path not in skipped, "reason": skipped.get(m.path, "")} for m in mounts
            ],
            "capacity": capacities,
            "entries": [
                {"path": e.path, "type": "dir"} if e.is_dir else {"path": e.path, "type": "file", "size": e.size, "sha256": e.sha256}
                for e in entries
            ],
        },
        indent=2,
    )


def _device_tree(mcu: Any) -> Tuple[str, str]:
    """Return ``(tree text, note)`` from ``mpremote tree -h`` for the bundle README.

    The tree is documentation only, so failing to read it is reported in a note rather than
    failing the backup. It runs after the backup connection is closed so the port is free.
    """
    was_connected = getattr(mcu, "connected", True)
    try:
        rc, output = mcu.run_command(["tree", "-h"], no_info=True, log_errors=False, timeout=60)
    except (OSError, RuntimeError) as error:
        return "", f"The filesystem tree could not be read ({error}); see {INVENTORY_NAME} for the file list."
    finally:
        mcu.connected = was_connected  # a failing tree command does not mean the board is gone
    lines = "".join(output).rstrip().splitlines()
    if rc != 0:
        return "", f"mpremote tree failed (exit code {rc}); see {INVENTORY_NAME} for the file list."
    if len(lines) > _TREE_LINES:
        omitted = len(lines) - _TREE_LINES
        lines = lines[:_TREE_LINES] + [f"... {omitted} more lines (see {INVENTORY_NAME})"]
    return "\n".join(lines), ""


# ---------------------------------------------------------------------------
# Restore planning
# ---------------------------------------------------------------------------


@dataclass
class RestoreActions:
    """What a restore will do, computed from the backup and the device's current state."""

    delete_files: List[str] = field(default_factory=list)
    delete_dirs: List[str] = field(default_factory=list)
    make_dirs: List[str] = field(default_factory=list)
    write_files: List[Entry] = field(default_factory=list)
    unchanged: int = 0
    overwritten: int = 0

    @property
    def write_bytes(self) -> int:
        return sum(entry.size for entry in self.write_files)


def _device_state(fs: DeviceFs, inventory: Inventory) -> Dict[str, bool]:
    """Return ``{path: is_dir}`` for everything currently below the backed-up mounts."""
    present = {mount.path for mount in fs.mounts()}
    state: Dict[str, bool] = {}
    for mount in inventory.mounts:
        if mount.path not in present:
            raise MPFlashError(f"The board has no {mount.path} filesystem, which the backup contains")
        state.update({entry.path: entry.is_dir for entry in _walk(fs, mount, present - {mount.path})})
    return state


def _plan(fs: DeviceFs, inventory: Inventory) -> RestoreActions:
    device = _device_state(fs, inventory)
    wanted_files = inventory.files
    wanted_dirs = inventory.dirs
    actions = RestoreActions()

    for path in sorted(device, key=lambda p: (-p.count("/"), p)):
        wanted_as_dir = path in wanted_dirs
        wanted_as_file = path in wanted_files
        if device[path]:
            if not wanted_as_dir:
                actions.delete_dirs.append(path)
        elif not wanted_as_file:
            actions.delete_files.append(path)
    # Files under a directory that is being removed are listed too, so removal can go bottom-up.

    existing_dirs = {p for p, is_dir in device.items() if is_dir and p in wanted_dirs}
    actions.make_dirs = sorted((p for p in wanted_dirs if p not in existing_dirs), key=lambda p: (p.count("/"), p))
    for path, entry in sorted(wanted_files.items()):
        if device.get(path) is False:
            actions.overwritten += 1
            if fs.sha256(path, entry.size) == entry.sha256:
                actions.unchanged += 1
                continue
        actions.write_files.append(entry)
    return actions


def _check_fits(fs: DeviceFs, inventory: Inventory) -> None:
    for mount in inventory.mounts:
        needed = sum(e.size for e in inventory.entries if not e.is_dir and inventory.mount_for(e.path) == mount)
        total = fs.capacity(mount.path)
        if total and needed > total * MAX_FILL:
            raise MPFlashError(f"The backup's {needed} bytes do not fit the {total}-byte filesystem at {mount.path}")


def _describe(actions: RestoreActions, inventory: Inventory) -> List[str]:
    mounts = ", ".join(mount.path for mount in inventory.mounts)
    lines = [f"mirror the backed-up filesystem ({mounts}): {len(inventory.files)} files, {len(inventory.dirs)} directories"]
    lines.append(
        f"write {len(actions.write_files)} files ({actions.write_bytes} bytes); {actions.unchanged} identical files are left alone"
    )
    if actions.overwritten - actions.unchanged:
        lines.append(f"overwrite {actions.overwritten - actions.unchanged} existing files")
    if actions.make_dirs:
        lines.append(f"create {len(actions.make_dirs)} directories")
    if actions.delete_files or actions.delete_dirs:
        shown = ", ".join((actions.delete_files + actions.delete_dirs)[:_SHOWN_PATHS])
        more = len(actions.delete_files) + len(actions.delete_dirs) - _SHOWN_PATHS
        lines.append(
            f"DELETE {len(actions.delete_files)} files and {len(actions.delete_dirs)} directories not in the backup: "
            f"{shown}{f' and {more} more' if more > 0 else ''}"
        )
    return lines


# ---------------------------------------------------------------------------
# Loading and validating a bundle's VFS data
# ---------------------------------------------------------------------------


def _valid_device_path(path: Any) -> bool:
    """Whether ``path`` can be stored in a bundle and restored identically on every host OS.

    Backslashes are rejected because ``zipfile`` rewrites them to ``/`` on Windows only, so such a
    name would back up on Linux but fail validation on Windows.
    """
    return (
        isinstance(path, str)
        and path.startswith("/")
        and path != "/"
        and "//" not in path
        and "\\" not in path
        and not path.endswith("/")
        and not _CONTROL.search(path)
        and all(part not in (".", "..") for part in path.split("/")[1:])
    )


def _parse_inventory(text: str) -> Inventory:
    try:
        data = json.loads(text)
        if data["schema"] != INVENTORY_SCHEMA:
            raise MPFlashError(f"Unsupported VFS inventory schema {data['schema']!r}")
        mounts = tuple(Mount(str(m["path"]), str(m["fstype"])) for m in data["mounts"] if m["included"] is True)
        entries: List[Entry] = []
        for raw in data["entries"]:
            if not _valid_device_path(raw["path"]):
                raise MPFlashError(f"Unsafe path in VFS inventory: {raw['path']!r}")
            if raw["type"] == "dir":
                entries.append(Entry(raw["path"], True))
            elif raw["type"] == "file":
                size, digest = raw["size"], raw["sha256"]
                if not isinstance(size, int) or isinstance(size, bool) or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
                    raise MPFlashError(f"Invalid size or hash for {raw['path']!r} in the VFS inventory")
                entries.append(Entry(raw["path"], False, size, digest))
            else:
                raise MPFlashError(f"Unknown entry type {raw['type']!r} in the VFS inventory")
    except (KeyError, TypeError, ValueError) as error:
        raise MPFlashError(f"The VFS inventory is malformed: {error!r}") from error

    inventory = Inventory(mounts=mounts, entries=tuple(entries))
    if not mounts:
        raise MPFlashError("The VFS inventory lists no restorable mount")
    paths = [entry.path for entry in entries]
    if len(set(paths)) != len(paths):
        raise MPFlashError("The VFS inventory lists a path more than once")
    dirs = inventory.dirs
    for entry in entries:
        mount = inventory.mount_for(entry.path)
        if mount is None:
            raise MPFlashError(f"{entry.path} is not inside a backed-up mount")
        parent = posixpath.dirname(entry.path)
        if parent != mount.path and parent not in dirs:
            raise MPFlashError(f"{entry.path} has no parent directory in the VFS inventory")
        if entry.path == mount.path:
            raise MPFlashError(f"{entry.path} is a mount point, not an entry")
    return inventory


def _load(bundle: Bundle, artifacts: Sequence[Artifact]) -> Tuple[Inventory, Dict[str, bytes]]:
    """Return the inventory and the file contents, after cross-checking the archive against it."""
    by_path = {artifact.path: artifact for artifact in artifacts}
    zip_artifact = by_path.get(f"artifacts/{ZIP_NAME}")
    inventory_artifact = by_path.get(f"artifacts/{INVENTORY_NAME}")
    if zip_artifact is None or inventory_artifact is None:
        raise MPFlashError(f"The bundle's VFS data is incomplete: {ZIP_NAME} and {INVENTORY_NAME} are both required")
    inventory = _parse_inventory(bundle.artifact_path(inventory_artifact).read_text(encoding="utf-8"))

    contents: Dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(bundle.artifact_path(zip_artifact)) as archive:
            members = {info.filename: info for info in archive.infolist()}
            if len(members) != len(archive.infolist()):
                raise MPFlashError("The VFS archive contains duplicate entries")
            expected = {_member_name(e.path, e.is_dir): e for e in inventory.entries}
            if set(members) != set(expected):
                extra = sorted(set(members) ^ set(expected))[:_SHOWN_PATHS]
                raise MPFlashError(f"The VFS archive does not match its inventory (e.g. {', '.join(extra)})")
            for name, entry in expected.items():
                if entry.is_dir:
                    continue
                if members[name].file_size != entry.size:
                    raise MPFlashError(f"{entry.path} has {members[name].file_size} bytes in the archive but {entry.size} in the inventory")
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != entry.sha256:
                    raise MPFlashError(f"{entry.path} does not match its recorded SHA-256")
                contents[entry.path] = data
    except zipfile.BadZipFile as error:
        raise MPFlashError(f"The VFS archive is not a valid ZIP file: {error}") from error
    return inventory, contents


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class VfsProvider(BackupProvider):
    """Back up and restore the writable MicroPython filesystem over the serial REPL."""

    name = "mpremote-vfs"
    priority = 0

    def __init__(self, opener: Opener = open_device_fs):
        self._open = opener

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        if not getattr(mcu, "connected", False) or getattr(mcu, "family", "") != "micropython":
            return ()
        return (
            ProviderCapability(
                component=ComponentKind.VFS,
                can_backup=True,
                can_restore=True,
                exactness=Exactness.LOGICAL,
                exclusions=EXCLUSIONS,
            ),
        )

    def backup(self, mcu: Any, component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        writer = ctx.writer
        notes: List[str] = []
        entries: List[Entry] = []
        skipped: Dict[str, str] = {}
        capacities: Dict[str, int] = {}
        zip_path = writer.artifact_path(ZIP_NAME)

        with self._open(mcu.serialport, soft_reset=True) as fs:
            mounts = fs.mounts()
            all_mounts = {mount.path for mount in mounts}
            included = []
            for mount in mounts:
                reason = _is_backed_up(mount)
                if reason:
                    skipped[mount.path] = reason
                    notes.append(f"Skipped {mount.path}: {reason}.")
                else:
                    included.append(mount)
            if not included:
                raise MPFlashError("The board has no writable filesystem to back up")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for mount in included:
                    total = fs.capacity(mount.path)
                    if total:
                        capacities[mount.path] = total
                    for entry in _walk(fs, mount, all_mounts - {mount.path}):
                        if not _valid_device_path(entry.path):
                            raise MPFlashError(
                                f"{entry.path!r} cannot be stored portably in a backup (backslash or control character in the name); "
                                "rename or delete it and run the backup again"
                            )
                        if entry.is_dir:
                            _add_dir(archive, entry.path)
                            entries.append(entry)
                            continue
                        data = fs.read_file(entry.path)
                        digest = hashlib.sha256(data).hexdigest()
                        if fs.sha256(entry.path, len(data)) != digest:
                            raise MPFlashError(f"{entry.path} was corrupted or changed while it was being read")
                        _add_file(archive, entry.path, data)
                        entries.append(Entry(entry.path, False, len(data), digest))

        writer.artifact_path(INVENTORY_NAME).write_text(
            _inventory_json(mounts, skipped, entries, capacities), encoding="utf-8", newline="\n"
        )
        for filename in (ZIP_NAME, INVENTORY_NAME):
            writer.register_artifact(
                filename,
                component=ComponentKind.VFS,
                role=ArtifactRole.LOGICAL_FILES,
                exactness=Exactness.LOGICAL,
                provider=self.name,
                exclusions=EXCLUSIONS,
            )
        files = sum(1 for entry in entries if not entry.is_dir)
        notes.insert(0, f"VFS: {files} files and {len(entries) - files} directories from {', '.join(mount_table_summary(included))}.")
        tree, tree_note = _device_tree(mcu)
        if tree_note:
            notes.append(tree_note)
        return BackupOutput(tree_text=tree, notes=tuple(notes))

    def describe_restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> Sequence[str]:
        inventory, _ = _load(bundle, artifacts)
        with self._open(mcu.serialport, soft_reset=False) as fs:
            _check_fits(fs, inventory)
            return _describe(_plan(fs, inventory), inventory)

    def restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> None:
        inventory, contents = _load(bundle, artifacts)
        with self._open(mcu.serialport, soft_reset=True) as fs:
            _check_fits(fs, inventory)
            actions = _plan(fs, inventory)
            for path in actions.delete_files:
                fs.remove_file(path)
            for path in actions.delete_dirs:
                fs.remove_dir(path)
            for path in actions.make_dirs:
                fs.mkdir(path)
            for entry in actions.write_files:
                log.debug(f"Writing {entry.path} ({entry.size} bytes)")
                fs.write_file(entry.path, contents[entry.path])
                if fs.sha256(entry.path, entry.size) != entry.sha256:
                    raise MPFlashError(f"{entry.path} did not verify after writing")
            self._verify_tree(fs, inventory)
        self._restart(mcu)

    @staticmethod
    def _verify_tree(fs: DeviceFs, inventory: Inventory) -> None:
        state = _device_state(fs, inventory)
        expected = {entry.path: entry.is_dir for entry in inventory.entries}
        if state != expected:
            difference = sorted(set(state.items()) ^ set(expected.items()))[:_SHOWN_PATHS]
            raise MPFlashError(f"The restored filesystem differs from the backup (e.g. {difference})")

    @staticmethod
    def _restart(mcu: Any) -> None:
        """Reset so the restored boot.py/main.py take effect, and make sure the board comes back."""
        mcu.run_command("reset", timeout=10, log_errors=False)
        mcu.connected = False
        if not mcu.wait_for_restart(timeout=20):
            log.warning(f"{mcu.serialport} did not reconnect after the restore; the files were verified before the reset")


def _add_dir(archive: zipfile.ZipFile, path: str) -> None:
    info = zipfile.ZipInfo(_member_name(path, True), _ZIP_TIME)
    info.external_attr = (0o40755 << 16) | 0x10
    archive.writestr(info, b"")


def _add_file(archive: zipfile.ZipFile, path: str, data: bytes) -> None:
    info = zipfile.ZipInfo(_member_name(path, False), _ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


register(VfsProvider())
