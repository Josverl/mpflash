"""Capability negotiation, backup planning/execution and restore planning/execution."""

import json
from datetime import datetime, timezone

import pytest
from backup_helpers import capability

from mpflash.backup.bundle import BundleWriter, read_bundle
from mpflash.backup.models import ArtifactRole, ComponentKind, DeviceIdentity, Exactness
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError

FLASH, VFS, ROMFS = ComponentKind.FLASH, ComponentKind.VFS, ComponentKind.ROMFS
NOW = datetime(2026, 10, 3, 21, 0, 0, tzinfo=timezone.utc)


def backup_to(tmp_path, mcu, components=(), **options):
    plan = plan_backup(mcu, components)
    return run_backup(mcu, plan, tmp_path / "out", now=NOW, **options)


# ---------------------------------------------------------------------------
# plan_backup
# ---------------------------------------------------------------------------


def test_auto_backup_selects_every_restorable_component_in_order(full_provider, mcu):
    plan = plan_backup(mcu)

    assert [capability.component for _, capability in plan.selections] == [FLASH, VFS, ROMFS]
    assert plan.device.board_id == "ESP32_GENERIC"


def test_auto_backup_skips_read_only_components_and_says_so(isolated_registry, mcu):
    isolated_registry(capability(VFS), capability(FLASH, can_restore=False))

    plan = plan_backup(mcu)

    assert [capability.component for _, capability in plan.selections] == [VFS]
    assert any("flash can be read but not restored" in note for note in plan.notes)


def test_explicit_read_only_component_is_allowed_with_a_note(isolated_registry, mcu):
    isolated_registry(capability(FLASH, can_restore=False))

    plan = plan_backup(mcu, [FLASH])

    assert len(plan.selections) == 1
    assert any("cannot restore it" in note for note in plan.notes)


def test_explicit_unsupported_component_fails_instead_of_degrading(isolated_registry, mcu):
    isolated_registry(capability(VFS))

    with pytest.raises(MPFlashError, match="No backup provider can read flash.*vfs via fake"):
        plan_backup(mcu, [FLASH])


def test_backup_without_any_provider_fails_explicitly(isolated_registry, mcu):
    with pytest.raises(MPFlashError, match="No backup provider supports esp32 ESP32_GENERIC"):
        plan_backup(mcu)


def test_backup_requires_an_identified_board(full_provider, mcu):
    mcu.board_id = ""

    with pytest.raises(MPFlashError, match="Cannot identify the board"):
        plan_backup(mcu)


def test_higher_priority_provider_wins(isolated_registry, mcu):
    isolated_registry(capability(VFS), name="low", priority=0)
    isolated_registry(capability(VFS), name="high", priority=10)

    plan = plan_backup(mcu, [VFS])

    assert plan.selections[0][0].name == "high"


def test_unavailable_and_failing_providers_are_ignored(isolated_registry, mcu, monkeypatch):
    broken = isolated_registry(capability(VFS), name="broken")
    missing = isolated_registry(capability(FLASH), name="missing")
    working = isolated_registry(capability(VFS), name="working", priority=-1)
    monkeypatch.setattr(broken, "capabilities", lambda board: 1 / 0)
    monkeypatch.setattr(missing, "is_available", lambda: False)

    plan = plan_backup(mcu)

    assert [provider.name for provider, _ in plan.selections] == [working.name]


# ---------------------------------------------------------------------------
# run_backup
# ---------------------------------------------------------------------------


def test_run_backup_publishes_a_verified_bundle(full_provider, mcu, tmp_path):
    root = backup_to(tmp_path, mcu)

    assert root.name == "ESP32_GENERIC-esp32-20261003T210000Z"
    bundle = read_bundle(root)
    bundle.verify()
    assert {artifact.component for artifact in bundle.manifest.artifacts} == {FLASH, VFS, ROMFS}
    flash = next(artifact for artifact in bundle.manifest.artifacts if artifact.component is FLASH)
    assert (flash.address, flash.length, flash.covers, flash.exclusions) == (0, 16, (ROMFS,), ("eFuses",))
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "tree of vfs" in readme and "vfs note" in readme


def test_run_backup_passes_files_option_to_providers(full_provider, mcu, tmp_path):
    root = backup_to(tmp_path, mcu, [VFS], include_files=True)

    assert full_provider.contexts[0].include_files is True
    assert (root / "files" / "main.py").exists()
    assert read_bundle(root).manifest.files_tree == "files"


def test_run_backup_leaves_nothing_behind_when_a_provider_fails(isolated_registry, mcu, tmp_path):
    isolated_registry(capability(VFS), fail_backup=True)

    with pytest.raises(MPFlashError, match="Backup of vfs by fake failed: device unreachable. No backup was created."):
        backup_to(tmp_path, mcu)

    assert list((tmp_path / "out").iterdir()) == []


@pytest.mark.parametrize(
    "component, option, message",
    [
        (FLASH, {"lie_exactness": True}, "declared exact but staged partial"),
        (VFS, {"skip_artifact": True}, "produced no vfs artifact"),
    ],
)
def test_run_backup_rejects_providers_that_misreport(isolated_registry, mcu, tmp_path, component, option, message):
    isolated_registry(capability(component), **option)

    with pytest.raises(MPFlashError, match=message):
        backup_to(tmp_path, mcu)

    assert list((tmp_path / "out").iterdir()) == []


def test_run_backup_rejects_artifacts_that_omit_declared_exclusions(isolated_registry, mcu, tmp_path):
    isolated_registry(capability(FLASH, exclusions=("eFuses",)), omit_exclusions=True)

    with pytest.raises(MPFlashError, match="omitted declared exclusions"):
        backup_to(tmp_path, mcu)


# ---------------------------------------------------------------------------
# plan_restore
# ---------------------------------------------------------------------------


@pytest.fixture
def bundle(full_provider, mcu, tmp_path):
    return read_bundle(backup_to(tmp_path, mcu))


def test_restore_plan_lists_every_write_without_touching_the_device(bundle, full_provider, mcu):
    plan = plan_restore(bundle, mcu)

    assert [item.component for item in plan.items] == [FLASH, VFS]
    assert any(line.startswith("[flash] write artifacts/flash.bin") for line in plan.lines)
    assert full_provider.restored == []


def test_auto_restore_skips_components_contained_in_the_raw_image(bundle, mcu):
    plan = plan_restore(bundle, mcu)

    assert ROMFS not in [item.component for item in plan.items]
    assert any("romfs is part of the raw flash image" in warning for warning in plan.warnings)


def test_explicit_restore_of_covered_component_with_its_image_is_rejected(bundle, mcu):
    with pytest.raises(MPFlashError, match="already contains it"):
        plan_restore(bundle, mcu, [FLASH, ROMFS])


def test_individual_components_can_be_restored_alone(bundle, mcu):
    plan = plan_restore(bundle, mcu, [ROMFS])

    assert [item.component for item in plan.items] == [ROMFS]


def test_restore_rejects_a_component_missing_from_the_bundle(isolated_registry, mcu, tmp_path):
    isolated_registry(capability(VFS))
    only_vfs = read_bundle(backup_to(tmp_path, mcu))

    with pytest.raises(MPFlashError, match="no restorable flash data"):
        plan_restore(only_vfs, mcu, [FLASH])


def test_restore_rejects_a_different_board(bundle, mcu):
    mcu.port = "rp2"
    mcu.board_id = "RPI_PICO"
    mcu.cpu = "RP2040"

    with pytest.raises(MPFlashError, match=r"(?s)does not match the target board.*port.*board_id.*cpu"):
        plan_restore(bundle, mcu)


def test_restore_warns_when_serial_number_differs(bundle, mcu):
    mcu.serial_number = "BBB"

    plan = plan_restore(bundle, mcu)

    assert any("different physical board" in warning for warning in plan.warnings)


def test_restore_rejects_a_tampered_artifact_before_planning(bundle, mcu, full_provider):
    (bundle.root / "artifacts" / "vfs.bin").write_bytes(b"EVIL!")

    with pytest.raises(MPFlashError, match="SHA-256"):
        plan_restore(bundle, mcu)

    assert full_provider.restored == []


def test_restore_surfaces_provider_incompatibility(bundle, mcu, full_provider):
    full_provider.reject_restore = True

    with pytest.raises(MPFlashError, match="flash size differs"):
        plan_restore(bundle, mcu)


def test_restore_requires_a_provider_that_can_write(bundle, mcu, full_provider):
    full_provider._capabilities = [capability(FLASH, can_restore=False)]

    with pytest.raises(MPFlashError, match="No provider can restore flash"):
        plan_restore(bundle, mcu, [FLASH])


def test_restore_prefers_the_provider_that_made_the_bundle(isolated_registry, mcu, tmp_path):
    original = isolated_registry(capability(VFS), name="original", priority=0)
    newer = isolated_registry(capability(VFS), name="newer", priority=10)
    bundle = read_bundle(run_backup(mcu, plan_backup(mcu, [VFS]), tmp_path, now=NOW))
    assert bundle.manifest.artifacts[0].provider == "newer"
    bundle_dir = bundle.root
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"][0]["provider"] = "original"
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    plan = plan_restore(read_bundle(bundle_dir), mcu)

    assert plan.items[0].provider is original
    assert newer.restored == []


def test_reference_only_components_cannot_be_restored(mcu, tmp_path, full_provider):
    with BundleWriter(tmp_path, "ref") as writer:
        writer.add_artifact_bytes(
            "firmware.bin",
            b"fw",
            component=FLASH,
            role=ArtifactRole.REFERENCE,
            exactness=Exactness.REFERENCE,
            provider="reference",
        )
        writer.add_artifact_bytes(
            "vfs.zip", b"files", component=VFS, role=ArtifactRole.LOGICAL_FILES, exactness=Exactness.LOGICAL, provider="fake"
        )
        root = writer.commit(DeviceIdentity.from_mcu(mcu))
    reference_bundle = read_bundle(root)

    with pytest.raises(MPFlashError, match="only holds a reference copy"):
        plan_restore(reference_bundle, mcu, [FLASH])
    assert [item.component for item in plan_restore(reference_bundle, mcu).items] == [VFS]


# ---------------------------------------------------------------------------
# run_restore
# ---------------------------------------------------------------------------


def test_run_restore_writes_raw_flash_before_files(bundle, mcu, full_provider):
    done = run_restore(plan_restore(bundle, mcu), mcu)

    assert done == (FLASH, VFS)
    assert full_provider.restored == [FLASH, VFS]


def test_run_restore_failure_reports_progress_and_remaining_work(bundle, mcu, full_provider):
    full_provider.fail_restore = VFS

    with pytest.raises(MPFlashError) as error:
        run_restore(plan_restore(bundle, mcu), mcu)

    message = str(error.value)
    assert "Restore of vfs by fake failed: write error" in message
    assert "Already restored: flash" in message
    assert "Not completed: vfs" in message


def test_run_restore_first_failure_reports_nothing_restored(bundle, mcu, full_provider):
    full_provider.fail_restore = FLASH

    with pytest.raises(MPFlashError, match="Already restored: nothing. Not completed: flash, vfs"):
        run_restore(plan_restore(bundle, mcu), mcu)
