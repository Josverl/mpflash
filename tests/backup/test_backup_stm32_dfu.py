"""Tests for the STM32 DfuSe raw-flash provider."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from fake_device import fake_mcu

from mpflash.backup.base import BackupContext
from mpflash.backup import registry
from mpflash.backup.builtins import stm32_dfu
from mpflash.backup.builtins.stm32_dfu import FLASH_BASE, STM32DfuProvider, parse_flash_range
from mpflash.backup.bundle import BundleWriter, read_bundle
from mpflash.backup.models import ArtifactRole, ComponentKind, DeviceIdentity, Exactness
from mpflash.errors import MPFlashError

FLASH = bytes((index * 31 + 7) % 256 for index in range(1024 * 1024))
pytestmark = pytest.mark.usefixtures("isolated_registry")
DFU_LISTING = (
    'Found DFU: [0483:df11] ver=2200, devnum=1, cfg=1, intf=0, path="1-1", '
    'alt=0, name="@Internal Flash /0x08000000/04*016Kg,01*064Kg,07*128Kg"\n'
    'Found DFU: [0483:df11] ver=2200, devnum=1, cfg=1, intf=0, path="1-1", '
    'alt=1, name="@Option Bytes /0x1FFFC000/01*016Kg"\n'
)


class FakeDfu:
    def __init__(self) -> None:
        self.flash = bytearray(FLASH)
        self.calls: List[List[str]] = []

    def run(self, command, **_kwargs):
        assert _kwargs["capture_output"] and _kwargs["check"] is False
        arguments = list(command)
        self.calls.append(arguments)
        if "--list" in arguments:
            return SimpleNamespace(returncode=0, stdout=DFU_LISTING, stderr="")
        path = Path(arguments[-1])
        address_option = arguments[arguments.index("--dfuse-address") + 1]
        _, raw_length, *_ = address_option.split(":")
        length = int(raw_length)
        if "--upload" in arguments:
            path.write_bytes(self.flash[:length])
        elif "--download" in arguments:
            data = path.read_bytes()
            self.flash[: len(data)] = data
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def provider(monkeypatch):
    fake = FakeDfu()
    monkeypatch.setattr(stm32_dfu.shutil, "which", lambda _: "dfu-util")
    monkeypatch.setattr(stm32_dfu.subprocess, "run", fake.run)
    instance = STM32DfuProvider(enter_dfu=lambda _: None)
    registry.register(instance)
    return instance, fake


@pytest.fixture
def mcu():
    return fake_mcu(port="stm32", cpu="STM32F405RG", board_id="PYBV11", board="PYBV11")


def test_parse_flash_range_uses_only_advertised_internal_flash():
    result = parse_flash_range(DFU_LISTING)

    assert result.alternate == 0
    assert result.address == FLASH_BASE
    assert result.length == len(FLASH)


@pytest.mark.parametrize(
    "descriptor",
    [
        "@Internal Flash /0x08000000/04*016Ka",
        "@Internal Flash /0x08000000/04*016Kx",
        "@Internal Flash /0x08000000/04*016Kg,broken",
        "@Internal Flash /0x08000000/00*016Kg",
    ],
)
def test_parse_flash_range_rejects_unsafe_or_invalid_segments(descriptor):
    output = f'Found DFU: [0483:df11] alt=0, name="{descriptor}"'

    with pytest.raises(MPFlashError):
        parse_flash_range(output)


def test_parse_flash_range_rejects_missing_or_ambiguous_internal_flash():
    with pytest.raises(MPFlashError, match="did not advertise"):
        parse_flash_range('Found DFU: [0483:df11] alt=0, name="@Option Bytes /0x1FFFC000/01*016Kg"')

    with pytest.raises(MPFlashError, match="multiple"):
        parse_flash_range(DFU_LISTING + DFU_LISTING.splitlines()[0] + "\n")

    with pytest.raises(MPFlashError, match="multiple"):
        parse_flash_range(DFU_LISTING + 'Found DFU: [0483:df11] alt=2, name="@Internal Flash /0x08100000/04*016Kg"\n')


def test_provider_capability_is_limited_to_connected_stm32(provider, mcu):
    instance, _ = provider
    assert len(instance.capabilities(mcu)) == 1
    assert registry.capabilities_for(mcu)[0][0] is instance
    assert instance.capabilities(fake_mcu(port="rp2", cpu="RP2040")) == ()
    assert instance.capabilities(fake_mcu(connected=False, port="stm32")) == ()


def test_provider_is_unavailable_without_dfutil(monkeypatch):
    monkeypatch.setattr(stm32_dfu.shutil, "which", lambda _: None)

    assert not STM32DfuProvider().is_available()
    with pytest.raises(MPFlashError, match="requires dfu-util"):
        stm32_dfu._tool_path()


def test_backup_reads_exact_flash_and_returns_board_to_application(provider, mcu, tmp_path):
    instance, fake = provider
    device = DeviceIdentity.from_mcu(mcu)
    with BundleWriter(tmp_path, "stm32-test") as writer:
        instance.backup(mcu, ComponentKind.FLASH, BackupContext(writer))
        bundle_path = writer.commit(device)

    bundle = read_bundle(bundle_path)
    (artifact,) = bundle.manifest.artifacts
    assert artifact.address == FLASH_BASE
    assert artifact.length == len(FLASH)
    assert artifact.exactness is Exactness.EXACT
    assert artifact.role is ArtifactRole.DEVICE_READ
    assert (bundle_path / artifact.path).read_bytes() == FLASH
    assert mcu.connected is True
    assert sum("--upload" in call for call in fake.calls) == 1
    assert "leave" in fake.calls[1][fake.calls[1].index("--dfuse-address") + 1]


def test_backup_rejects_short_upload(provider, mcu, tmp_path, monkeypatch):
    instance, _ = provider
    run = stm32_dfu._run_dfu_util

    def short_upload(tool, arguments, *, timeout=stm32_dfu.DFU_TIMEOUT):
        if "--upload" in arguments:
            Path(arguments[-1]).write_bytes(b"short")
            return ""
        return run(tool, arguments, timeout=timeout)

    monkeypatch.setattr(stm32_dfu, "_run_dfu_util", short_upload)
    with BundleWriter(tmp_path, "stm32-short") as writer:
        with pytest.raises(MPFlashError, match="uploaded 5 bytes"):
            instance.backup(mcu, ComponentKind.FLASH, BackupContext(writer))


def test_restore_downloads_then_uploads_and_verifies_exact_flash(provider, mcu, tmp_path):
    instance, fake = provider
    original = bytearray(FLASH)
    original[100:110] = b"restored!!"
    source = tmp_path / "source.bin"
    source.write_bytes(original)
    identity = DeviceIdentity.from_mcu(mcu)
    with BundleWriter(tmp_path, "stm32-restore") as writer:
        writer.add_artifact_copy(
            "flash.bin",
            source,
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider=instance.name,
            address=FLASH_BASE,
            length=len(original),
            covers=(ComponentKind.VFS,),
            exclusions=stm32_dfu.EXCLUSIONS,
        )
        bundle_path = writer.commit(identity)
    bundle = read_bundle(bundle_path)
    (artifact,) = bundle.manifest.artifacts

    assert instance.describe_restore(mcu, bundle, [artifact])
    instance.restore(mcu, bundle, [artifact])

    assert bytes(fake.flash) == bytes(original)
    assert hashlib.sha256(fake.flash).digest() == hashlib.sha256(original).digest()
    assert sum("--download" in call for call in fake.calls) == 1
    assert sum("--upload" in call for call in fake.calls) == 2
    assert mcu.connected is True


def test_restore_rejects_a_different_flash_geometry(provider, mcu, tmp_path, monkeypatch):
    instance, _ = provider
    source = tmp_path / "flash.bin"
    source.write_bytes(FLASH)
    identity = DeviceIdentity.from_mcu(mcu)
    with BundleWriter(tmp_path, "stm32-geometry") as writer:
        writer.add_artifact_copy(
            "flash.bin",
            source,
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider=instance.name,
            address=FLASH_BASE,
            length=len(FLASH),
            covers=(ComponentKind.VFS,),
            exclusions=stm32_dfu.EXCLUSIONS,
        )
        bundle_path = writer.commit(identity)
    bundle = read_bundle(bundle_path)
    (artifact,) = bundle.manifest.artifacts
    monkeypatch.setattr(stm32_dfu, "parse_flash_range", lambda _: stm32_dfu.DfuFlashRange(0, FLASH_BASE, len(FLASH) // 2))

    with pytest.raises(MPFlashError, match="advertises"):
        instance.describe_restore(mcu, bundle, [artifact])
