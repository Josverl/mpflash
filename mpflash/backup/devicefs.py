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
import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Generator, List, Optional, Protocol, Tuple, Type

from mpflash.errors import MPFlashError

_STAT_DIR_BIT = 0x4000
_HASH_BYTES_PER_SECOND = 20_000
_MIN_CHUNK = 128
_MAX_CHUNK = 4096


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


def _chunk_size(free_memory: int) -> int:
    """Pick a transfer chunk that fits the board's RAM, as a power of two."""
    chunk = _MIN_CHUNK
    while chunk * 2 <= min(max(free_memory // 64, _MIN_CHUNK), _MAX_CHUNK):
        chunk *= 2
    return chunk


class MpremoteDeviceFs:
    """:class:`DeviceFs` implemented on an mpremote ``SerialTransport`` in raw REPL."""

    def __init__(self, transport: Any, error_type: Type[Exception]):
        self._t = transport
        self._error = error_type
        self._chunk = _MIN_CHUNK
        try:
            self._chunk = _chunk_size(int(self._eval("(__import__('gc').collect(), __import__('gc').mem_free())[1]")))
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
        return bytes(self._run(lambda: self._t.fs_readfile(path, chunk_size=self._chunk)))

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
        timeout = 10 + size_hint / _HASH_BYTES_PER_SECOND
        try:
            self._exec("import hashlib\n_h = hashlib.sha256()", 10)
        except MPFlashError:
            return hashlib.sha256(self.read_file(path)).hexdigest()
        buffer = min(self._chunk, 512)
        self._exec(
            f"_b = memoryview(bytearray({buffer}))\n"
            f"with open({path!r}, 'rb') as _f:\n"
            " while True:\n"
            "  _n = _f.readinto(_b)\n"
            "  if not _n:\n"
            "   break\n"
            "  _h.update(_b[:_n])\n",
            timeout,
        )
        digest = self._eval("_h.digest()")
        return bytes(digest).hex()

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
