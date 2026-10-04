"""Pico 2 geometry/security gates, device queries and raw flash round trips."""

from __future__ import annotations

import struct
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Generator

import pytest
from fake_device import fake_mcu
from test_backup_rp2 import FakeBoard, FakeRepl, install, make_image

from mpflash.backup import registry
from mpflash.backup.builtins import rp2350
from mpflash.backup.builtins.rp2 import BLOCK, XIP_BASE, build_uf2
from mpflash.backup.bundle import read_bundle
from mpflash.backup.models import ComponentKind
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError

TRANSLATIONS = tuple(0x04000000 + i * 0x400 for i in range(4))


def probe(**changes: Any) -> tuple:
    values = dict(
        system_rc=4,
        system_flags=14,
        critical=0,
        cpu=0,
        devinfo=0xC00,
        partition_rc=4,
        partition_flags=1,
        count=0,
        permissions=0xFFFFE000,
        families=0xFC078000,
        translations=TRANSLATIONS,
        fs_address=0x10100000,
        fs_size=rp2350.FILESYSTEM_SIZE,
    )
    values.update(changes)
    return (
        (values["system_rc"], tuple(values[key] for key in ("system_flags", "critical", "cpu", "devinfo"))),
        (values["partition_rc"], tuple(values[key] for key in ("partition_flags", "count", "permissions", "families"))),
        values["translations"],
        values["fs_address"],
        values["fs_size"],
    )


@pytest.mark.parametrize("devinfo", [0xA00, 0xB00, 0xC00])
def test_rom_window_is_an_upper_bound_not_a_physical_flash_probe(devinfo: int) -> None:
    rp2350.validate_probe(probe(devinfo=devinfo))


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"system_rc": -4}, "invalid geometry/security"),
        ({"system_rc": 3}, "could not establish"),
        ({"system_flags": 6}, "could not establish"),
        ({"partition_rc": 0}, "could not establish"),
        ({"partition_flags": 0}, "could not establish"),
        ({"critical": 1}, "secure boot"),
        ({"cpu": 1}, "Only Arm"),
        ({"count": 1}, "partition tables"),
        ({"count": 256}, "partition tables"),
        ({"permissions": 0x7FFFE000}, "not fully accessible"),
        ({"families": 0xFC058000}, "not fully accessible"),
        ({"devinfo": 0x900}, "single 4 MiB"),
        ({"devinfo": 0xAC00}, "single 4 MiB"),
        ({"translations": (0x4000400, *TRANSLATIONS[1:])}, "translated XIP"),
        ({"translations": None}, "translated XIP"),
        ({"fs_address": 0x10200000}, "standard 4 MiB"),
        ({"fs_size": 2 * 1024 * 1024}, "standard 4 MiB"),
        ({"critical": "unknown"}, "invalid geometry/security"),
    ],
)
def test_unsafe_or_unknown_layout_is_rejected(change: dict, reason: str) -> None:
    with pytest.raises(MPFlashError, match=reason):
        rp2350.validate_probe(probe(**change))


@pytest.mark.parametrize("value", [None, (), ((), (), (), 0, 0)])
def test_malformed_probe_is_rejected(value: Any) -> None:
    with pytest.raises(MPFlashError, match="malformed"):
        rp2350.validate_probe(value)


def pico2_mcu(**changes: Any) -> Any:
    values = dict(port="rp2", cpu="RP2350", board_id="RPI_PICO2", board="RPI_PICO2")
    values.update(changes)
    return fake_mcu(**values)


def test_capability_is_scoped_to_pico2() -> None:
    provider = rp2350.RP2350FlashProvider()
    (capability,) = provider.capabilities(pico2_mcu())
    assert capability.can_backup and capability.can_restore
    for changes in ({"cpu": "RP2040"}, {"board_id": "UNKNOWN"}, {"connected": False}, {"port": "samd"}):
        assert provider.capabilities(pico2_mcu(**changes)) == ()


def image_with_item(item: int) -> bytes:
    image = bytearray(make_image(rp2350.FLASH_SIZE))
    image[256:276] = struct.pack("<5I", 0xFFFFDED3, item, 0x1FF, 0, 0xAB123579)
    return bytes(image)


def test_source_partition_tables_and_other_architectures_are_rejected() -> None:
    provider = rp2350.RP2350FlashProvider()
    provider._validate_image(image_with_item(0x10210142))
    for item, message in ((0x0000010A, "partition table"), (0x11210142, "Arm secure"), (0x10110142, "Arm secure")):
        with pytest.raises(MPFlashError, match=message):
            provider._validate_image(image_with_item(item))
    with pytest.raises(MPFlashError, match="no supported Arm"):
        provider._validate_image(bytes(rp2350.FLASH_SIZE))
    with pytest.raises(MPFlashError, match="4 MiB"):
        provider._validate_image(bytes(BLOCK))


class Pico2Repl(FakeRepl):
    def exec(self, command: str, timeout: float = 10) -> bytes:
        if command == rp2350.DEVICE_CODE:
            original = sys.implementation
            sys.implementation = SimpleNamespace(_build="RPI_PICO2", _mpy=7942)
            try:
                return super().exec(command, timeout)
            finally:
                sys.implementation = original
        return super().exec(command, timeout)


class Pico2Board(FakeBoard):
    def bytearray_at(self, address: int, length: int) -> bytearray:
        assert XIP_BASE <= address and address + length <= XIP_BASE + rp2350.FLASH_SIZE
        return super().bytearray_at(address, length)


class BootRegisters(dict):
    def __getitem__(self, address: int) -> int:
        value = super().__getitem__(address)
        if address == 0x400E080C and value:
            super().__setitem__(address, 0)
        return value

    def __setitem__(self, address: int, value: int) -> None:
        super().__setitem__(address, 1 if address == 0x400E080C and value == 0 else value)


@pytest.fixture
def pico2(monkeypatch: pytest.MonkeyPatch, isolated_registry: Any) -> tuple:
    board = Pico2Board(image_with_item(0x10210142), rp2350.FILESYSTEM_SIZE)
    install(monkeypatch, board)
    machine = SimpleNamespace(
        mem16={0x16: 0x75},
        mem32=BootRegisters({0x400E080C: 1, **{0x400D0034 + i * 4: value for i, value in enumerate(TRANSLATIONS)}}),
    )
    state: dict[str, Any] = {"probe": probe(), "secure": True}

    def asm(function: Any) -> Any:
        if function.__name__ == "_rom_secure":
            return lambda _: (1 << 22) if state["secure"] else 0
        if function.__name__ == "_rom_lookup":
            return lambda code, mask, entry: code

        def call(out: Any, words: int, flags: int, address: int) -> int:
            assert words == 4
            result, values = state["probe"][0 if address == 0x5347 else 1]
            assert flags == (14 if address == 0x5347 else 1)
            for index, value in enumerate(values):
                out[index] = value
            return result

        return call

    monkeypatch.setitem(sys.modules, "machine", machine)
    monkeypatch.setitem(sys.modules, "micropython", SimpleNamespace(asm_thumb=asm))
    monkeypatch.setattr(sys.modules["uctypes"], "addressof", lambda flash: 0x10100000, raising=False)

    @contextmanager
    def open_repl(port: str, *, soft_reset: bool = True) -> Generator[Pico2Repl, None, None]:
        yield Pico2Repl(board)

    writes = []

    def flash(mcu: Any, path: Path) -> None:
        data = path.read_bytes()
        for offset in range(0, len(data), 512):
            header = struct.unpack_from("<8I", data, offset)
            assert header[7] == rp2350.UF2_FAMILY_RP2350_ARM_S
            address, size = header[3:5]
            start = address - XIP_BASE
            assert 0 <= start <= len(board.flash) - size
            board.flash[start : start + size] = data[offset + 32 : offset + 32 + size]
        writes.append(data)

    provider = rp2350.RP2350FlashProvider(opener=open_repl, flasher=flash)
    registry.register(provider)
    return provider, board, state, writes


def test_backup_and_restore_use_only_confirmed_geometry_and_arm_uf2(pico2: tuple, tmp_path: Path) -> None:
    provider, board, _, writes = pico2
    mcu = pico2_mcu()
    original = bytes(board.flash)
    root = run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), tmp_path)
    bundle = read_bundle(root)
    artifact = bundle.manifest.artifacts[0]
    assert artifact.provider == "rp2350-flash" and artifact.length == rp2350.FLASH_SIZE
    assert (root / artifact.path).read_bytes() == original
    assert all(offset + length <= rp2350.FLASH_SIZE for offset, length in board.rd_calls)
    board.flash[-BLOCK:] = b"\x00" * BLOCK
    run_restore(plan_restore(bundle, mcu), mcu)
    assert bytes(board.flash) == original and len(writes) == 1
    assert len(writes[0]) == 16 * 512
    run_restore(plan_restore(bundle, mcu), mcu)
    assert len(writes) == 1


def test_security_is_rechecked_between_planning_and_writing(pico2: tuple, tmp_path: Path) -> None:
    _, board, state, writes = pico2
    mcu = pico2_mcu()
    root = run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), tmp_path)
    board.flash[-BLOCK:] = bytes(BLOCK)
    plan = plan_restore(read_bundle(root), mcu)
    state["probe"] = probe(critical=1)
    with pytest.raises(MPFlashError, match="secure boot"):
        run_restore(plan, mcu)
    assert writes == []


def test_nonsecure_execution_is_rejected_before_any_flash_read(pico2: tuple, tmp_path: Path) -> None:
    _, board, state, writes = pico2
    state["secure"] = False
    mcu = pico2_mcu()
    with pytest.raises(RuntimeError, match="non-secure execution"):
        run_backup(mcu, plan_backup(mcu, [ComponentKind.FLASH]), tmp_path)
    assert board.rd_calls == [] and writes == []
    assert list(tmp_path.iterdir()) == []


def test_uf2_can_select_rp2350_without_changing_rp2040_default() -> None:
    uf2 = build_uf2(bytes(BLOCK), [0], family=rp2350.UF2_FAMILY_RP2350_ARM_S)
    assert struct.unpack_from("<I", uf2, 28)[0] == rp2350.UF2_FAMILY_RP2350_ARM_S
    assert struct.unpack_from("<I", build_uf2(bytes(BLOCK), [0]), 28)[0] == 0xE48BFF56
