"""Filesystem access to a MicroPython board over one raw-REPL connection.

The backup providers only depend on the small :class:`DeviceFs` protocol, so the
planning and archive logic is testable with an in-memory device. The concrete
implementation drives mpremote's ``SerialTransport`` in-process: one connection
serves a whole backup instead of spawning ``mpremote`` once per file, and mount
points are handled explicitly (``mpremote cp -r`` fails on ports whose root
contains a read-only ROM mount or is virtual).
"""

from __future__ import annotations

import ast
import binascii
import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Generator, List, Optional, Protocol, Tuple, Type

from mpflash.errors import MPFlashError
from mpflash.logger import log

_STAT_DIR_BIT = 0x4000
_HASH_BYTES_PER_SECOND = 20_000
_MIN_CHUNK = 128
_MAX_CHUNK = 4096
READ_ATTEMPTS = 3

# Runs on the board. Replies are written straight to stdout as base64 followed by a CRC32, which is
# several times faster than print(repr(bytes)) and lets the host detect a reply the USB link damaged.
_FILE_CODE = """
import binascii, sys
try:
    _c = binascii.crc32
except AttributeError:
    _c = None
def _rf(p, o, n):
    with open(p, "rb") as f:
        f.seek(o)
        d = f.read(n)
    sys.stdout.write(binascii.b2a_base64(d, newline=False))
    sys.stdout.write(".%08x" % (_c(d) & 0xFFFFFFFF) if _c else ".-")
"""


_HASH_CODE = """
import hashlib, binascii
def _sh(p, n):
    h = hashlib.sha256()
    b = memoryview(bytearray(n))
    with open(p, "rb") as f:
        while True:
            k = f.readinto(b)
            if not k:
                break
            h.update(b[:k])
    print(binascii.hexlify(h.digest()).decode())
"""


def decode_chunk(reply: bytes, length: Optional[int], *, allow_unchecked: bool = False) -> Tuple[Optional[bytes], str]:
    """Return ``(data, "")`` for a valid ``base64.crc32hex`` reply, otherwise ``(None, why)``.

    ``length`` is the exact number of bytes expected, or ``None`` when any length is acceptable.
    A board without ``binascii.crc32`` (ESP8266) sends ``-`` instead of a checksum; that is accepted only
    with ``allow_unchecked``, for callers that verify the whole result another way.
    """
    payload, separator, crc = reply.strip().partition(b".")
    if not separator:
        return None, "the reply was cut short before its checksum"
    unchecked = allow_unchecked and crc == b"-"
    try:
        data = binascii.a2b_base64(payload)
        expected = 0 if unchecked else int(crc, 16)
    except ValueError:  # binascii.Error is a ValueError
        return None, "the reply is not valid base64 and a checksum"
    if length is not None and len(data) != length:
        return None, f"it holds {len(data)} bytes, expected {length}"
    if not unchecked and binascii.crc32(data) != expected:
        return None, "the checksum does not match"
    return data, ""


@dataclass(frozen=True)
class DirEntry:
    """One entry returned by :meth:`DeviceFs.listdir`."""

    name: str
    is_dir: bool


@dataclass(frozen=True)
class Mount:
    """One entry of the device's mount table."""

    path: str
    fstype: str


class DeviceFs(Protocol):
    """The operations a backup provider needs from a connected board."""

    def mounts(self) -> List[Mount]: ...

    def listdir(self, path: str) -> List[DirEntry]: ...

    def read_file(self, path: str) -> bytes: ...

    def write_file(self, path: str, data: bytes) -> None: ...

    def mkdir(self, path: str) -> None: ...

    def remove_file(self, path: str) -> None: ...

    def remove_dir(self, path: str) -> None: ...

    def sha256(self, path: str, size_hint: int = 0) -> str: ...

    def capacity(self, path: str) -> Optional[int]:
        """Return the total size in bytes of the filesystem at ``path`` when known."""
        ...


def _chunk_size(free_memory: int, share: int = 64) -> int:
    """Pick a transfer chunk of about ``1/share`` of the board's free RAM, as a power of two."""
    chunk = _MIN_CHUNK
    while chunk * 2 <= min(max(free_memory // share, _MIN_CHUNK), _MAX_CHUNK):
        chunk *= 2
    return chunk


class MpremoteDeviceFs:
    """:class:`DeviceFs` implemented on an mpremote ``SerialTransport`` in raw REPL."""

    def __init__(self, transport: Any, error_type: Type[Exception]):
        self._t = transport
        self._error = error_type
        self._chunk = _MIN_CHUNK
        # Reads need about 2.4x their chunk in RAM (data, then its base64), so they can use a larger one
        # than writes; on an ESP8266 4x larger chunks read a file 1.7x faster, which is the UART's limit.
        self._read_chunk = _MIN_CHUNK
        self._fast_reads: Optional[bool] = None
        self._fast_hash: Optional[bool] = None
        try:
            free = int(self._eval("(__import__('gc').collect(), __import__('gc').mem_free())[1]"))
            self._chunk = _chunk_size(free)
            self._read_chunk = _chunk_size(free, share=16)
        except (MPFlashError, ValueError, TypeError):
            pass

    # -- low level -------------------------------------------------------

    def _run(self, action):
        """Run a transport call, converting every transport failure into ``MPFlashError``."""
        try:
            return action()
        except MPFlashError:
            raise
        except self._error as error:  # TransportError and TransportExecError
            raise MPFlashError(_last_line(str(error))) from error
        except OSError as error:
            raise MPFlashError(f"Device filesystem error: {error}") from error

    def _eval(self, expression: str):
        return self._run(lambda: self._t.eval(expression))

    def _exec(self, command: str, timeout: float = 10):
        def action():
            out, err = self._t.exec_raw(command, timeout=timeout)
            if err:
                raise self._error(err.decode(errors="replace"))
            return out

        return self._run(action)

    # -- raw REPL --------------------------------------------------------

    def exec(self, command: str, timeout: float = 10) -> bytes:
        """Run ``command`` on the board and return its stdout; raises ``MPFlashError`` on any device error."""
        return self._exec(command, timeout)

    def eval(self, expression: str, timeout: float = 10) -> Any:
        """Evaluate ``expression`` on the board and return its value (a Python literal such as bytes, int or str)."""
        output = self._exec(f"print(repr({expression}))", timeout)
        try:
            return ast.literal_eval(output.decode().strip())
        except (ValueError, SyntaxError, UnicodeDecodeError) as error:
            raise MPFlashError(f"Unexpected reply from the board for {expression!r}: {output[:80]!r}") from error

    # -- DeviceFs --------------------------------------------------------

    def mounts(self) -> List[Mount]:
        try:
            self._exec("try:\n import vfs as _v\nexcept ImportError:\n import os as _v")
            raw = self._eval("[(p, str(f)) for f, p in _v.mount()]")
        except MPFlashError:
            return [Mount("/", "")]
        return [Mount(str(path), str(fstype).strip("<>")) for path, fstype in raw] or [Mount("/", "")]

    def listdir(self, path: str) -> List[DirEntry]:
        entries = self._run(lambda: self._t.fs_listdir(path))
        return [DirEntry(entry.name, bool(entry.st_mode & _STAT_DIR_BIT)) for entry in entries]

    def read_file(self, path: str) -> bytes:
        if self._fast_reads is None:
            try:
                self._exec(_FILE_CODE)
                self._fast_reads = True
            except MPFlashError as error:  # firmware without binascii.crc32 or b2a_base64(newline=)
                log.debug(f"Using mpremote's file reads: {error}")
                self._fast_reads = False
        if not self._fast_reads:
            return bytes(self._run(lambda: self._t.fs_readfile(path, chunk_size=self._chunk)))
        return self._read_in_chunks(path)

    def _read_in_chunks(self, path: str) -> bytes:
        """Read a file one request per chunk; a file of up to one chunk takes a single round trip."""
        data = bytearray()
        while True:
            part = self._request_chunk(path, len(data))
            data += part
            if len(part) < self._read_chunk:
                return bytes(data)

    def _request_chunk(self, path: str, offset: int) -> bytes:
        problem = ""
        for attempt in range(1, READ_ATTEMPTS + 1):
            reply = self._exec(f"_rf({path!r}, {offset}, {self._read_chunk})", timeout=30)
            part, problem = decode_chunk(reply, None, allow_unchecked=True)
            if part is not None and len(part) <= self._read_chunk:
                return part
            log.warning(f"Read of {path} at {offset} failed ({problem or 'too long'}); attempt {attempt} of {READ_ATTEMPTS}")
        raise MPFlashError(f"The board returned damaged data for {path} at offset {offset} {READ_ATTEMPTS} times in a row: {problem}")

    def write_file(self, path: str, data: bytes) -> None:
        self._run(lambda: self._t.fs_writefile(path, data, chunk_size=self._chunk))

    def mkdir(self, path: str) -> None:
        self._run(lambda: self._t.fs_mkdir(path))

    def remove_file(self, path: str) -> None:
        self._run(lambda: self._t.fs_rmfile(path))

    def remove_dir(self, path: str) -> None:
        self._run(lambda: self._t.fs_rmdir(path))

    def sha256(self, path: str, size_hint: int = 0) -> str:
        """Hash on the device, with a timeout that grows with the file size.

        Falls back to hashing the transferred bytes when the firmware has no ``hashlib``.
        """
        if self._fast_hash is None:
            try:
                self._exec(_HASH_CODE)
                self._fast_hash = True
            except MPFlashError as error:
                log.debug(f"Hashing files on the host: {error}")
                self._fast_hash = False
        if self._fast_hash:
            try:
                out = self._exec(f"_sh({path!r}, {min(self._chunk, 512)})", 10 + size_hint / _HASH_BYTES_PER_SECOND)
                digest = out.decode().strip()
                if len(digest) == 64:
                    return digest
            except MPFlashError:
                pass
        return hashlib.sha256(self.read_file(path)).hexdigest()

    def capacity(self, path: str) -> Optional[int]:
        try:
            stat = self._eval(f"tuple(__import__('os').statvfs({path!r}))")
        except MPFlashError:
            return None
        total = int(stat[1]) * int(stat[2])
        return total or None


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "device error"


_EOT = 4  # the raw REPL ends stdout and then stderr with this byte


def follow_in_bulk(serial: Any, timeout: float, error: Type[Exception], leftover: bytearray) -> Tuple[bytes, bytes]:
    """Read the stdout and stderr of a raw-REPL command, each ended by ``0x04``, in bulk.

    mpremote's own ``follow()`` reads one byte per loop iteration, which caps throughput near
    25 KB/s however fast the link is, and a reader that slow also makes a board's USB transmit
    buffer time out and drop data. Reading whatever is waiting is limited by the link instead.

    Bytes read beyond the second ``0x04`` (the raw REPL prompt ``>``) are put in ``leftover`` so the
    next command can still see them.
    """
    parts: List[bytes] = []
    pending = bytearray()
    last = time.monotonic()
    while True:
        waiting = serial.in_waiting
        if not waiting:
            if time.monotonic() - last > timeout:
                raise error(f"timeout waiting for the {'first' if not parts else 'second'} end of output marker")
            time.sleep(0.0005)
            continue
        chunk = serial.read(waiting)
        last = time.monotonic()
        start = 0
        while True:
            end = chunk.find(_EOT, start)
            if end < 0:
                pending.extend(chunk[start:])
                break
            pending.extend(chunk[start:end])
            parts.append(bytes(pending))
            pending.clear()
            start = end + 1
            if len(parts) == 2:
                leftover.extend(chunk[start:])
                return parts[0], parts[1]


@lru_cache(maxsize=1)
def _bulk_transport_class() -> Any:
    """Return mpremote's ``SerialTransport`` with bulk reads (imported lazily; mpremote is slow to import)."""
    from mpremote.transport import TransportError
    from mpremote.transport_serial import SerialTransport

    class BulkSerialTransport(SerialTransport):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._leftover = bytearray()

        def read_until(self, min_num_bytes: int, ending: bytes, *args: Any, **kwargs: Any) -> bytes:
            # Bytes that follow_in_bulk read past the previous command's output (normally the b">" prompt).
            head = bytes(self._leftover)
            self._leftover.clear()
            if head.endswith(ending):
                return head
            return head + super().read_until(min_num_bytes, ending, *args, **kwargs)

        def follow(self, timeout: float, data_consumer: Any = None) -> Tuple[bytes, bytes]:
            if data_consumer is not None:  # streaming consumers keep mpremote's own behaviour
                return super().follow(timeout, data_consumer)
            return follow_in_bulk(self.serial, timeout, TransportError, self._leftover)

    return BulkSerialTransport


@contextmanager
def open_device_fs(serialport: str, *, soft_reset: bool = True) -> Generator[MpremoteDeviceFs, None, None]:
    """Open one raw-REPL connection to ``serialport`` and yield its filesystem (and raw REPL).

    ``soft_reset=True`` stops the running application and closes its open files, which gives a
    consistent view for backup and restore. Read-only inspection can use ``soft_reset=False`` to
    leave the interpreter state untouched.
    """
    from mpremote.transport import TransportError

    try:
        transport = _bulk_transport_class()(serialport)
    except TransportError as error:
        raise MPFlashError(f"Could not open {serialport}: {error}") from error
    try:
        try:
            transport.enter_raw_repl(soft_reset=soft_reset)
        except TransportError as error:
            raise MPFlashError(f"Could not enter the MicroPython raw REPL on {serialport}: {error}") from error
        try:
            yield MpremoteDeviceFs(transport, TransportError)
        finally:
            try:
                transport.exit_raw_repl()
            except (TransportError, OSError):
                pass
    finally:
        try:
            transport.close()
        except OSError:
            pass


def mount_table_summary(mounts: List[Mount]) -> Tuple[str, ...]:
    """Describe a mount table for notes and logs."""
    return tuple(f"{mount.path} ({mount.fstype or 'unknown filesystem'})" for mount in mounts)
