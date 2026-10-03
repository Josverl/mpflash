"""VFS provider: backup, mirror restore and validation of untrusted bundles."""

import hashlib
import io
import json
import os
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pytest
from fake_device import FakeDeviceFs, fake_mcu

from mpflash.backup import registry
from mpflash.backup.builtins.vfs import INVENTORY_NAME, ZIP_NAME, VfsProvider
from mpflash.backup.bundle import BundleWriter, read_bundle
from mpflash.backup.devicefs import Mount
from mpflash.backup.models import ArtifactRole, ComponentKind, DeviceIdentity, Exactness
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError

VFS = ComponentKind.VFS
NOW = datetime(2026, 10, 3, 21, 0, 0, tzinfo=timezone.utc)
SAMPLE = {"/main.py": b"print('hi')\n", "/lib/util.py": b"x = 1\n", "/lib/deep/data.bin": bytes(range(256))}


@pytest.fixture
def mcu():
    return fake_mcu()


@pytest.fixture
def device(isolated_registry):
    """A board with a small filesystem, registered through a VFS provider."""
    fake = FakeDeviceFs(SAMPLE, dirs={"/lib", "/lib/deep"})
    registry.register(VfsProvider(opener=fake.opener()))
    return fake


def backup(mcu, out: Path, **options) -> Path:
    return run_backup(mcu, plan_backup(mcu, [VFS]), out, now=NOW, **options)


def archive_names(bundle_root: Path) -> Dict[str, bytes]:
    with zipfile.ZipFile(bundle_root / "artifacts" / ZIP_NAME) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def inventory(bundle_root: Path) -> dict:
    return json.loads((bundle_root / "artifacts" / INVENTORY_NAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_provider_offers_restorable_logical_backup_for_micropython(mcu):
    (capability,) = VfsProvider().capabilities(mcu)

    assert (capability.component, capability.can_backup, capability.can_restore) == (VFS, True, True)
    assert capability.exactness is Exactness.LOGICAL
    assert any("ROMFS" in text for text in capability.exclusions)


@pytest.mark.parametrize("overrides", [{"family": "circuitpython"}, {"family": "unknown"}, {"connected": False}])
def test_provider_does_not_apply_to_other_boards(overrides):
    assert VfsProvider().capabilities(fake_mcu(**overrides)) == ()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def test_backup_archives_every_file_and_directory(device, mcu, tmp_path):
    root = backup(mcu, tmp_path)

    assert archive_names(root) == {
        "lib/": b"",
        "lib/deep/": b"",
        "main.py": SAMPLE["/main.py"],
        "lib/util.py": SAMPLE["/lib/util.py"],
        "lib/deep/data.bin": SAMPLE["/lib/deep/data.bin"],
    }
    files = {e["path"]: e for e in inventory(root)["entries"] if e["type"] == "file"}
    assert files["/lib/util.py"]["sha256"] == hashlib.sha256(SAMPLE["/lib/util.py"]).hexdigest()
    assert files["/lib/deep/data.bin"]["size"] == 256


def test_backup_artifacts_are_logical_and_declare_exclusions(device, mcu, tmp_path):
    bundle = read_bundle(backup(mcu, tmp_path))

    assert sorted(a.path for a in bundle.manifest.artifacts) == [f"artifacts/{INVENTORY_NAME}", f"artifacts/{ZIP_NAME}"]
    for artifact in bundle.manifest.artifacts:
        assert (artifact.role, artifact.exactness, artifact.component) == (ArtifactRole.LOGICAL_FILES, Exactness.LOGICAL, VFS)
        assert artifact.exclusions
    bundle.verify()


def test_backup_is_deterministic(device, mcu, tmp_path):
    first = backup(mcu, tmp_path / "a")
    second = backup(mcu, tmp_path / "b")

    assert (first / "artifacts" / ZIP_NAME).read_bytes() == (second / "artifacts" / ZIP_NAME).read_bytes()


def test_backup_stops_the_application_first(device, mcu, tmp_path):
    backup(mcu, tmp_path)

    assert device.soft_resets == [True]


def test_backup_skips_read_only_rom_and_removable_storage(isolated_registry, mcu, tmp_path):
    fake = FakeDeviceFs(
        {"/main.py": b"a", "/rom/app.mpy": b"rom", "/sd/photo.jpg": b"sd"},
        mounts=[Mount("/rom", "VfsRom"), Mount("/", "VfsLfs2"), Mount("/sd", "VfsFat")],
    )
    registry.register(VfsProvider(opener=fake.opener()))

    root = backup(mcu, tmp_path)

    assert list(archive_names(root)) == ["main.py"]
    mounts = {m["path"]: m for m in inventory(root)["mounts"]}
    assert mounts["/rom"]["included"] is False and "ROMFS" in mounts["/rom"]["reason"]
    assert mounts["/sd"]["included"] is False and "removable" in mounts["/sd"]["reason"]
    notes = (root / "README.md").read_text(encoding="utf-8")
    assert "Skipped /rom" in notes and "Skipped /sd" in notes


def test_backup_does_not_cross_into_other_included_mounts(isolated_registry, mcu, tmp_path):
    fake = FakeDeviceFs({"/boot.py": b"b", "/flash/main.py": b"m"}, mounts=[Mount("/", "VfsPosix"), Mount("/flash", "VfsLfs2")])
    registry.register(VfsProvider(opener=fake.opener()))

    root = backup(mcu, tmp_path)

    paths = [e["path"] for e in inventory(root)["entries"]]
    assert sorted(paths) == ["/boot.py", "/flash/main.py"]


def test_empty_filesystem_makes_a_valid_bundle(isolated_registry, mcu, tmp_path):
    registry.register(VfsProvider(opener=FakeDeviceFs().opener()))

    root = backup(mcu, tmp_path)

    assert archive_names(root) == {}
    read_bundle(root).verify()


def test_backup_without_a_writable_filesystem_fails(isolated_registry, mcu, tmp_path):
    fake = FakeDeviceFs(mounts=[Mount("/rom", "VfsRom")])
    registry.register(VfsProvider(opener=fake.opener()))

    with pytest.raises(MPFlashError, match="no writable filesystem"):
        backup(mcu, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_backup_detects_corruption_during_reads(device, mcu, tmp_path):
    device.corrupt_reads.add("/main.py")

    with pytest.raises(MPFlashError, match="/main.py was corrupted or changed"):
        backup(mcu, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_vfs_content_is_stored_once_in_the_zip(device, mcu, tmp_path):
    root = backup(mcu, tmp_path)

    assert {entry.name for entry in root.iterdir()} == {"README.md", "manifest.json", "artifacts"}
    assert not any(path.name == "main.py" for path in root.rglob("*"))
    assert archive_names(root)["main.py"] == SAMPLE["/main.py"]


def test_names_the_host_cannot_store_are_kept_in_the_zip(isolated_registry, mcu, tmp_path):
    registry.register(VfsProvider(opener=FakeDeviceFs({"/we:ird.py": b"2", "/sp ace é.py": b"3"}).opener()))

    names = archive_names(backup(mcu, tmp_path))

    assert names["we:ird.py"] == b"2" and names["sp ace é.py"] == b"3"


@pytest.mark.parametrize("name", ["/back\\slash.py", "/ctl\x07.py"])
def test_names_that_cannot_round_trip_on_every_host_fail_the_backup(isolated_registry, mcu, tmp_path, name):
    """zipfile rewrites a backslash to '/' on Windows only, so such a bundle would differ per host."""
    registry.register(VfsProvider(opener=FakeDeviceFs({name: b"x"}).opener()))

    with pytest.raises(MPFlashError, match="cannot be stored portably"):
        backup(mcu, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_bundle_text_files_use_unix_line_endings_on_every_host(device, mcu, tmp_path):
    root = backup(mcu, tmp_path)

    for path in (root / "README.md", root / "manifest.json", root / "artifacts" / INVENTORY_NAME):
        assert b"\r" not in path.read_bytes(), path.name


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_bundle_is_private_on_posix_hosts(device, mcu, tmp_path):
    root = backup(mcu, tmp_path)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "artifacts").stat().st_mode) == 0o700
    for path in (root / "README.md", root / "manifest.json", root / "artifacts" / ZIP_NAME):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name


TREE_OUTPUT = [
    "tree :\n",
    ":/\n",
    "├── [   139]  boot.py\n",
    "└── lib\n",
    "    └── [    24]  boardname.py\n",
]


def with_tree(mcu, output=TREE_OUTPUT, rc=0, on_call=None):
    """Make the board's ``mpremote tree -h`` return ``output`` and everything else succeed."""

    def run_command(command, **kwargs):
        if command[0] != "tree":
            return 0, []
        if on_call:
            on_call()
        return rc, output

    mcu.run_command.side_effect = run_command


def readme(root: Path) -> str:
    return (root / "README.md").read_text(encoding="utf-8")


def test_readme_embeds_the_output_of_mpremote_tree_h_verbatim(device, mcu, tmp_path):
    with_tree(mcu)

    text = readme(backup(mcu, tmp_path))

    assert "```text\n" + "".join(TREE_OUTPUT).rstrip() + "\n```" in text
    assert "VFS: 3 files and 2 directories" in text
    mcu.run_command.assert_any_call(["tree", "-h"], no_info=True, log_errors=False, timeout=60)


def test_tree_is_read_after_the_backup_connection_is_closed(device, mcu, tmp_path):
    open_when_called = []
    with_tree(mcu, on_call=lambda: open_when_called.append(device.open_depth))

    backup(mcu, tmp_path)

    assert open_when_called == [0]  # the port is free for the separate mpremote process


@pytest.mark.parametrize("failure", [{"rc": 1}, {"rc": 1, "output": []}])
def test_a_failing_tree_command_does_not_fail_the_backup(device, mcu, tmp_path, failure):
    with_tree(mcu, on_call=lambda: setattr(mcu, "connected", False), **failure)

    text = readme(backup(mcu, tmp_path))

    assert "mpremote tree failed (exit code 1)" in text and "## Filesystem tree" not in text
    assert mcu.connected is True  # a failed tree command must not mark the board as gone


@pytest.mark.parametrize("error", [TimeoutError("timed out"), RuntimeError("Board reset detected"), FileNotFoundError("mpremote")])
def test_an_erroring_tree_command_does_not_fail_the_backup(device, mcu, tmp_path, error):
    def explode(command, **kwargs):
        if command[0] == "tree":
            raise error
        return 0, []

    mcu.run_command.side_effect = explode

    text = readme(backup(mcu, tmp_path))

    assert "The filesystem tree could not be read" in text and "## Filesystem tree" not in text
    read_bundle(next(tmp_path.iterdir())).verify()


def test_an_empty_tree_adds_no_section(device, mcu, tmp_path):
    assert "## Filesystem tree" not in readme(backup(mcu, tmp_path))


def test_long_trees_are_truncated_with_a_pointer_to_the_inventory(device, mcu, tmp_path):
    with_tree(mcu, output=[f"line {i}\n" for i in range(500)])

    text = readme(backup(mcu, tmp_path))

    assert "line 399" in text and "line 400" not in text
    assert f"... 100 more lines (see {INVENTORY_NAME})" in text


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def damaged() -> FakeDeviceFs:
    """Return a board that differs from the backup in every way a mirror must undo."""
    return FakeDeviceFs(
        {
            "/main.py": SAMPLE["/main.py"],  # identical: must not be rewritten
            "/lib/util.py": b"CHANGED",  # content differs
            "/extra.txt": b"x",  # not in backup
            "/junk/nested/deep.txt": b"y",  # directory tree not in backup
            "/lib/deep": b"a file where the backup has a directory",
        },
        dirs={"/lib", "/junk", "/junk/nested"},
    )


@pytest.fixture
def restore_env(device, mcu, tmp_path, isolated_registry):
    """A backup of ``device`` plus a damaged board registered as the restore target."""
    bundle = read_bundle(backup(mcu, tmp_path))
    target = damaged()
    registry._providers.clear()
    registry.register(VfsProvider(opener=target.opener()))
    return bundle, target


def test_restore_makes_the_board_match_the_backup(restore_env, mcu):
    bundle, target = restore_env

    run_restore(plan_restore(bundle, mcu), mcu)

    assert target.files == SAMPLE
    assert target.dirs == {"/lib", "/lib/deep"}


def test_restore_deletes_before_writing_and_skips_identical_files(restore_env, mcu):
    bundle, target = restore_env

    run_restore(plan_restore(bundle, mcu), mcu)

    ops = target.mutations()
    kinds = [kind for kind, _ in ops]
    assert kinds.index("write") > max(i for i, kind in enumerate(kinds) if kind in ("rm", "rmdir"))
    assert ("write", "/main.py") not in ops
    assert ("write", "/lib/util.py") in ops
    removed_dirs = [path for kind, path in ops if kind == "rmdir"]
    assert removed_dirs == ["/junk/nested", "/junk"]  # deepest first


def test_restore_replaces_a_file_that_blocks_a_directory(restore_env, mcu):
    bundle, target = restore_env

    run_restore(plan_restore(bundle, mcu), mcu)

    assert ("rm", "/lib/deep") in target.mutations() and ("mkdir", "/lib/deep") in target.mutations()


def test_restore_replaces_a_directory_that_blocks_a_file(device, mcu, tmp_path):
    bundle = read_bundle(backup(mcu, tmp_path))
    target = FakeDeviceFs({"/main.py/inner.txt": b"x"}, dirs={"/main.py", "/lib", "/lib/deep"})
    registry._providers.clear()
    registry.register(VfsProvider(opener=target.opener()))

    run_restore(plan_restore(bundle, mcu), mcu)

    assert target.files == SAMPLE and "/main.py" not in target.dirs


def test_restore_resets_the_board_so_restored_scripts_run(restore_env, mcu):
    bundle, _ = restore_env

    run_restore(plan_restore(bundle, mcu), mcu)

    mcu.run_command.assert_any_call("reset", timeout=10, log_errors=False)
    mcu.wait_for_restart.assert_called_once_with(timeout=20)


def test_restore_succeeds_even_if_the_board_is_slow_to_return(restore_env, mcu):
    bundle, target = restore_env
    mcu.wait_for_restart.return_value = False

    run_restore(plan_restore(bundle, mcu), mcu)

    assert target.files == SAMPLE


def test_dry_run_plan_reports_each_action_without_changing_anything(restore_env, mcu):
    bundle, target = restore_env
    before = (dict(target.files), set(target.dirs))

    plan = plan_restore(bundle, mcu)

    text = "\n".join(plan.lines)
    assert "mirror the backed-up filesystem (/): 3 files, 2 directories" in text
    assert "write 2 files" in text and "1 identical files are left alone" in text
    assert "DELETE 3 files and 2 directories" in text and "/extra.txt" in text
    assert target.mutations() == [] and (target.files, target.dirs) == before
    assert target.soft_resets == [False]  # inspection leaves the interpreter alone


def test_plan_truncates_long_delete_lists(device, mcu, tmp_path):
    bundle = read_bundle(backup(mcu, tmp_path))
    target = FakeDeviceFs({**SAMPLE, **{f"/junk{i}.txt": b"x" for i in range(12)}}, dirs={"/lib", "/lib/deep"})
    registry._providers.clear()
    registry.register(VfsProvider(opener=target.opener()))

    text = "\n".join(plan_restore(bundle, mcu).lines)

    assert "DELETE 12 files and 0 directories" in text and "and 7 more" in text


def test_restore_detects_a_file_that_fails_verification(restore_env, mcu):
    bundle, target = restore_env
    target.corrupt_writes.add("/lib/util.py")

    with pytest.raises(MPFlashError, match="/lib/util.py did not verify after writing"):
        run_restore(plan_restore(bundle, mcu), mcu)


def test_restore_reports_write_failures_with_progress(restore_env, mcu):
    bundle, target = restore_env
    target.fail_writes.add("/lib/util.py")

    with pytest.raises(MPFlashError, match="Restore of vfs by mpremote-vfs failed: No space left on device"):
        run_restore(plan_restore(bundle, mcu), mcu)


def test_restore_requires_the_backed_up_mount(device, mcu, tmp_path):
    bundle = read_bundle(backup(mcu, tmp_path))
    registry._providers.clear()
    registry.register(VfsProvider(opener=FakeDeviceFs(mounts=[Mount("/flash", "VfsLfs2")]).opener()))

    with pytest.raises(MPFlashError, match="no / filesystem"):
        plan_restore(bundle, mcu)


def test_restore_refuses_a_backup_that_cannot_fit(device, mcu, tmp_path):
    bundle = read_bundle(backup(mcu, tmp_path))
    registry._providers.clear()
    registry.register(VfsProvider(opener=FakeDeviceFs(capacity=100).opener()))

    with pytest.raises(MPFlashError, match="do not fit the 100-byte filesystem"):
        plan_restore(bundle, mcu)


def test_restore_never_touches_mounts_outside_the_backup(isolated_registry, mcu, tmp_path):
    source = FakeDeviceFs({"/main.py": b"m"}, mounts=[Mount("/", "VfsLfs2")])
    registry.register(VfsProvider(opener=source.opener()))
    bundle = read_bundle(backup(mcu, tmp_path))
    target = FakeDeviceFs(
        {"/main.py": b"old", "/sd/keep.jpg": b"precious", "/rom/app.mpy": b"rom"},
        mounts=[Mount("/rom", "VfsRom"), Mount("/", "VfsLfs2"), Mount("/sd", "VfsFat")],
    )
    registry._providers.clear()
    registry.register(VfsProvider(opener=target.opener()))

    run_restore(plan_restore(bundle, mcu), mcu)

    assert target.files["/main.py"] == b"m"
    assert target.files["/sd/keep.jpg"] == b"precious" and target.files["/rom/app.mpy"] == b"rom"


# ---------------------------------------------------------------------------
# untrusted bundles (hashes are valid, so only the provider can notice)
# ---------------------------------------------------------------------------


def craft(
    tmp_path: Path,
    mcu,
    entries,
    members: Optional[Dict[str, bytes]] = None,
    *,
    mounts=None,
    schema: int = 1,
    inventory_text: Optional[str] = None,
    zip_bytes: Optional[bytes] = None,
    skip: Optional[str] = None,
):
    """Build a bundle whose files are hash-valid but whose content may be hostile."""
    members = members if members is not None else {}
    if zip_bytes is None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        zip_bytes = buffer.getvalue()
    if inventory_text is None:
        inventory_text = json.dumps(
            {
                "schema": schema,
                "mounts": mounts if mounts is not None else [{"path": "/", "fstype": "VfsLfs2", "included": True, "reason": ""}],
                "entries": entries,
            }
        )
    with BundleWriter(tmp_path, "crafted") as writer:
        for filename, payload in ((ZIP_NAME, zip_bytes), (INVENTORY_NAME, inventory_text.encode())):
            if filename == skip:
                continue
            writer.add_artifact_bytes(
                filename,
                payload,
                component=VFS,
                role=ArtifactRole.LOGICAL_FILES,
                exactness=Exactness.LOGICAL,
                provider="mpremote-vfs",
            )
        root = writer.commit(DeviceIdentity.from_mcu(mcu))
    return read_bundle(root)


def file_entry(path="/a.txt", data=b"a", **override):
    entry = {"path": path, "type": "file", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    entry.update(override)
    return entry


@pytest.fixture
def blank_board(isolated_registry):
    fake = FakeDeviceFs()
    registry.register(VfsProvider(opener=fake.opener()))
    return fake


def test_crafted_valid_bundle_is_accepted(blank_board, mcu, tmp_path):
    bundle = craft(tmp_path, mcu, [file_entry()], {"a.txt": b"a"})

    run_restore(plan_restore(bundle, mcu), mcu)

    assert blank_board.files == {"/a.txt": b"a"}


@pytest.mark.parametrize(
    "path",
    ["/../etc/passwd", "/a/../b", "/a/./b", "relative.txt", "//double", "/trailing/", "/ctl\x07", "/", "/back\\slash"],
)
def test_unsafe_inventory_paths_are_rejected(blank_board, mcu, tmp_path, path):
    bundle = craft(tmp_path, mcu, [file_entry(path)], {})

    with pytest.raises(MPFlashError, match="Unsafe path|malformed"):
        plan_restore(bundle, mcu)


@pytest.mark.parametrize(
    "entries, members, message",
    [
        ([file_entry("/d/a.txt")], {"d/a.txt": b"a"}, "no parent directory"),
        ([file_entry(), file_entry()], {"a.txt": b"a"}, "more than once"),
        ([file_entry()], {}, "does not match its inventory"),
        ([file_entry()], {"a.txt": b"a", "evil.txt": b"e"}, "does not match its inventory"),
        ([file_entry()], {"a.txt": b"WRONG"}, "has 5 bytes in the archive but 1 in the inventory"),
        ([file_entry(sha256="0" * 64)], {"a.txt": b"a"}, "does not match its recorded SHA-256"),
        ([file_entry(sha256="nothex")], {"a.txt": b"a"}, "Invalid size or hash"),
        ([file_entry(size=-1)], {"a.txt": b"a"}, "Invalid size or hash"),
        ([{"path": "/a.txt", "type": "symlink"}], {}, "Unknown entry type"),
        ([file_entry("/sd/x.txt")], {"sd/x.txt": b"a"}, "no parent directory|not inside"),
    ],
)
def test_inconsistent_inventories_are_rejected(blank_board, mcu, tmp_path, entries, members, message):
    bundle = craft(tmp_path, mcu, entries, members)

    with pytest.raises(MPFlashError, match=message):
        plan_restore(bundle, mcu)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"schema": 2}, "Unsupported VFS inventory schema"),
        ({"inventory_text": "{not json"}, "malformed"),
        ({"inventory_text": json.dumps({"schema": 1})}, "malformed"),
        ({"mounts": [{"path": "/rom", "fstype": "VfsRom", "included": False, "reason": "rom"}]}, "no restorable mount"),
        ({"zip_bytes": b"not a zip"}, "not a valid ZIP"),
    ],
)
def test_malformed_vfs_data_is_rejected(blank_board, mcu, tmp_path, kwargs, message):
    bundle = craft(tmp_path, mcu, [], {}, **kwargs)

    with pytest.raises(MPFlashError, match=message):
        plan_restore(bundle, mcu)


def test_bundle_missing_one_vfs_file_is_rejected(blank_board, mcu, tmp_path):
    bundle = craft(tmp_path, mcu, [], {}, skip=ZIP_NAME)

    with pytest.raises(MPFlashError, match="VFS data is incomplete"):
        plan_restore(bundle, mcu)
