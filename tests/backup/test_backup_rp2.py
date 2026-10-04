"""RP2040 raw flash provider: device code, UF2 restore and end-to-end integrity."""

import binascii
import hashlib
import random
import struct
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple

import pytest
from fake_device import fake_mcu

from mpflash.backup import registry
from mpflash.backup.builtins import rp2
from mpflash.backup.builtins.rp2 import (
    BLOCK,
    UF2_FAMILY_RP2040,
    XIP_BASE,
    ReplFlash,
    Rp2FlashProvider,
    build_uf2,
)
from mpflash.backup.bundle import BundleWriter, read_bundle
from mpflash.backup.models import ArtifactRole, ComponentKind, DeviceIdentity, Exactness
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError

FLASH, VFS, ROMFS = ComponentKind.FLASH, ComponentKind.VFS, ComponentKind.ROMFS
MIB = 1024 * 1024


def make_image(size: int = MIB, seed: int = 1) -> bytes:
    """A flash image: boot code and firmware at the start, a few files late, everything else erased."""
    rnd = random.Random(seed)
    image = bytearray(b"\xff" * size)
    firmware = min(300 * 1024, size // 2)  # never longer than the image: slice assignment would otherwise grow it
    image[:firmware] = rnd.randbytes(firmware)
    for block in (size // BLOCK - 3, size // BLOCK - 2):  # files near the end
        image[block * BLOCK : block * BLOCK + 700] = rnd.randbytes(700)
    return bytes(image)


class FakeBoard:
    """An RP2040: its flash is a bytearray mapped (and aliased) at XIP_BASE, as seen by ``uctypes``."""

    def __init__(self, image: bytes, fs_bytes: Optional[int] = None):
        self.flash = bytearray(image)
        self.fs_bytes = fs_bytes if fs_bytes is not None else len(image) // 2
        self.rd_calls: List[Tuple[int, int]] = []
        self.corrupt_reads = False
        self.short_reads = False
        self.transient_failures = 0  # the next N reads lose their tail, then the link recovers
        self.opens: List[bool] = []

    # uctypes.bytearray_at: reads wrap around the real flash size, like the QSPI chip ignoring high address bits
    def bytearray_at(self, address: int, length: int) -> bytearray:
        offset = (address - XIP_BASE) % len(self.flash)
        return bytearray(self.flash[offset : offset + length])

    def modules(self) -> dict:
        board = self

        class Flash:
            def ioctl(self, op: int, arg: int) -> int:
                assert (op, arg) == (4, 0)
                return board.fs_bytes // BLOCK

        return {
            "uctypes": types.SimpleNamespace(bytearray_at=self.bytearray_at),
            "rp2": types.SimpleNamespace(Flash=Flash),
        }


class _Stdout:
    """The board's sys.stdout: MicroPython's write() accepts bytes, CPython's does not."""

    def __init__(self) -> None:
        self.captured = bytearray()

    def write(self, data) -> int:
        self.captured += data if isinstance(data, bytes) else data.encode()
        return len(data)

    def flush(self) -> None:
        pass


class FakeRepl:
    """Runs the code the provider sends to the board in CPython, against a :class:`FakeBoard`."""

    def __init__(self, board: FakeBoard):
        self.board = board
        self.namespace: dict = {}
        self.timeouts: List[float] = []

    def exec(self, command: str, timeout: float = 10) -> bytes:
        """Run ``command`` and return what it printed, as the raw REPL would."""
        self.timeouts.append(timeout)
        stdout, original = _Stdout(), sys.stdout
        sys.stdout = stdout  # type: ignore[assignment]
        try:
            exec(command, self.namespace)
        finally:
            sys.stdout = original
        output = bytes(stdout.captured)
        if command.startswith("_rd("):
            offset, length = (int(part) for part in command[len("_rd(") : -1].split(","))
            self.board.rd_calls.append((offset, length))
            payload, _, crc = output.partition(b".")
            drop_tail = self.board.short_reads or self.board.transient_failures > 0
            if self.board.transient_failures > 0:
                self.board.transient_failures -= 1
            if drop_tail:  # the board's USB serial lost its last 64-byte packet
                payload = payload[:-64]
            if self.board.corrupt_reads:
                data = bytearray(binascii.a2b_base64(payload))
                data[0] ^= 0xFF
                payload = binascii.b2a_base64(bytes(data), newline=False)
            output = payload + b"." + crc
        return output

    def eval(self, expression: str, timeout: float = 10):
        self.timeouts.append(timeout)
        return eval(expression, self.namespace)


def install(monkeypatch, board: FakeBoard) -> None:
    for name, module in board.modules().items():
        monkeypatch.setitem(sys.modules, name, module)


def opener_for(board: FakeBoard):
    @contextmanager
    def open_repl(serialport: str, *, soft_reset: bool = True):
        board.opens.append(soft_reset)
        yield FakeRepl(board)

    return open_repl


def apply_uf2(board: FakeBoard, uf2: bytes) -> List[int]:
    """What the RP2040 boot ROM does with a UF2: validate each block and program it. Returns the sectors touched."""
    assert len(uf2) % 512 == 0
    count = len(uf2) // 512
    touched = set()
    for index in range(count):
        block = uf2[index * 512 : (index + 1) * 512]
        m0, m1, flags, address, size, number, total, family = struct.unpack_from("<8I", block)
        assert (m0, m1) == (0x0A324655, 0x9E5D5157) and struct.unpack_from("<I", block, 508)[0] == 0x0AB16F30
        assert flags == 0x2000 and family == UF2_FAMILY_RP2040
        assert (number, total, size) == (index, count, 256)
        offset = address - XIP_BASE
        assert 0 <= offset and offset + size <= len(board.flash) and offset % 256 == 0
        board.flash[offset : offset + size] = block[32 : 32 + size]
        touched.add(offset // BLOCK)
    return sorted(touched)


@pytest.fixture
def board(monkeypatch):
    fake = FakeBoard(make_image())
    install(monkeypatch, fake)
    return fake


@pytest.fixture
def mcu():
    return fake_mcu(port="rp2", cpu="RP2040", board_id="PIMORONI_PICOLIPO", board="PIMORONI_PICOLIPO")


@pytest.fixture
def provider(isolated_registry, board):
    """A registered provider whose 'bootloader' applies the UF2 to the fake board."""
    flashed: List[List[int]] = []

    def flasher(mcu_, uf2_path: Path) -> None:
        flashed.append(apply_uf2(board, uf2_path.read_bytes()))

    instance = Rp2FlashProvider(opener=opener_for(board), flasher=flasher)
    instance.flashed = flashed  # type: ignore[attr-defined]
    registry.register(instance)
    return instance


def backup(mcu, out: Path) -> Path:
    return run_backup(mcu, plan_backup(mcu, [FLASH]), out)


# ---------------------------------------------------------------------------
# the code that runs on the board
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [256 * 1024, MIB, 2 * MIB, 8 * MIB, 16 * MIB])
def test_flash_size_is_detected_by_address_aliasing(monkeypatch, size):
    board = FakeBoard(make_image(size))
    install(monkeypatch, board)

    assert ReplFlash(FakeRepl(board)).flash_size() == size


def test_blank_map_marks_exactly_the_erased_blocks(board):
    flash = ReplFlash(FakeRepl(board))
    blank = flash.blank_blocks(MIB)

    expected = {i for i in range(MIB // BLOCK) if board.flash[i * BLOCK : (i + 1) * BLOCK] == b"\xff" * BLOCK}
    assert blank == expected
    assert len(blank) == MIB // BLOCK - 75 - 2  # 300 KiB of firmware (75 blocks) and two file blocks are not blank


def test_reads_return_the_flash_contents(board):
    flash = ReplFlash(FakeRepl(board))

    assert flash.read(0, 4096) == bytes(board.flash[:4096])
    assert flash.read(5 * BLOCK + 17, 100) == bytes(board.flash[5 * BLOCK + 17 : 5 * BLOCK + 117])


def test_block_digests_identify_each_block(board):
    digests = ReplFlash(FakeRepl(board)).block_digests(MIB)

    assert len(digests) == MIB // BLOCK and all(len(d) == 8 for d in digests)
    assert digests[3] == hashlib.sha256(bytes(board.flash[3 * BLOCK : 4 * BLOCK])).digest()[:8]


def test_whole_flash_sha256_matches_the_host(board):
    flash = ReplFlash(FakeRepl(board))

    assert flash.sha256(MIB) == hashlib.sha256(bytes(board.flash)).hexdigest()


def test_long_operations_get_long_timeouts(board):
    repl = FakeRepl(board)

    ReplFlash(repl).sha256(16 * MIB)

    assert repl.timeouts[-1] == 60 + 16 * 3


def test_an_incomplete_digest_list_is_rejected(board):
    repl = FakeRepl(board)
    flash = ReplFlash(repl)
    original = repl.eval
    repl.eval = lambda expression, timeout=10: (
        original(expression, timeout)[:-1] if expression.startswith("_sectors") else original(expression, timeout)
    )  # type: ignore[method-assign]

    with pytest.raises(MPFlashError, match="incomplete list of flash digests"):
        flash.block_digests(MIB)


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_provider_offers_exact_restorable_flash_for_rp2040(mcu):
    (capability,) = Rp2FlashProvider().capabilities(mcu)

    assert (capability.component, capability.can_backup, capability.can_restore) == (FLASH, True, True)
    assert capability.exactness is Exactness.EXACT and set(capability.covers) == {VFS, ROMFS}
    assert any("boot ROM" in text for text in capability.exclusions)


@pytest.mark.parametrize("overrides", [{"cpu": "RP2350"}, {"port": "samd"}, {"connected": False}, {"family": "circuitpython"}])
def test_provider_does_not_apply_to_other_boards(overrides):
    board = {"port": "rp2", "cpu": "RP2040", **overrides}

    assert Rp2FlashProvider().capabilities(fake_mcu(**board)) == ()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def test_backup_stores_the_flash_exactly(provider, board, mcu, tmp_path):
    root = backup(mcu, tmp_path)

    bundle = read_bundle(root)
    bundle.verify()
    (artifact,) = bundle.manifest.artifacts
    assert (artifact.component, artifact.role, artifact.exactness) == (FLASH, ArtifactRole.DEVICE_READ, Exactness.EXACT)
    assert (artifact.address, artifact.length) == (XIP_BASE, MIB)
    assert (root / "artifacts" / "flash.bin").read_bytes() == bytes(board.flash)
    assert set(artifact.covers) == {VFS, ROMFS}


def test_backup_transfers_only_blocks_that_are_not_erased(provider, board, mcu, tmp_path):
    backup(mcu, tmp_path)

    reads = board.rd_calls
    read_blocks = [b for offset, length in reads for b in range(offset // BLOCK, (offset + length - 1) // BLOCK + 1)]
    data_blocks = [i for i in range(MIB // BLOCK) if board.flash[i * BLOCK : (i + 1) * BLOCK] != b"\xff" * BLOCK]
    assert sorted(read_blocks) == data_blocks  # exactly the blocks that hold data, each exactly once
    assert len(data_blocks) == 77
    assert all(length <= rp2.READ_CHUNK for _, length in reads)


def test_backup_notes_report_how_much_was_skipped(provider, mcu, tmp_path):
    text = (backup(mcu, tmp_path) / "README.md").read_text(encoding="utf-8")

    assert "verified by SHA-256 on the board" in text
    assert f"{MIB // BLOCK - 77} of {MIB // BLOCK} erased blocks were not transferred" in text


def test_backup_stops_the_application_first(provider, board, mcu, tmp_path):
    backup(mcu, tmp_path)

    assert board.opens == [True]


@pytest.mark.parametrize(
    "setting, reason",
    [("corrupt_reads", "the checksum does not match"), ("short_reads", r"it holds \d+ bytes, expected \d+")],
)
def test_persistently_damaged_transfers_fail_loudly_and_nothing_is_published(provider, board, mcu, tmp_path, setting, reason):
    setattr(board, setting, True)

    with pytest.raises(MPFlashError, match=rf"damaged data at offset .* 3 times in a row: {reason}"):
        backup(mcu, tmp_path)

    assert len(board.rd_calls) == 3  # it gave up after the third attempt at the first chunk
    assert list(tmp_path.iterdir()) == []


def test_a_transient_loss_on_the_usb_link_is_retried_and_the_backup_is_still_exact(provider, board, mcu, tmp_path):
    """The Pico's USB serial was seen dropping the last 64-byte packet of a large write."""
    board.transient_failures = 2

    root = backup(mcu, tmp_path)

    assert (root / "artifacts" / "flash.bin").read_bytes() == bytes(board.flash)
    assert board.rd_calls[0] == board.rd_calls[1] == board.rd_calls[2]  # the same chunk was requested three times


@pytest.mark.parametrize(
    "reply, length, problem",
    [
        (b"", 4, "cut short"),
        (b"AAAAAA==", 4, "cut short"),
        (b"!!!.00000000", 4, "holds 0 bytes, expected 4"),  # non-strict base64 discards junk; the length check catches it
        (b"AAAAAA==.zzzzzzzz", 4, "not valid base64"),
        (b"AAAAAA==.00000000", 5, "holds 4 bytes, expected 5"),
        (b"AAAAAA==.12345678", 4, "checksum does not match"),
    ],
)
def test_damaged_replies_are_rejected_with_a_reason(reply, length, problem):
    data, why = rp2._decode_chunk(reply, length)

    assert data is None and problem in why


def test_a_valid_reply_is_accepted():
    payload = bytes(range(20))
    reply = binascii.b2a_base64(payload, newline=False) + b"." + b"%08x" % binascii.crc32(payload)

    assert rp2._decode_chunk(reply + b"\r\n", 20) == (payload, "")


def test_backup_refuses_a_flash_size_that_conflicts_with_the_filesystem(isolated_registry, monkeypatch, mcu, tmp_path):
    board = FakeBoard(make_image(), fs_bytes=2 * MIB)  # a filesystem bigger than the detected flash
    install(monkeypatch, board)
    registry.register(Rp2FlashProvider(opener=opener_for(board)))

    with pytest.raises(MPFlashError, match="inconsistent with the board's filesystem"):
        backup(mcu, tmp_path)


def test_backup_of_a_fully_erased_flash_works(isolated_registry, monkeypatch, mcu, tmp_path):
    # Only the first block is data, so the alias probe still has something to compare.
    image = bytearray(b"\xff" * MIB)
    image[:BLOCK] = random.Random(5).randbytes(BLOCK)
    board = FakeBoard(bytes(image))
    install(monkeypatch, board)
    registry.register(Rp2FlashProvider(opener=opener_for(board)))

    root = backup(mcu, tmp_path)

    assert (root / "artifacts" / "flash.bin").read_bytes() == bytes(image)
    assert board.rd_calls == [(0, BLOCK)]


# ---------------------------------------------------------------------------
# UF2
# ---------------------------------------------------------------------------


def test_uf2_blocks_follow_the_boot_rom_format():
    image = bytes(range(256)) * 32  # 8 KiB
    uf2 = build_uf2(image, [1])

    assert len(uf2) == 16 * 512
    first = struct.unpack_from("<8I", uf2)
    assert first == (0x0A324655, 0x9E5D5157, 0x2000, XIP_BASE + BLOCK, 256, 0, 16, UF2_FAMILY_RP2040)
    assert uf2[32:288] == image[BLOCK : BLOCK + 256]
    assert struct.unpack_from("<I", uf2, 508)[0] == 0x0AB16F30
    assert uf2[288:508] == bytes(220)


def test_uf2_covers_whole_sectors_in_ascending_order():
    uf2 = build_uf2(bytes(4 * BLOCK), [3, 0])

    addresses = [struct.unpack_from("<8I", uf2, i * 512)[3] for i in range(32)]
    assert addresses == sorted(addresses)
    assert addresses[0] == XIP_BASE and addresses[16] == XIP_BASE + 3 * BLOCK and addresses[-1] == XIP_BASE + 4 * BLOCK - 256
    assert [struct.unpack_from("<8I", uf2, i * 512)[5:7] for i in (0, 31)] == [(0, 32), (31, 32)]


def test_uf2_for_no_blocks_is_empty():
    assert build_uf2(bytes(BLOCK), []) == b""


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


@pytest.fixture
def bundle(provider, board, mcu, tmp_path):
    original = bytes(board.flash)
    root = backup(mcu, tmp_path)
    board.opens.clear()
    return read_bundle(root), original


def damage(board: FakeBoard, blocks=(10, 200, 255)):
    for block in blocks:
        board.flash[block * BLOCK : block * BLOCK + 50] = b"DAMAGE" * 8 + b"!!"


def test_restore_rewrites_only_the_sectors_that_differ(provider, board, bundle, mcu):
    bundle_, original = bundle
    damage(board)  # 10 is firmware, 200 and 255 were erased/file blocks

    run_restore(plan_restore(bundle_, mcu), mcu)

    assert bytes(board.flash) == original
    assert provider.flashed == [[10, 200, 255]]


def test_restore_restores_a_sector_that_was_erased_in_the_backup(provider, board, bundle, mcu):
    bundle_, original = bundle
    assert original[100 * BLOCK : 101 * BLOCK] == b"\xff" * BLOCK  # erased in the backup
    board.flash[100 * BLOCK : 101 * BLOCK] = b"\x00" * BLOCK  # now holds data

    run_restore(plan_restore(bundle_, mcu), mcu)

    assert bytes(board.flash) == original


def test_restore_of_an_identical_flash_writes_nothing_and_skips_the_bootloader(provider, board, bundle, mcu):
    bundle_, _ = bundle

    run_restore(plan_restore(bundle_, mcu), mcu)

    assert provider.flashed == []


def test_restore_plan_describes_the_work_without_changing_the_board(provider, board, bundle, mcu):
    bundle_, _ = bundle
    damage(board)
    before = bytes(board.flash)

    plan = plan_restore(bundle_, mcu)

    text = "\n".join(plan.lines)
    assert "rewrite 3 of 256 flash sectors of 4 KiB (12288 bytes)" in text and "BOOTSEL" in text
    assert bytes(board.flash) == before and provider.flashed == []
    assert board.opens == [False]  # the dry run does not disturb the running program


def test_plan_for_an_identical_flash_says_nothing_will_be_written(provider, bundle, mcu):
    bundle_, _ = bundle

    assert "nothing will be written" in "\n".join(plan_restore(bundle_, mcu).lines)


def test_restore_replaces_the_filesystem_it_covers(provider, bundle, mcu):
    bundle_, _ = bundle

    plan = plan_restore(bundle_, mcu)

    assert [item.component for item in plan.items] == [FLASH]


def test_restore_rejects_a_board_with_a_different_flash_size(isolated_registry, monkeypatch, bundle, mcu):
    bundle_, _ = bundle
    other = FakeBoard(make_image(2 * MIB))
    install(monkeypatch, other)
    flashed = []
    registry._providers.clear()
    registry.register(Rp2FlashProvider(opener=opener_for(other), flasher=lambda m, p: flashed.append(p)))

    with pytest.raises(MPFlashError, match="image is 1048576 bytes but this board has 2097152 bytes of flash"):
        plan_restore(bundle_, mcu)

    assert flashed == []


def test_restore_reports_bootloader_failures_with_progress(provider, board, bundle, mcu):
    bundle_, _ = bundle
    damage(board)
    plan = plan_restore(bundle_, mcu)

    def fail(mcu_, path):
        raise MPFlashError("Could not put COM9 into the UF2 (BOOTSEL) bootloader")

    provider._flash = fail

    with pytest.raises(MPFlashError, match="Restore of flash by rp2-flash failed: Could not put COM9 into the UF2"):
        run_restore(plan, mcu)


def test_restore_fails_loudly_when_the_result_does_not_verify(provider, board, bundle, mcu):
    bundle_, _ = bundle
    damage(board)
    plan = plan_restore(bundle_, mcu)

    def flash_wrongly(mcu_, path: Path):
        apply_uf2(board, path.read_bytes())
        board.flash[10 * BLOCK] ^= 0xFF  # the bootloader wrote something else

    provider._flash = flash_wrongly

    with pytest.raises(MPFlashError, match="does not match the backup after restoring it"):
        run_restore(plan, mcu)


def test_restore_only_accepts_a_raw_image_at_the_flash_base(provider, mcu, tmp_path):
    with BundleWriter(tmp_path, "odd") as writer:
        writer.add_artifact_bytes(
            "flash.bin",
            b"x" * BLOCK,
            component=FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider="esptool-flash",
            address=0,
            length=BLOCK,
        )
        root = writer.commit(DeviceIdentity.from_mcu(mcu))

    with pytest.raises(MPFlashError, match="starts at 0x10000000"):
        plan_restore(read_bundle(root), mcu)


def test_the_default_flasher_uses_the_uf2_bootloader_path(monkeypatch, mcu, tmp_path):
    calls = []
    monkeypatch.setattr("mpflash.flash.registry.get_backend", lambda name: calls.append(("backend", name)) or "uf2-backend")
    monkeypatch.setattr(
        "mpflash.flash.services.default_services.enter_bootloader",
        lambda m, method, backend=None: calls.append(("enter", backend)) or True,
    )
    monkeypatch.setattr("mpflash.flash.builtins.uf2.flash_uf2", lambda m, path: calls.append(("copy", path.name)) or m)

    rp2.flash_through_bootloader(mcu, tmp_path / "restore.uf2")

    assert calls == [("backend", "uf2"), ("enter", "uf2-backend"), ("copy", "restore.uf2")]


@pytest.mark.parametrize("enter, copy, message", [(False, True, "Could not put"), (True, None, "Copying the restore image")])
def test_the_default_flasher_reports_each_failure(monkeypatch, mcu, tmp_path, enter, copy, message):
    monkeypatch.setattr("mpflash.flash.registry.get_backend", lambda name: object())
    monkeypatch.setattr("mpflash.flash.services.default_services.enter_bootloader", lambda m, method, backend=None: enter)
    monkeypatch.setattr("mpflash.flash.builtins.uf2.flash_uf2", lambda m, path: copy)

    with pytest.raises(MPFlashError, match=message):
        rp2.flash_through_bootloader(mcu, tmp_path / "restore.uf2")
