"""ESP raw flash provider: backup, guarded restore and refusal of unsafe devices."""

import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

import pytest
from fake_device import fake_mcu

from mpflash.backup import registry
from mpflash.backup.builtins import esp
from mpflash.backup.builtins.esp import EspFlashProvider, connect_esptool
from mpflash.backup.bundle import read_bundle
from mpflash.backup.models import ArtifactRole, ComponentKind, Exactness
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError

FLASH, VFS, ROMFS = ComponentKind.FLASH, ComponentKind.VFS, ComponentKind.ROMFS
SIZE = 4096
IMAGE = bytes((i * 7 + 3) % 256 for i in range(SIZE))


class FakeChip:
    """An ESP chip whose flash is a bytearray, recording every operation."""

    def __init__(
        self,
        flash: bytes = IMAGE,
        chip: str = "ESP32",
        size: Optional[int] = None,
        problems: Optional[List[str]] = None,
    ):
        self.flash = bytearray(flash)
        self.chip = chip
        self.size = len(flash) if size is None else size
        self.problems = problems or []
        self.ops: List[str] = []
        self.connects: List[tuple] = []
        self.short_read = False
        self.corrupt_write = False
        self.fail_write: Optional[str] = None
        self.fail_connect: Optional[str] = None

    def flash_size(self) -> int:
        return self.size

    def security_problems(self) -> List[str]:
        return list(self.problems)

    def read_flash(self, path: Path, size: int) -> None:
        self.ops.append("read")
        data = bytes(self.flash[:size])
        path.write_bytes(data[:-1] if self.short_read else data)

    def write_flash(self, path: Path) -> None:
        if self.fail_write:
            raise MPFlashError(self.fail_write)
        self.ops.append("write")
        data = bytearray(path.read_bytes())
        if self.corrupt_write:
            data[10] ^= 0xFF
        self.flash[: len(data)] = data

    def flash_md5(self, size: int) -> str:
        return hashlib.md5(bytes(self.flash[:size])).hexdigest()

    def hard_reset(self) -> None:
        self.ops.append("reset")

    def connector(self):
        chip = self

        @contextmanager
        def connect(serialport: str, cpu: str):
            chip.connects.append((serialport, cpu))
            if chip.fail_connect:
                raise MPFlashError(chip.fail_connect)
            yield chip

        return connect


@pytest.fixture
def mcu():
    return fake_mcu(port="esp32", cpu="ESP32", vid=0x1A86, board="ESP32_GENERIC")


@pytest.fixture
def chip(isolated_registry, monkeypatch):
    """A registered provider backed by a fake chip, with disk-space checks out of the way."""
    fake = FakeChip()
    registry.register(EspFlashProvider(connector=fake.connector()))
    return fake


def backup(mcu, out: Path) -> Path:
    return run_backup(mcu, plan_backup(mcu, [FLASH]), out)


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_provider_offers_exact_restorable_flash_covering_filesystems(mcu):
    (capability,) = EspFlashProvider().capabilities(mcu)

    assert (capability.component, capability.can_backup, capability.can_restore) == (FLASH, True, True)
    assert capability.exactness is Exactness.EXACT
    assert set(capability.covers) == {VFS, ROMFS}
    assert any("eFuses" in text for text in capability.exclusions)


@pytest.mark.parametrize(
    "overrides",
    [
        {"port": "rp2"},
        {"connected": False},
        {"vid": 0x303A},  # native USB needs a ROM-bootloader re-enumeration that is not implemented
        {"board": "ARDUINO_NANO_ESP32"},
    ],
)
def test_provider_does_not_apply_to_other_boards(overrides):
    board = {"port": "esp32", "vid": 0x1A86, "board": "ESP32_GENERIC", **overrides}

    assert EspFlashProvider().capabilities(fake_mcu(**board)) == ()


def test_esp8266_is_supported(mcu):
    mcu.port = "esp8266"

    assert len(EspFlashProvider().capabilities(mcu)) == 1


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def test_backup_stores_the_flash_byte_for_byte(chip, mcu, tmp_path):
    root = backup(mcu, tmp_path)

    bundle = read_bundle(root)
    bundle.verify()
    (artifact,) = bundle.manifest.artifacts
    assert (artifact.component, artifact.role, artifact.exactness) == (FLASH, ArtifactRole.DEVICE_READ, Exactness.EXACT)
    assert (artifact.address, artifact.length, artifact.size) == (0, SIZE, SIZE)
    assert (root / "artifacts" / "flash.bin").read_bytes() == IMAGE
    assert set(artifact.covers) == {VFS, ROMFS} and artifact.exclusions
    assert chip.connects == [("COM9", "ESP32")]


def test_backup_resets_the_chip_and_waits_for_the_board(chip, mcu, tmp_path):
    backup(mcu, tmp_path)

    assert chip.ops == ["read", "reset"]
    mcu.wait_for_restart.assert_called_once_with(timeout=20)


def test_backup_fails_if_the_board_does_not_come_back(chip, mcu, tmp_path):
    mcu.wait_for_restart.return_value = False

    with pytest.raises(MPFlashError, match="did not come back after reading the flash"):
        backup(mcu, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_backup_of_a_short_read_is_rejected(chip, mcu, tmp_path):
    chip.short_read = True

    with pytest.raises(MPFlashError, match="produced 4095 bytes, expected 4096"):
        backup(mcu, tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("problem", ["flash encryption is enabled", "secure boot is enabled", "the chip is in secure download mode"])
def test_backup_refuses_secured_chips(chip, mcu, tmp_path, problem):
    chip.problems = [problem]

    with pytest.raises(MPFlashError, match=f"Cannot back up the flash of this ESP32: {problem}"):
        backup(mcu, tmp_path)

    assert chip.ops == []
    assert list(tmp_path.iterdir()) == []


def test_backup_refuses_when_the_disk_is_too_small(chip, mcu, tmp_path, monkeypatch):
    monkeypatch.setattr(esp.shutil, "disk_usage", lambda path: type("U", (), {"free": 1000})())

    with pytest.raises(MPFlashError, match="Not enough disk space"):
        backup(mcu, tmp_path)

    assert chip.ops == []


def test_backup_reports_connection_failures(chip, mcu, tmp_path):
    chip.fail_connect = "Could not connect to the ESP bootloader on COM9: timed out"

    with pytest.raises(MPFlashError, match="Backup of flash by esptool-flash failed: Could not connect"):
        backup(mcu, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_notes_name_the_chip_and_size(chip, mcu, tmp_path):
    text = (backup(mcu, tmp_path) / "README.md").read_text(encoding="utf-8")

    assert "4096 bytes read from the ESP32 through esptool" in text
    assert "eFuses/OTP" in text


def test_auto_backup_includes_flash_and_the_filesystem_it_covers(isolated_registry, mcu, tmp_path):
    from mpflash.backup.builtins.vfs import VfsProvider
    from fake_device import FakeDeviceFs

    fake = FakeChip()
    registry.register(EspFlashProvider(connector=fake.connector()))
    registry.register(VfsProvider(opener=FakeDeviceFs({"/main.py": b"x"}).opener()))

    plan = plan_backup(mcu)

    assert [capability.component for _, capability in plan.selections] == [FLASH, VFS]


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


@pytest.fixture
def bundle(chip, mcu, tmp_path):
    root = backup(mcu, tmp_path)
    chip.ops.clear()
    chip.connects.clear()
    mcu.wait_for_restart.reset_mock()
    return read_bundle(root)


def test_restore_rewrites_the_whole_flash_and_verifies_it(chip, bundle, mcu):
    chip.flash = bytearray(b"\x00" * SIZE)

    run_restore(plan_restore(bundle, mcu), mcu)

    assert bytes(chip.flash) == IMAGE
    assert chip.ops == ["reset", "write", "reset"]  # the first reset ends the dry-run style check in plan_restore


def test_dry_run_checks_the_target_without_writing(chip, bundle, mcu):
    chip.flash = bytearray(b"\xaa" * SIZE)

    plan = plan_restore(bundle, mcu)

    assert "write" not in chip.ops and bytes(chip.flash) == b"\xaa" * SIZE
    text = "\n".join(plan.lines)
    assert "ERASE and rewrite the ENTIRE flash: 4096 bytes at 0x00000000" in text
    assert "filesystem" in text and "MD5" in text and "resets" in text


def test_restore_fails_loudly_when_the_flash_does_not_verify(chip, bundle, mcu):
    chip.corrupt_write = True

    with pytest.raises(MPFlashError, match="did not verify after writing.*may not boot"):
        run_restore(plan_restore(bundle, mcu), mcu)


def test_restore_reports_write_errors(chip, bundle, mcu):
    chip.fail_write = "A fatal error occurred: Failed to write compressed data"
    plan = plan_restore(bundle, mcu)

    with pytest.raises(MPFlashError, match="Restore of flash by esptool-flash failed: A fatal error"):
        run_restore(plan, mcu)


def test_restore_rejects_a_different_chip(chip, bundle, mcu):
    chip.chip = "ESP32-S3"

    with pytest.raises(MPFlashError, match="made from an ESP32 but this board has an ESP32-S3"):
        plan_restore(bundle, mcu)


def test_chip_names_are_compared_ignoring_punctuation(chip, mcu, tmp_path):
    mcu.cpu = "ESP32S3"
    chip.chip = "ESP32-S3"
    bundle = read_bundle(backup(mcu, tmp_path))

    plan_restore(bundle, mcu)


def test_restore_rejects_a_different_flash_size(chip, bundle, mcu):
    chip.size = SIZE * 2

    with pytest.raises(MPFlashError, match="image is 4096 bytes but this board has 8192 bytes of flash"):
        plan_restore(bundle, mcu)


@pytest.mark.parametrize("problem", ["flash encryption is enabled", "secure boot is enabled"])
def test_restore_refuses_secured_chips_before_writing(chip, bundle, mcu, problem):
    chip.problems = [problem]

    with pytest.raises(MPFlashError, match=f"Cannot restore the flash of this ESP32: {problem}"):
        plan_restore(bundle, mcu)

    assert "write" not in chip.ops


def test_restore_requires_the_bundle_to_record_the_chip(chip, mcu, tmp_path):
    mcu.cpu = ""
    bundle = read_bundle(backup(mcu, tmp_path))
    mcu.cpu = ""

    with pytest.raises(MPFlashError, match="does not record which chip"):
        plan_restore(bundle, mcu)


def test_restore_replaces_the_filesystem_it_covers(chip, bundle, mcu):
    plan = plan_restore(bundle, mcu)

    assert [item.component for item in plan.items] == [FLASH]
    assert plan.warnings == ()


def test_a_slow_board_after_restore_is_only_a_warning(chip, bundle, mcu):
    plan = plan_restore(bundle, mcu)
    mcu.wait_for_restart.return_value = False

    run_restore(plan, mcu)

    assert bytes(chip.flash) == IMAGE


def test_restore_rejects_bundles_without_exactly_one_raw_image(chip, mcu, tmp_path):
    from mpflash.backup.bundle import BundleWriter
    from mpflash.backup.models import DeviceIdentity

    with BundleWriter(tmp_path, "odd") as writer:
        writer.add_artifact_bytes(
            "flash.bin",
            b"x" * 8,
            component=FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider="esptool-flash",
            address=0x1000,
            length=8,
        )
        root = writer.commit(DeviceIdentity.from_mcu(mcu))

    with pytest.raises(MPFlashError, match="starts at address 0"):
        plan_restore(read_bundle(root), mcu)


# ---------------------------------------------------------------------------
# esptool adapter
# ---------------------------------------------------------------------------


class FakeEsp:
    CHIP_NAME = "ESP32"

    def __init__(self, enc=False, boot=False, secure_download=False, raises=None, md5=b"\x01" * 16):
        self.enc, self.boot, self.secure_download_mode = enc, boot, secure_download
        self.raises = raises
        self.md5 = md5

    def get_flash_encryption_enabled(self):
        if self.raises:
            raise self.raises
        return self.enc

    def get_secure_boot_enabled(self):
        return self.boot

    def flash_md5sum(self, addr, size):
        return "AB" * 16


class FakeCmds:
    def __init__(self, flash_size="4MB"):
        self.flash_size = flash_size
        self.calls = []

    def detect_flash_size(self, esp):
        return self.flash_size

    def read_flash(self, esp, address, size, **kwargs):
        self.calls.append(("read", address, size, kwargs))

    def write_flash(self, esp, addr_data, **kwargs):
        self.calls.append(("write", addr_data, kwargs))

    def reset_chip(self, esp, mode):
        self.calls.append(("reset", mode))


def adapter(esp=None, cmds=None):
    return esp_module._EsptoolDevice(esp or FakeEsp(), cmds or FakeCmds())


esp_module = esp


def test_adapter_reports_flash_size_in_bytes():
    assert adapter().flash_size() == 4 * 1024 * 1024
    assert adapter(cmds=FakeCmds("512KB")).flash_size() == 512 * 1024


@pytest.mark.parametrize("answer", [None, "bogus"])
def test_adapter_rejects_an_undetectable_flash_size(answer):
    with pytest.raises(MPFlashError, match="Could not detect the flash size of the ESP32"):
        adapter(cmds=FakeCmds(answer)).flash_size()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({}, []),
        ({"enc": True}, ["flash encryption is enabled"]),
        ({"boot": True}, ["secure boot is enabled"]),
        ({"secure_download": True}, ["the chip is in secure download mode"]),
        ({"enc": True, "boot": True}, ["flash encryption is enabled", "secure boot is enabled"]),
    ],
)
def test_adapter_reports_security_state(kwargs, expected):
    assert adapter(FakeEsp(**kwargs)).security_problems() == expected


def test_adapter_treats_unknown_security_state_as_unsafe():
    (problem,) = adapter(FakeEsp(raises=RuntimeError("no efuse access"))).security_problems()

    assert "could not be determined" in problem and "no efuse access" in problem


def test_adapter_writes_exactly_without_forcing():
    cmds = FakeCmds()

    adapter(cmds=cmds).write_flash(Path("image.bin"))

    (_, addr_data, kwargs) = cmds.calls[0]
    assert addr_data == [(0, "image.bin")]
    assert kwargs["flash_mode"] == kwargs["flash_freq"] == kwargs["flash_size"] == "keep"
    assert "force" not in kwargs  # esptool's protection against overwriting encrypted flash stays on


def test_adapter_reads_from_address_zero_and_resets_hard():
    cmds = FakeCmds()
    device = adapter(cmds=cmds)

    device.read_flash(Path("out.bin"), 4096)
    device.hard_reset()

    assert cmds.calls[0][:3] == ("read", 0, 4096) and cmds.calls[0][3]["output"] == "out.bin"
    assert cmds.calls[1] == ("reset", "hard-reset")


def test_adapter_normalises_the_device_md5():
    assert adapter().flash_md5(16) == "ab" * 16


def test_connect_raises_a_clear_error_when_the_bootloader_is_unreachable(monkeypatch):
    import esptool.cmds as cmds

    def refuse(port, **kwargs):
        raise OSError("could not open port")

    monkeypatch.setattr(cmds, "detect_chip", refuse)

    with pytest.raises(MPFlashError, match="Could not connect to the ESP bootloader on COM9: could not open port"):
        with connect_esptool("COM9", "ESP32"):
            pass
