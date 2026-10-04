"""ROMFS provider: the code that runs on the board (memory-mapped and block-device partitions) and the round trip."""

import random
import sys
import types
from contextlib import contextmanager
from typing import List

import pytest
from fake_device import fake_mcu
from test_backup_rp2 import FakeRepl as _Repl

from mpflash.backup import registry
from mpflash.backup.builtins.romfs import ROMFS_HEADER, RomfsDevice, RomfsProvider
from mpflash.backup.bundle import read_bundle
from mpflash.backup.models import ArtifactRole, ComponentKind, Exactness
from mpflash.backup.service import plan_backup, plan_restore, run_backup, run_restore
from mpflash.errors import MPFlashError

ROMFS = ComponentKind.ROMFS
PARTITION = 64 * 1024
BLOCK = 4096


def varint(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def make_romfs(payload: int = 1500, seed: int = 1) -> bytes:
    return ROMFS_HEADER + varint(payload) + random.Random(seed).randbytes(payload)


class BlockDevice:
    """A flash partition behind ``ioctl``/``readblocks``/``writeblocks``, like nRF and ESP32."""

    def __init__(self, board: "FakeRomBoard"):
        self.board = board

    def ioctl(self, op: int, arg: int):
        if op == 4:
            return len(self.board.rom) // BLOCK
        if op == 5:
            return BLOCK
        if op == 6:
            self.board.erase(arg * BLOCK, BLOCK)
            return 0
        raise OSError(op)

    def readblocks(self, number: int, buf: bytearray, offset: int = 0) -> None:
        start = number * BLOCK + offset
        buf[:] = self.board.rom[start : start + len(buf)]

    def writeblocks(self, number: int, buf: bytes, offset: int = 0) -> None:
        self.board.program(number * BLOCK + offset, bytes(buf))


class FakeRomBoard:
    """A board whose ROMFS partition is either mapped memory (``rom_ioctl`` returns a buffer) or a block device."""

    def __init__(self, image: bytes = b"", *, block_device: bool = False, partition: int = PARTITION, has_rom: bool = True):
        self.rom = bytearray(b"\xff" * partition)
        self.rom[: len(image)] = image
        self.block_device, self.has_rom = block_device, has_rom
        self.erased: List[tuple] = []
        self.corrupt_reads = 0
        self.corrupt_writes = False
        self.opens: List[bool] = []
        self.unmounted: List[str] = []

    def erase(self, start: int, length: int) -> None:
        self.erased.append((start, length))
        self.rom[start : start + length] = b"\xff" * length

    def program(self, start: int, data: bytes) -> None:
        assert all(byte == 0xFF for byte in self.rom[start : start + len(data)]), "writing to flash that was not erased"
        if self.corrupt_writes:
            data = bytes([data[0] ^ 1]) + data[1:]
        self.rom[start : start + len(data)] = data

    def vfs_module(self) -> types.SimpleNamespace:
        board = self
        device = BlockDevice(self)

        def rom_ioctl(op, *args):
            if op == 1:
                return 1
            if op == 2:
                return device if board.block_device else memoryview(board.rom)
            if op == 3:
                start, length = (0, args[1]) if len(args) == 2 else (args[1], args[2])
                board.erase(start, length)
                return BLOCK
            if op == 4:
                board.program(args[1], bytes(args[2]))
                return 0
            if op == 5:
                return 0
            if op == 6:
                return BLOCK
            raise OSError(op)

        module = types.SimpleNamespace(umount=board.unmounted.append)
        if board.has_rom:
            module.rom_ioctl = rom_ioctl
        return module


class RomRepl(_Repl):
    def __init__(self, board: FakeRomBoard):
        self.board = board
        self.namespace: dict = {}
        self.timeouts: List[float] = []

    def exec(self, command: str, timeout: float = 10) -> bytes:
        self.timeouts.append(timeout)
        if command.startswith("_rd(") and self.board.corrupt_reads:
            self.board.corrupt_reads -= 1
            return b"AAAA.00000000"
        return self._run(command)

    def _run(self, command: str) -> bytes:
        from test_backup_rp2 import _Stdout

        stdout, original = _Stdout(), sys.stdout
        sys.stdout = stdout  # type: ignore[assignment]
        try:
            exec(command, self.namespace)
        finally:
            sys.stdout = original
        return bytes(stdout.captured)


def install(monkeypatch, board: FakeRomBoard) -> None:
    monkeypatch.setitem(sys.modules, "vfs", board.vfs_module())


def opener_for(board: FakeRomBoard, fail: bool = False):
    @contextmanager
    def open_repl(serialport: str, *, soft_reset: bool = True):
        if fail:
            raise MPFlashError("could not enter raw repl")
        board.opens.append(soft_reset)
        yield RomRepl(board)

    return open_repl


@pytest.fixture(params=[False, True], ids=["mapped", "block-device"])
def layout(request) -> bool:
    return request.param


@pytest.fixture
def mcu():
    return fake_mcu(port="samd", cpu="SAMD51P19A", board_id="SEEED_WIO_TERMINAL", board="SEEED_WIO_TERMINAL", version="1.29.0")


def register_provider(monkeypatch, isolated_registry, board: FakeRomBoard, **options) -> RomfsProvider:
    install(monkeypatch, board)
    provider = RomfsProvider(opener=opener_for(board, **options))
    registry.register(provider)
    return provider


# ---------------------------------------------------------------------------
# the code that runs on the board
# ---------------------------------------------------------------------------


def test_probe_reports_the_partition_and_the_image_length_from_its_header(monkeypatch, layout):
    image = make_romfs(1500)
    board = FakeRomBoard(image, block_device=layout)
    install(monkeypatch, board)

    assert RomfsDevice(RomRepl(board)).probe() == (1, PARTITION, BLOCK, len(image))


@pytest.mark.parametrize("content", [b"", b"\x00" * 64, ROMFS_HEADER + varint(10**6) + b"x" * 8])
def test_probe_reports_no_image_for_an_empty_or_inconsistent_partition(monkeypatch, layout, content):
    board = FakeRomBoard(content, block_device=layout)
    install(monkeypatch, board)

    assert RomfsDevice(RomRepl(board)).probe()[3] == 0


def test_probe_reports_nothing_without_rom_ioctl(monkeypatch):
    board = FakeRomBoard(make_romfs(), has_rom=False)
    install(monkeypatch, board)

    assert RomfsDevice(RomRepl(board)).probe() == (0, 0, 0, 0)


def test_images_larger_than_one_read_chunk_are_read_whole(monkeypatch, layout):
    image = make_romfs(40_000)
    board = FakeRomBoard(image, block_device=layout)
    install(monkeypatch, board)
    device = RomfsDevice(RomRepl(board))

    assert b"".join(device.read(o, min(16384, len(image) - o)) for o in range(0, len(image), 16384)) == image


def test_a_damaged_read_is_requested_again(monkeypatch):
    image = make_romfs()
    board = FakeRomBoard(image)
    install(monkeypatch, board)
    board.corrupt_reads = 2

    assert RomfsDevice(RomRepl(board)).read(0, len(image)) == image


def test_a_read_that_stays_damaged_is_an_error(monkeypatch):
    board = FakeRomBoard(make_romfs())
    install(monkeypatch, board)
    board.corrupt_reads = 99

    with pytest.raises(MPFlashError, match="damaged ROMFS data"):
        RomfsDevice(RomRepl(board)).read(0, 100)


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_a_board_with_an_image_offers_exact_backup_and_restore(monkeypatch, isolated_registry, mcu, layout):
    provider = register_provider(monkeypatch, isolated_registry, FakeRomBoard(make_romfs(), block_device=layout))

    (capability,) = provider.capabilities(mcu)

    assert capability.component is ROMFS and capability.can_backup and capability.can_restore
    assert capability.exactness is Exactness.EXACT and capability.exclusions


def test_an_empty_partition_can_be_restored_to_but_has_nothing_to_back_up(monkeypatch, isolated_registry, mcu):
    provider = register_provider(monkeypatch, isolated_registry, FakeRomBoard())

    (capability,) = provider.capabilities(mcu)

    assert capability.can_restore and not capability.can_backup


@pytest.mark.parametrize(
    "overrides",
    [{"connected": False}, {"family": "circuitpython"}, {"port": "esp8266"}, {"version": "1.24.1"}],
)
def test_boards_that_cannot_have_a_romfs_are_not_probed(monkeypatch, isolated_registry, mcu, overrides):
    board = FakeRomBoard(make_romfs())
    provider = register_provider(monkeypatch, isolated_registry, board)
    for name, value in overrides.items():
        setattr(mcu, name, value)

    assert provider.capabilities(mcu) == ()
    assert board.opens == []


@pytest.mark.parametrize("version", ["v1.25.0", "1.29.0-preview", "2.0", "unknown", ""])
def test_newer_or_unknown_versions_are_probed(monkeypatch, isolated_registry, mcu, version):
    provider = register_provider(monkeypatch, isolated_registry, FakeRomBoard(make_romfs()))
    mcu.version = version

    assert len(provider.capabilities(mcu)) == 1


def test_a_board_without_rom_ioctl_offers_nothing(monkeypatch, isolated_registry, mcu):
    provider = register_provider(monkeypatch, isolated_registry, FakeRomBoard(make_romfs(), has_rom=False))

    assert provider.capabilities(mcu) == ()


def test_a_board_that_cannot_be_reached_offers_nothing(monkeypatch, isolated_registry, mcu):
    provider = register_provider(monkeypatch, isolated_registry, FakeRomBoard(make_romfs()), fail=True)

    assert provider.capabilities(mcu) == ()


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


def test_backup_stores_the_exact_image_and_verifies_it(monkeypatch, isolated_registry, mcu, layout, tmp_path):
    image = make_romfs(5000)
    register_provider(monkeypatch, isolated_registry, FakeRomBoard(image, block_device=layout))

    root = run_backup(mcu, plan_backup(mcu, [ROMFS]), tmp_path)

    bundle = read_bundle(root)
    bundle.verify()
    (artifact,) = bundle.manifest.artifacts
    assert (artifact.component, artifact.role, artifact.exactness) == (ROMFS, ArtifactRole.DEVICE_READ, Exactness.EXACT)
    assert artifact.length == artifact.size == len(image)
    assert (root / "artifacts" / "romfs.img").read_bytes() == image


def test_restore_replaces_a_different_image_with_the_backup_byte_for_byte(monkeypatch, isolated_registry, mcu, layout, tmp_path):
    original = make_romfs(5000, seed=1)
    board = FakeRomBoard(original, block_device=layout)
    register_provider(monkeypatch, isolated_registry, board)
    root = run_backup(mcu, plan_backup(mcu, [ROMFS]), tmp_path)

    other = make_romfs(900, seed=2)
    board.rom[:] = b"\xff" * PARTITION
    board.rom[: len(other)] = other
    plan = plan_restore(read_bundle(root), mcu)
    assert any("ROMFS" in line for line in plan.lines)
    run_restore(plan, mcu)

    assert bytes(board.rom[: len(original)]) == original
    assert board.unmounted == ["/rom"]  # the partition cannot be erased while it is mounted
    mcu.wait_for_restart.assert_called_once_with(timeout=20)


def test_restore_reports_a_corrupted_write(monkeypatch, isolated_registry, mcu, tmp_path):
    board = FakeRomBoard(make_romfs(3000))
    register_provider(monkeypatch, isolated_registry, board)
    root = run_backup(mcu, plan_backup(mcu, [ROMFS]), tmp_path)
    board.corrupt_writes = True

    with pytest.raises(MPFlashError, match="does not match the backup"):
        run_restore(plan_restore(read_bundle(root), mcu), mcu)


def test_restore_fails_when_the_board_does_not_come_back(monkeypatch, isolated_registry, mcu, tmp_path):
    register_provider(monkeypatch, isolated_registry, FakeRomBoard(make_romfs()))
    root = run_backup(mcu, plan_backup(mcu, [ROMFS]), tmp_path)
    mcu.wait_for_restart.return_value = False

    with pytest.raises(MPFlashError, match="did not reconnect"):
        run_restore(plan_restore(read_bundle(root), mcu), mcu)


def test_restore_to_a_smaller_partition_is_refused_before_anything_is_erased(monkeypatch, isolated_registry, mcu, tmp_path):
    source = FakeRomBoard(make_romfs(20_000))
    register_provider(monkeypatch, isolated_registry, source)
    root = run_backup(mcu, plan_backup(mcu, [ROMFS]), tmp_path)

    target = FakeRomBoard(partition=8 * 1024)
    register_provider(monkeypatch, isolated_registry, target)
    with pytest.raises(MPFlashError, match="only 8192 bytes"):
        plan_restore(read_bundle(root), mcu)

    assert target.erased == []


def test_restore_to_a_board_without_a_partition_is_refused(monkeypatch, isolated_registry, mcu, tmp_path):
    register_provider(monkeypatch, isolated_registry, FakeRomBoard(make_romfs()))
    root = run_backup(mcu, plan_backup(mcu, [ROMFS]), tmp_path)

    registry._providers.clear()
    register_provider(monkeypatch, isolated_registry, FakeRomBoard(has_rom=False))
    with pytest.raises(MPFlashError):
        plan_restore(read_bundle(root), mcu)


def test_backup_of_a_partition_that_became_empty_is_an_error(monkeypatch, isolated_registry, mcu, tmp_path):
    board = FakeRomBoard(make_romfs())
    provider = register_provider(monkeypatch, isolated_registry, board)
    plan = plan_backup(mcu, [ROMFS])
    board.rom[:] = b"\xff" * PARTITION  # erased between planning and the backup

    with pytest.raises(MPFlashError, match="no valid ROMFS image"):
        run_backup(mcu, plan, tmp_path)
    assert provider is not None
