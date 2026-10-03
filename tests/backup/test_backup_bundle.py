"""Atomic writing, strict reading and verification of backup bundles."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from mpflash.backup.bundle import (
    INCOMPLETE_SUFFIX,
    BundleWriter,
    bundle_name,
    read_bundle,
    render_readme,
)
from mpflash.backup.models import ArtifactRole, ComponentKind, DeviceIdentity, Exactness
from mpflash.errors import MPFlashError

DEVICE = DeviceIdentity(port="esp32", board_id="ESP32_GENERIC", cpu="ESP32", version="1.29.0", serial_number="AAA")
VFS: Dict[str, Any] = dict(component=ComponentKind.VFS, role=ArtifactRole.LOGICAL_FILES, exactness=Exactness.LOGICAL, provider="fake")


def make_bundle(parent: Path, name: str = "bundle", **commit) -> Path:
    with BundleWriter(parent, name) as writer:
        writer.add_artifact_bytes("vfs.zip", b"hello", **VFS)
        return writer.commit(DEVICE, **commit)


def rewrite_manifest(bundle: Path, change) -> None:
    path = bundle / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_writer_publishes_complete_bundle_atomically(tmp_path):
    root = make_bundle(tmp_path, tree_text="/ (tree)", notes=["a note"])

    assert root == tmp_path / "bundle"
    assert not (tmp_path / f"bundle{INCOMPLETE_SUFFIX}").exists()
    assert {entry.name for entry in root.iterdir()} == {"README.md", "manifest.json", "artifacts"}
    bundle = read_bundle(root)
    bundle.verify()
    artifact = bundle.manifest.artifacts[0]
    assert (artifact.path, artifact.size) == ("artifacts/vfs.zip", 5)
    assert bundle.manifest.notes == ("a note",)
    assert bundle.manifest.device == DEVICE


def test_writer_discards_staging_folder_on_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with BundleWriter(tmp_path, "bundle") as writer:
            writer.add_artifact_bytes("vfs.zip", b"hello", **VFS)
            raise RuntimeError("provider crashed")

    assert list(tmp_path.iterdir()) == []


def test_writer_refuses_to_overwrite_existing_backup(tmp_path):
    make_bundle(tmp_path)

    with pytest.raises(MPFlashError, match="already exists"):
        with BundleWriter(tmp_path, "bundle"):
            pass

    assert (tmp_path / "bundle" / "manifest.json").exists()


def test_writer_refuses_stale_incomplete_folder(tmp_path):
    (tmp_path / f"bundle{INCOMPLETE_SUFFIX}").mkdir()

    with pytest.raises(MPFlashError, match="already exists"):
        BundleWriter(tmp_path, "bundle").__enter__()


def test_commit_requires_artifacts(tmp_path):
    with pytest.raises(MPFlashError, match="without artifacts"):
        with BundleWriter(tmp_path, "bundle") as writer:
            writer.commit(DEVICE)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["", "../escape", "a/b", ".hidden", "bad name", f"x{INCOMPLETE_SUFFIX}"])
def test_writer_rejects_unsafe_folder_names(tmp_path, name):
    with pytest.raises(MPFlashError, match="Invalid backup folder name"):
        BundleWriter(tmp_path, name)


@pytest.mark.parametrize("filename", ["a/b.bin", "../x", "a\\b", ""])
def test_artifact_filenames_cannot_contain_folders(tmp_path, filename):
    with BundleWriter(tmp_path, "bundle") as writer:
        with pytest.raises(MPFlashError):
            writer.artifact_path(filename)


def test_register_requires_a_staged_file(tmp_path):
    with BundleWriter(tmp_path, "bundle") as writer:
        with pytest.raises(MPFlashError, match="did not stage"):
            writer.register_artifact("missing.bin", **VFS)


def test_artifact_cannot_be_registered_twice(tmp_path):
    with BundleWriter(tmp_path, "bundle") as writer:
        writer.add_artifact_bytes("vfs.zip", b"hello", **VFS)
        with pytest.raises(MPFlashError, match="registered twice"):
            writer.register_artifact("vfs.zip", **VFS)


def test_add_artifact_copy_records_hash_of_copied_file(tmp_path):
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"firmware")
    with BundleWriter(tmp_path / "out", "bundle") as writer:
        artifact = writer.add_artifact_copy(
            "firmware.bin",
            source,
            component=ComponentKind.FLASH,
            role=ArtifactRole.REFERENCE,
            exactness=Exactness.REFERENCE,
            provider="reference",
        )

    assert artifact.size == 8
    assert not artifact.restorable


def test_files_tree_is_recorded_when_requested(tmp_path):
    with BundleWriter(tmp_path, "bundle") as writer:
        (writer.files_dir() / "main.py").write_text("x", encoding="utf-8")
        writer.add_artifact_bytes("vfs.zip", b"hello", **VFS)
        root = writer.commit(DEVICE)

    assert read_bundle(root).manifest.files_tree == "files"
    assert (root / "files" / "main.py").exists()


def test_reader_rejects_incomplete_folder_name(tmp_path):
    folder = tmp_path / f"bundle{INCOMPLETE_SUFFIX}"
    folder.mkdir()

    with pytest.raises(MPFlashError, match="incomplete backup"):
        read_bundle(folder)


def test_reader_rejects_missing_folder_and_manifest(tmp_path):
    with pytest.raises(MPFlashError, match="not a folder"):
        read_bundle(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(MPFlashError, match="manifest.json is missing"):
        read_bundle(empty)


def test_reader_rejects_invalid_json(tmp_path):
    root = make_bundle(tmp_path)
    (root / "manifest.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(MPFlashError, match="not valid JSON"):
        read_bundle(root)


def test_reader_rejects_manifest_marked_incomplete(tmp_path):
    root = make_bundle(tmp_path)
    rewrite_manifest(root, lambda data: data.update(complete=False))

    with pytest.raises(MPFlashError, match="incomplete"):
        read_bundle(root)


def test_reader_rejects_missing_artifact(tmp_path):
    root = make_bundle(tmp_path)
    (root / "artifacts" / "vfs.zip").unlink()

    with pytest.raises(MPFlashError, match="is missing"):
        read_bundle(root)


@pytest.mark.parametrize("path", ["artifacts/../manifest.json", "/etc/passwd", "..\\x", "other/vfs.zip"])
def test_reader_rejects_manifest_paths_that_escape_the_artifact_folder(tmp_path, path):
    root = make_bundle(tmp_path)
    rewrite_manifest(root, lambda data: data["artifacts"][0].update(path=path))

    with pytest.raises(MPFlashError, match="path"):
        read_bundle(root)


def test_verify_detects_modified_artifact(tmp_path):
    root = make_bundle(tmp_path)
    (root / "artifacts" / "vfs.zip").write_bytes(b"HELLO")

    with pytest.raises(MPFlashError, match="SHA-256"):
        read_bundle(root).verify()


def test_verify_detects_size_change(tmp_path):
    root = make_bundle(tmp_path)
    (root / "artifacts" / "vfs.zip").write_bytes(b"hello world")

    with pytest.raises(MPFlashError, match="has size 11, expected 5"):
        read_bundle(root).verify()


def test_verify_rejects_unlisted_artifact_files(tmp_path):
    root = make_bundle(tmp_path)
    (root / "artifacts" / "extra.bin").write_bytes(b"sneaky")

    with pytest.raises(MPFlashError, match="unlisted artifact"):
        read_bundle(root).verify()


def test_reader_rejects_symlinked_artifacts(tmp_path):
    root = make_bundle(tmp_path)
    target = tmp_path / "outside.bin"
    target.write_bytes(b"hello")
    artifact = root / "artifacts" / "vfs.zip"
    artifact.unlink()
    try:
        os.symlink(target, artifact)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this host")

    with pytest.raises(MPFlashError, match="symbolic link"):
        read_bundle(root)


def test_bundle_name_is_sortable_and_filesystem_safe():
    name = bundle_name(
        DeviceIdentity(port="esp32", board_id="ESP32 GENERIC/S3"),
        now=datetime(2026, 10, 3, 21, 5, 9, tzinfo=timezone.utc),
    )

    assert name == "ESP32_GENERIC_S3-esp32-20261003T210509Z"


def test_readme_documents_security_exclusions_and_restore(tmp_path):
    root = make_bundle(tmp_path, tree_text="/ main.py")
    text = (root / "README.md").read_text(encoding="utf-8")

    assert "# MPFlash backup: ESP32_GENERIC (esp32)" in text
    assert "credentials" in text
    assert "OTP/eFuses" in text
    assert "mpflash restore bundle --serial <PORT> --dry-run" in text
    assert "artifacts/vfs.zip" in text and "logical" in text
    assert "/ main.py" in text


def test_readme_lists_coverage_exclusions_and_escapes_table_cells(tmp_path):
    with BundleWriter(tmp_path, "bundle") as writer:
        writer.add_artifact_bytes(
            "flash.bin",
            b"x" * 4,
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider="fake",
            address=0x10000000,
            length=4,
            covers=(ComponentKind.ROMFS,),
            exclusions=("OTP",),
        )
        root = writer.commit(DeviceIdentity(port="esp32", board_id="A|B", description="pipe | here"))

    text = render_readme(read_bundle(root).manifest, "bundle")

    assert "A\\|B" in text
    assert "0x10000000+0x4" in text
    assert "`artifacts/flash.bin`: OTP" in text
    assert "already contains: romfs" in text
