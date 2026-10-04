"""ROMFS backup and restore: the read-only filesystem image that MicroPython mounts at ``/rom``.

The image is read from the board with ``vfs.rom_ioctl`` (the interface behind ``mpremote romfs``) and
stored byte for byte, so a restore brings back exactly the files, ``.mpy`` modules and layout the board had.
The image size comes from the ROMFS header; the unused rest of the partition is not part of the backup.

Boards expose the partition either as a memory-mapped buffer (SAMD, STM32, RP2350, ...) or as a block
device (``dev.ioctl``/``readblocks``, e.g. nRF and ESP32 flash partitions). Both are supported, using the
same sequence of calls as ``mpremote romfs deploy`` to erase and write it.

Only partition 0 is handled. Boards without ``vfs.rom_ioctl`` or without a ROMFS partition do not
offer the component.
"""

from __future__ import annotations

import binascii
import hashlib
from typing import Any, Callable, ContextManager, Optional, Sequence, Tuple

from mpflash.backup.base import BackupContext, BackupOutput, BackupProvider
from mpflash.backup.builtins.rp2 import Repl
from mpflash.backup.bundle import Bundle
from mpflash.backup.devicefs import READ_ATTEMPTS, decode_chunk, open_device_fs
from mpflash.backup.models import Artifact, ArtifactRole, ComponentKind, Exactness, ProviderCapability
from mpflash.backup.registry import register
from mpflash.errors import MPFlashError
from mpflash.logger import log

IMAGE_NAME = "romfs.img"
ROMFS_HEADER = b"\xd2\xcd\x31"
READ_CHUNK = 16 * 1024
WRITE_CHUNK = 4096
_HEADER_PROBE = 12  # the ROMFS header is 3 bytes plus a variable-length size of at most 9
_MIN_ROMFS_VERSION = (1, 25)  # vfs.rom_ioctl and /rom arrived in MicroPython 1.25

EXCLUSIONS = (
    "Only the ROMFS image (its header gives the length) is stored; the unused remainder of the partition is not.",
    "Only the first ROMFS partition is handled.",
)

# Runs on the board (MicroPython). Dependency-free apart from vfs so tests can run it under CPython.
DEVICE_CODE = r"""
import binascii, hashlib, sys, vfs
def _dev():
    d = vfs.rom_ioctl(2, 0)
    if isinstance(d, int):
        raise OSError("no ROMFS partition")
    return d
def _blk(d):
    if hasattr(d, "ioctl"):
        return d.ioctl(5, 0)
    b = vfs.rom_ioctl(6, 0)
    return b if b > 0 else len(d)
def _size(d):
    if hasattr(d, "ioctl"):
        return d.ioctl(4, 0) * d.ioctl(5, 0)
    return len(d)
def _get(o, n):
    d = _dev()
    if hasattr(d, "ioctl"):
        b = d.ioctl(5, 0)
        buf = bytearray(n)
        d.readblocks(o // b, buf, o % b)
        return buf
    return memoryview(d)[o:o + n]
def _len():
    h = bytes(_get(0, 12))
    if h[:3] != b"\xd2\xcd\x31":
        return 0
    s = 0
    k = 3
    while k < 12:
        v = h[k]
        s = (s << 7) | (v & 127)
        k += 1
        if not v & 128:
            n = k + s
            return n if n <= _size(_dev()) else 0
    return 0
def _probe():
    if not hasattr(vfs, "rom_ioctl") or vfs.rom_ioctl(1) <= 0:
        return (0, 0, 0, 0)
    d = _dev()
    return (vfs.rom_ioctl(1), _size(d), _blk(d), _len())
def _rd(o, n):
    d = _get(o, n)
    sys.stdout.write(binascii.b2a_base64(d, newline=False))
    sys.stdout.write(".%08x" % (binascii.crc32(d) & 0xFFFFFFFF))
def _sha(n):
    h = hashlib.sha256()
    for o in range(0, n, 4096):
        h.update(_get(o, min(4096, n - o)))
    return h.digest()
def _prep(n):
    d = _dev()
    try:
        vfs.umount("/rom")
    except Exception:
        pass
    if hasattr(d, "ioctl"):
        b = d.ioctl(5, 0)
        for o in range(0, n, b):
            d.ioctl(6, o // b)
        return min(4096, b)
    b = _blk(d)
    m = 0
    if b < len(d):
        o = 0
        while o < n:
            p = (min(n - o, 32768) + b - 1) // b * b
            m = vfs.rom_ioctl(3, 0, o, p)
            o += p
    else:
        m = vfs.rom_ioctl(3, 0, n)
    return max(4096, m)
def _wr(o, buf):
    d = _dev()
    if hasattr(d, "ioctl"):
        b = d.ioctl(5, 0)
        d.writeblocks(o // b, buf, o % b)
    else:
        vfs.rom_ioctl(4, 0, o, buf)
def _done():
    if not hasattr(_dev(), "ioctl"):
        vfs.rom_ioctl(5, 0)
"""

Opener = Callable[..., ContextManager[Repl]]


class RomfsDevice:
    """Runs :data:`DEVICE_CODE` over a raw REPL."""

    def __init__(self, repl: Repl):
        self._repl = repl
        repl.exec(DEVICE_CODE)

    def probe(self) -> Tuple[int, int, int, int]:
        """Return ``(partitions, partition_size, block_size, image_length)``; the length is 0 when there is no valid image."""
        partitions, size, block, image = self._repl.eval("_probe()")
        return int(partitions), int(size), int(block), int(image)

    def read(self, offset: int, length: int) -> bytes:
        problem = ""
        for attempt in range(1, READ_ATTEMPTS + 1):
            reply = self._repl.exec(f"_rd({offset}, {length})", timeout=30)
            data, problem = decode_chunk(reply, length)
            if data is not None:
                return data
            log.warning(f"ROMFS read at {offset:#x} failed ({problem}); attempt {attempt} of {READ_ATTEMPTS}")
        raise MPFlashError(f"The board returned damaged ROMFS data at offset {offset:#x} {READ_ATTEMPTS} times in a row: {problem}")

    def sha256(self, length: int) -> str:
        return bytes(self._repl.eval(f"_sha({length})", timeout=30 + length / 4096)).hex()

    def prepare(self, length: int) -> int:
        """Unmount ``/rom`` and erase enough of the partition; return the write chunk size."""
        return int(self._repl.eval(f"_prep({length})", timeout=120 + length / 8192))

    def write(self, offset: int, data: bytes) -> None:
        self._repl.exec(f"_wr({offset}, binascii.a2b_base64({binascii.b2a_base64(data, newline=False)!r}))", timeout=30)

    def finish(self) -> None:
        self._repl.exec("_done()", timeout=60)


def _version_supports_romfs(version: Any) -> bool:
    parts = str(version or "").lstrip("vV").split("-")[0].split(".")
    try:
        return (int(parts[0]), int(parts[1])) >= _MIN_ROMFS_VERSION
    except (ValueError, IndexError):
        return True  # unknown: let the board answer


def _image_artifact(artifacts: Sequence[Artifact]) -> Artifact:
    images = [a for a in artifacts if a.component is ComponentKind.ROMFS and a.role is ArtifactRole.DEVICE_READ]
    if len(images) != 1 or len(artifacts) != 1:
        raise MPFlashError("The bundle must contain exactly one ROMFS image to restore")
    artifact = images[0]
    if artifact.length is None or artifact.length <= 0:
        raise MPFlashError("The ROMFS image in the bundle has no recorded length")
    return artifact


class RomfsProvider(BackupProvider):
    """Back up and restore the ROMFS partition as an exact image."""

    name = "romfs"
    priority = 10

    def __init__(self, opener: Opener = open_device_fs):
        self._open = opener

    def _probe(self, mcu: Any) -> Optional[Tuple[int, int, int, int]]:
        try:
            with self._open(mcu.serialport, soft_reset=False) as repl:
                return RomfsDevice(repl).probe()
        except Exception as error:  # noqa: BLE001 - a board that cannot answer simply has no ROMFS to offer
            log.debug(f"No ROMFS on {mcu.serialport}: {error}")
            return None

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        if not getattr(mcu, "connected", False) or getattr(mcu, "family", "") != "micropython":
            return ()
        if getattr(mcu, "port", "") == "esp8266" or not _version_supports_romfs(getattr(mcu, "version", "")):
            return ()
        probe = self._probe(mcu)
        if probe is None or probe[0] <= 0:
            return ()
        return (
            ProviderCapability(
                component=ComponentKind.ROMFS,
                can_backup=probe[3] > 0,  # an empty partition has nothing to back up
                can_restore=True,
                exactness=Exactness.EXACT,
                exclusions=EXCLUSIONS,
            ),
        )

    # -- backup ------------------------------------------------------------

    def backup(self, mcu: Any, component: ComponentKind, ctx: BackupContext) -> BackupOutput:
        writer = ctx.writer
        with self._open(mcu.serialport, soft_reset=False) as repl:
            device = RomfsDevice(repl)
            _, partition, _, length = device.probe()
            if length <= 0:
                raise MPFlashError(f"{mcu.serialport} has no valid ROMFS image to back up")
            image = bytearray()
            for offset in range(0, length, READ_CHUNK):
                image += device.read(offset, min(READ_CHUNK, length - offset))
            digest = hashlib.sha256(image).hexdigest()
            if device.sha256(length) != digest:
                raise MPFlashError("The ROMFS image did not match the SHA-256 calculated on the board; no backup was created.")
        writer.artifact_path(IMAGE_NAME).write_bytes(bytes(image))
        writer.register_artifact(
            IMAGE_NAME,
            component=ComponentKind.ROMFS,
            role=ArtifactRole.DEVICE_READ,
            exactness=Exactness.EXACT,
            provider=self.name,
            address=0,
            length=length,
            exclusions=EXCLUSIONS,
        )
        return BackupOutput(notes=(f"ROMFS: {length} byte image from a {partition} byte partition, verified by SHA-256 on the board.",))

    # -- restore -----------------------------------------------------------

    def describe_restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> Sequence[str]:
        artifact = _image_artifact(artifacts)
        assert artifact.length is not None
        image = bundle.artifact_path(artifact).read_bytes()
        self._check_image(image, artifact.length)
        self._check_fits(mcu, artifact.length)
        return [
            f"erase and rewrite the ROMFS partition with the {artifact.length} byte image from the backup",
            "this replaces everything in the ROMFS (/rom); the board is reset afterwards and the image verified by SHA-256",
        ]

    def restore(self, mcu: Any, bundle: Bundle, artifacts: Sequence[Artifact]) -> None:
        artifact = _image_artifact(artifacts)
        assert artifact.length is not None
        length = artifact.length
        image = bundle.artifact_path(artifact).read_bytes()
        self._check_image(image, length)
        with self._open(mcu.serialport, soft_reset=True) as repl:
            device = RomfsDevice(repl)
            self._check_fits_device(device, length)
            chunk = device.prepare(length)
            for offset in range(0, length, chunk):
                part = image[offset : offset + chunk]
                device.write(offset, part + bytes(chunk - len(part)))
            device.finish()
        self._restart(mcu)
        with self._open(mcu.serialport, soft_reset=False) as repl:
            if RomfsDevice(repl).sha256(length) != artifact.sha256:
                raise MPFlashError("The ROMFS does not match the backup after restoring it")

    @staticmethod
    def _check_image(image: bytes, length: int) -> None:
        if len(image) != length or not image.startswith(ROMFS_HEADER):
            raise MPFlashError("The ROMFS image in the bundle is not a valid ROMFS image")

    def _check_fits(self, mcu: Any, length: int) -> None:
        with self._open(mcu.serialport, soft_reset=False) as repl:
            self._check_fits_device(RomfsDevice(repl), length)

    @staticmethod
    def _check_fits_device(device: RomfsDevice, length: int) -> None:
        partitions, size, _, _ = device.probe()
        if partitions <= 0:
            raise MPFlashError("This board has no ROMFS partition to restore to")
        if length > size:
            raise MPFlashError(f"The ROMFS image is {length} bytes but this board's ROMFS partition is only {size} bytes")

    @staticmethod
    def _restart(mcu: Any) -> None:
        """Reset so the new image is mounted at /rom, and make sure the board comes back."""
        mcu.run_command("reset", timeout=10, log_errors=False)
        mcu.connected = False
        if not mcu.wait_for_restart(timeout=20):
            raise MPFlashError(f"{mcu.serialport} did not reconnect after the ROMFS restore, so it could not be verified")


register(RomfsProvider())
