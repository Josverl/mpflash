"""Raw flash backup and restore for RP2040 boards, without picotool.

Backup reads the whole QSPI flash from the running MicroPython: the RP2040 maps its flash at
``0x10000000`` (XIP), which ``uctypes`` can read directly. Restore builds a UF2 containing only the
4 KiB sectors that differ from the board and copies it through the board's UF2 (BOOTSEL) bootloader.

Why not picotool: it needs a WinUSB driver bound with Zadig on Windows (an administrator-level,
system-wide change; measured on the development machine, picotool could not connect without it), it
cannot be installed with pip or winget, and the only Python PICOBOOT library is AGPL-licensed.

How the reads stay fast and correct (measured on a Pico LiPo 16MB):

* Streaming the flash with one long ``print`` loop silently loses data, so reads are request/response.
* The host reads the serial port in bulk (see :mod:`mpflash.backup.devicefs`): mpremote's one-byte-at-a-time
  reader capped throughput near 20 KiB/s; bulk reads reach ~260 KiB/s.
* Chunks are written to stdout as base64 and carry a CRC32. The Pico's USB serial was seen dropping the
  last 64-byte packet of a large write, so a damaged chunk is requested again.
* Erased (all 0xFF) 4 KiB blocks are not transferred; a board that is mostly empty is read in seconds.
* The whole image is checked against a SHA-256 computed on the board, which also verifies a restore
  without downloading the flash again.

Only RP2040 is supported. RP2350 uses another UF2 family, partition tables and secure boot.
"""

from __future__ import annotations

import binascii
import hashlib
import shutil
import struct
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Protocol, Sequence, Set, Tuple

from mpflash.backup.base import BackupContext, BackupOutput, BackupProvider
from mpflash.backup.bundle import Bundle
from mpflash.backup.devicefs import open_device_fs
from mpflash.backup.models import Artifact, ArtifactRole, ComponentKind, Exactness, ProviderCapability
from mpflash.backup.registry import register
from mpflash.errors import MPFlashError
from mpflash.logger import log

FLASH_NAME = "flash.bin"
XIP_BASE = 0x10000000
BLOCK = 4096  # flash erase unit
UF2_PAYLOAD = 256  # flash program unit
UF2_FAMILY_RP2040 = 0xE48BFF56
_UF2_MAGIC = (0x0A324655, 0x9E5D5157)
_UF2_END = 0x0AB16F30
_UF2_FLAG_FAMILY = 0x00002000
READ_CHUNK = 6 * BLOCK  # 24 KiB: ~260 KiB/s over USB-CDC; larger chunks gain nothing
_DISK_MARGIN = 16 * 1024 * 1024
_DIGEST_BYTES = 8
_DIGESTS_PER_CALL = 256

EXCLUSIONS = (
    "Only the external QSPI flash is included; RAM and the RP2040 boot ROM are not.",
    "Erased (all 0xFF) 4 KiB blocks were not transferred; they are stored as erased flash.",
)
#: A raw image contains the filesystem and ROMFS regions, so restoring it replaces both.
COVERS = (ComponentKind.VFS, ComponentKind.ROMFS)

# Runs on the board (MicroPython). Kept dependency-free so it can also be executed by CPython in tests.
DEVICE_CODE = r"""
import binascii, hashlib, sys, uctypes
_X = 0x10000000
_A = uctypes.bytearray_at
def _size():
    head = bytes(_A(_X, 4096))
    s = 262144
    while s < 16777216:
        if bytes(_A(_X + s, 4096)) == head:
            return s
        s *= 2
    return s
def _fs():
    import rp2
    return rp2.Flash().ioctl(4, 0) * 4096
def _blank(n):
    f = b"\xff" * 4096
    k = n // 4096
    m = bytearray((k + 7) // 8)
    for i in range(k):
        if bytes(_A(_X + i * 4096, 4096)) == f:
            m[i >> 3] |= 1 << (i & 7)
    return bytes(m)
def _rd(o, n):
    d = _A(_X + o, n)
    sys.stdout.write(binascii.b2a_base64(d, newline=False))
    sys.stdout.write(".%08x" % (binascii.crc32(d) & 0xFFFFFFFF))
def _sectors(a, c):
    h = hashlib.sha256
    return b"".join(h(_A(_X + i * 4096, 4096)).digest()[:8] for i in range(a, a + c))
def _sha(n):
    h = hashlib.sha256()
    for o in range(0, n, 65536):
        h.update(_A(_X + o, min(65536, n - o)))
    return h.digest()
"""


READ_ATTEMPTS = 3


def _decode_chunk(reply: bytes, length: int) -> Tuple[Optional[bytes], str]:
    """Return ``(data, "")`` for a valid ``base64.crc32hex`` reply, otherwise ``(None, why)``."""
    payload, separator, crc = reply.strip().partition(b".")
    if not separator:
        return None, "the reply was cut short before its checksum"
    try:
        data = binascii.a2b_base64(payload)
        expected = int(crc, 16)
    except ValueError:  # binascii.Error is a ValueError
        return None, "the reply is not valid base64 and a checksum"
    if len(data) != length:
        return None, f"it holds {len(data)} bytes, expected {length}"
    if binascii.crc32(data) != expected:
        return None, "the checksum does not match"
    return data, ""


class Repl(Protocol):
    """A raw REPL connection to the board."""

    def exec(self, command: str, timeout: float = 10) -> bytes: ...

    def eval(self, expression: str, timeout: float = 10) -> Any: ...


class Rp2Device(Protocol):
    """What the provider needs to know about a board's flash."""

    def flash_size(self) -> int: ...

    def filesystem_bytes(self) -> int: ...

    def blank_blocks(self, size: int) -> Set[int]:
        """Return the indexes of 4 KiB blocks that are entirely erased (0xFF)."""
        ...

    def read(self, offset: int, length: int) -> bytes: ...

    def block_digests(self, size: int) -> List[bytes]:
        """Return a short digest for every 4 KiB block."""
        ...

    def sha256(self, size: int) -> str: ...


class ReplFlash:
    """:class:`Rp2Device` implemented by running :data:`DEVICE_CODE` over a raw REPL."""

    def __init__(self, repl: Repl):
        self._repl = repl
        repl.exec(DEVICE_CODE)

    def flash_size(self) -> int:
        return int(self._repl.eval("_size()"))

    def filesystem_bytes(self) -> int:
        return int(self._repl.eval("_fs()"))

    def blank_blocks(self, size: int) -> Set[int]:
        bits = bytes(self._repl.eval(f"_blank({size})", timeout=60))
        return {i for i in range(size // BLOCK) if bits[i >> 3] >> (i & 7) & 1}

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes at ``offset``, retrying chunks that arrive damaged.

        The board's USB serial can drop the tail of a large write, so every chunk carries a CRC32 and
        is requested again when it is short, malformed or fails the check.
        """
        problem = ""
        for attempt in range(1, READ_ATTEMPTS + 1):
            # Written straight to stdout as base64: print(repr(...)) is several times slower on the board.
            reply = self._repl.exec(f"_rd({offset}, {length})", timeout=30)
            data, problem = _decode_chunk(reply, length)
            if data is not None:
                return data
            log.warning(f"Flash read at {offset:#x} failed ({problem}); attempt {attempt} of {READ_ATTEMPTS}")
        raise MPFlashError(f"The board returned damaged data at offset {offset:#x} {READ_ATTEMPTS} times in a row: {problem}")

    def block_digests(self, size: int) -> List[bytes]:
        digests: List[bytes] = []
        total = size // BLOCK
        for first in range(0, total, _DIGESTS_PER_CALL):
            count = min(_DIGESTS_PER_CALL, total - first)
            raw = bytes(self._repl.eval(f"_sectors({first}, {count})", timeout=60))
            if len(raw) != count * _DIGEST_BYTES:
                raise MPFlashError("The board returned an incomplete list of flash digests")
            digests.extend(raw[i : i + _DIGEST_BYTES] for i in range(0, len(raw), _DIGEST_BYTES))
        return digests

    def sha256(self, size: int) -> str:
        return bytes(self._repl.eval(f"_sha({size})", timeout=60 + size / (1024 * 1024) * 3)).hex()


# ---------------------------------------------------------------------------
# UF2
# ---------------------------------------------------------------------------


def build_uf2(image: bytes, blocks: Sequence[int]) -> bytes:
    """Build a UF2 that programs the given 4 KiB ``blocks`` of ``image`` into RP2040 flash.

    Every block is written in full (16 pages of 256 bytes), including erased ones, because the boot
    ROM only erases a sector when it is written to.
    """
    pages = [(block * BLOCK + page * UF2_PAYLOAD) for block in sorted(blocks) for page in range(BLOCK // UF2_PAYLOAD)]
    out = bytearray()
    for number, offset in enumerate(pages):
        header = struct.pack("<8I", *_UF2_MAGIC, _UF2_FLAG_FAMILY, XIP_BASE + offset, UF2_PAYLOAD, number, len(pages), UF2_FAMILY_RP2040)
        payload = image[offset : offset + UF2_PAYLOAD]
        out += header + payload + bytes(476 - UF2_PAYLOAD) + struct.pack("<I", _UF2_END)
    return bytes(out)


def _nonblank_runs(blank: Set[int], total: int) -> Iterator[Tuple[int, int]]:
    """Yield ``(first_block, block_count)`` for each run of blocks that are not erased."""
    start: Optional[int] = None
    for index in range(total):
        if index in blank:
            if start is not None:
                yield start, index - start
                start = None
        elif start is None:
            start = index
    if start is not None:
        yield start, total - start


def _differing_blocks(image: bytes, device: Rp2Device, size: int) -> List[int]:
    wanted = [hashlib.sha256(image[i : i + BLOCK]).digest()[:_DIGEST_BYTES] for i in range(0, size, BLOCK)]
    current = device.block_digests(size)
    return [index for index, (a, b) in enumerate(zip(wanted, current)) if a != b]


def flash_through_bootloader(mcu: Any, uf2: Path) -> None:
    """Put the board into BOOTSEL, copy ``uf2`` to its drive and wait for it to come back."""
    from mpflash.common import BootloaderMethod
    from mpflash.flash.builtins.uf2 import flash_uf2
    from mpflash.flash.registry import get_backend
    from mpflash.flash.services import default_services

    backend = get_backend("uf2")
    if not default_services.enter_bootloader(mcu, BootloaderMethod.AUTO, backend=backend):
        raise MPFlashError(f"Could not put {mcu.serialport} into the UF2 (BOOTSEL) bootloader")
    if flash_uf2(mcu, uf2) is None:
        raise MPFlashError("Copying the restore image to the UF2 bootloader failed, or the board did not come back afterwards")


Opener = Callable[..., "AbstractContextManager[Repl]"]
Flasher = Callable[[Any, Path], None]


def _flash_artifact(artifacts: Sequence[Artifact]) -> Artifact:
    raw = [a for a in artifacts if a.component is ComponentKind.FLASH and a.role is ArtifactRole.DEVICE_READ]
    if len(raw) != 1 or len(artifacts) != 1:
        raise MPFlashError("The bundle must contain exactly one raw flash image to restore")
    artifact = raw[0]
    if artifact.address != XIP_BASE or artifact.length is None or artifact.length % BLOCK:
        raise MPFlashError("Only a raw RP2040 flash image that starts at 0x10000000 can be restored")
    return artifact


class Rp2FlashProvider(BackupProvider):
    """Back up and restore the whole flash of an RP2040 board running MicroPython."""

    name = "rp2-flash"
    priority = 10

    def __init__(self, opener: Opener = open_device_fs, flasher: Flasher = flash_through_bootloader):
        self._open = opener
        self._flash = flasher

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        if not getattr(mcu, "connected", False) or getattr(mcu, "family", "") != "micropython":
            return ()
        if getattr(mcu, "port", "") != "rp2" or str(getattr(mcu, "cpu", "")).upper() != "RP2040":
            return ()
        return (
            ProviderCapability(
                component=ComponentKind.FLASH,
                can_backup=True,
                can_restore=True,
                exactness=Exactness.EXACT,
                covers=COVERS,
                exclusions=EXCLUSIONS,
            ),
        )

    # -- backup ------------------------------------------------------------

    def backup(self, mcu: Any, component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        writer = ctx.writer
        target = writer.artifact_path(FLASH_NAME)
        with self._open(mcu.serialport, soft_reset=True) as repl:
            device = ReplFlash(repl)
            size = self._detect_size(device)
            free = shutil.disk_usage(target.parent).free
            if free < size + _DISK_MARGIN:
                raise MPFlashError(f"Not enough disk space: the {size}-byte flash image needs more than the {free} bytes free")
            blank = device.blank_blocks(size)
            image = bytearray(b"\xff" * size)
            transferred = 0
            for first, count in _nonblank_runs(blank, size // BLOCK):
                end = (first + count) * BLOCK
                for offset in range(first * BLOCK, end, READ_CHUNK):
                    length = min(READ_CHUNK, end - offset)
                    data = device.read(offset, length)
                    if len(data) != length:
                        raise MPFlashError(f"The board returned {len(data)} bytes at offset {offset:#x}, expected {length}")
                    image[offset : offset + length] = data
                    transferred += length
                log.info(f"Read {transferred // 1024} KiB of flash from {mcu.serialport}")
            digest = hashlib.sha256(image).hexdigest()
            if device.sha256(size) != digest:
                raise MPFlashError(
                    "The flash read did not match the SHA-256 calculated on the board; the transfer was corrupted. No backup was created."
                )
        target.write_bytes(bytes(image))
        writer.register_artifact(
            FLASH_NAME,
            component=ComponentKind.FLASH,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider=self.name,
            address=XIP_BASE,
            length=size,
            covers=COVERS,
            exclusions=EXCLUSIONS,
        )
        erased = len(blank)
        note = (
            f"Flash: {size} bytes of RP2040 flash read through the REPL and verified by SHA-256 on the board; "
            f"{erased} of {size // BLOCK} erased blocks were not transferred. It includes the filesystem."
        )
        return BackupOutput(notes=(note,))

    @staticmethod
    def _detect_size(device: Rp2Device) -> int:
        size = device.flash_size()
        if size < BLOCK or size % BLOCK or size <= device.filesystem_bytes():
            raise MPFlashError(
                f"The detected flash size of {size} bytes is inconsistent with the board's filesystem; refusing to back it up"
            )
        return size

    # -- restore -----------------------------------------------------------

    def describe_restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> Sequence[str]:
        artifact = _flash_artifact(artifacts)
        assert artifact.length is not None
        image = bundle.artifact_path(artifact).read_bytes()
        with self._open(mcu.serialport, soft_reset=False) as repl:
            device = ReplFlash(repl)
            self._check_size(device, artifact.length)
            blocks = _differing_blocks(image, device, artifact.length)
        total = artifact.length // BLOCK
        if not blocks:
            return [f"the flash already matches the backup ({artifact.length} bytes); nothing will be written"]
        return [
            f"rewrite {len(blocks)} of {total} flash sectors of 4 KiB ({len(blocks) * BLOCK} bytes) that differ from the backup",
            "this replaces firmware and/or filesystem data in those sectors",
            "the board is switched to its UF2 (BOOTSEL) bootloader and back, then verified by SHA-256 of the whole flash",
        ]

    def restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> None:
        artifact = _flash_artifact(artifacts)
        assert artifact.length is not None
        size = artifact.length
        image = bundle.artifact_path(artifact).read_bytes()
        with self._open(mcu.serialport, soft_reset=True) as repl:
            device = ReplFlash(repl)
            self._check_size(device, size)
            blocks = _differing_blocks(image, device, size)
        if blocks:
            log.info(f"Writing {len(blocks)} of {size // BLOCK} flash sectors through the UF2 bootloader")
            with tempfile.TemporaryDirectory(prefix="mpflash-restore-") as folder:
                uf2 = Path(folder) / "restore.uf2"
                uf2.write_bytes(build_uf2(image, blocks))
                self._flash(mcu, uf2)
        else:
            log.info("The flash already matches the backup; verifying only")
        with self._open(mcu.serialport, soft_reset=True) as repl:
            written = ReplFlash(repl).sha256(size)
        if written != artifact.sha256:
            raise MPFlashError(
                "The flash does not match the backup after restoring it "
                "(a script that runs at boot may have written to the filesystem). Run the restore again."
            )

    @staticmethod
    def _check_size(device: Rp2Device, expected: int) -> None:
        size = device.flash_size()
        if size != expected:
            raise MPFlashError(f"The image is {expected} bytes but this board has {size} bytes of flash; they must be identical")


register(Rp2FlashProvider())
