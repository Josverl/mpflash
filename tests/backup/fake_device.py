"""An in-memory board for testing the VFS provider without hardware."""

from contextlib import contextmanager
from hashlib import sha256
from typing import Any, Dict, Generator, Iterable, List, Optional, Set, Tuple
from unittest.mock import Mock

from mpflash.backup.devicefs import DirEntry, Mount
from mpflash.errors import MPFlashError


class FakeDeviceFs:
    """Implements ``DeviceFs`` over dictionaries and records every mutation."""

    def __init__(
        self,
        files: Optional[Dict[str, bytes]] = None,
        dirs: Iterable[str] = (),
        mounts: Optional[List[Mount]] = None,
        capacity: Optional[int] = None,
    ):
        self.files: Dict[str, bytes] = dict(files or {})
        self.dirs: Set[str] = set(dirs)
        self.mount_table = mounts if mounts is not None else [Mount("/", "VfsLfs2")]
        self.total = capacity
        self.ops: List[Tuple[str, str]] = []
        self.corrupt_reads: Set[str] = set()
        self.corrupt_writes: Set[str] = set()
        self.fail_writes: Set[str] = set()
        self.soft_resets: List[bool] = []
        self.open_depth = 0

    # -- DeviceFs ----------------------------------------------------------

    def mounts(self) -> List[Mount]:
        return list(self.mount_table)

    def listdir(self, path: str) -> List[DirEntry]:
        prefix = path.rstrip("/") + "/"
        names: Dict[str, bool] = {}
        for candidate in self.dirs | {m.path for m in self.mount_table}:
            self._child(prefix, candidate, True, names)
        for candidate in self.files:
            self._child(prefix, candidate, False, names)
        return [DirEntry(name, is_dir) for name, is_dir in names.items()]

    @staticmethod
    def _child(prefix: str, candidate: str, is_dir: bool, names: Dict[str, bool]) -> None:
        if candidate.startswith(prefix) and candidate != prefix.rstrip("/"):
            head, _, rest = candidate[len(prefix) :].partition("/")
            if head:
                names[head] = names.get(head, False) or bool(rest) or is_dir

    def read_file(self, path: str) -> bytes:
        data = self.files[path]
        return data + b"!" if path in self.corrupt_reads else data

    def write_file(self, path: str, data: bytes) -> None:
        if path in self.fail_writes:
            raise MPFlashError("No space left on device")
        self.ops.append(("write", path))
        self.files[path] = data + b"!" if path in self.corrupt_writes else data

    def mkdir(self, path: str) -> None:
        self.ops.append(("mkdir", path))
        self.dirs.add(path)

    def remove_file(self, path: str) -> None:
        self.ops.append(("rm", path))
        del self.files[path]

    def remove_dir(self, path: str) -> None:
        self.ops.append(("rmdir", path))
        self.dirs.discard(path)

    def sha256(self, path: str, size_hint: int = 0) -> str:
        return sha256(self.files[path]).hexdigest()

    def capacity(self, path: str) -> Optional[int]:
        return self.total

    # -- helpers -----------------------------------------------------------

    def mutations(self) -> List[Tuple[str, str]]:
        return list(self.ops)

    def opener(self):
        fake = self

        @contextmanager
        def open_fs(serialport: str, *, soft_reset: bool = True) -> Generator["FakeDeviceFs", None, None]:
            fake.soft_resets.append(soft_reset)
            fake.open_depth += 1
            try:
                yield fake
            finally:
                fake.open_depth -= 1

        return open_fs


def fake_mcu(**overrides: Any) -> Any:
    """A probed MicroPython board whose reset command does nothing."""
    from types import SimpleNamespace

    mcu = SimpleNamespace(
        serialport="COM9",
        connected=True,
        family="micropython",
        port="esp32",
        board_id="ESP32_GENERIC",
        board="ESP32_GENERIC",
        cpu="ESP32",
        version="1.29.0",
        description="",
        sys_platform="esp32",
        vid=0,
        pid=0,
        serial_number="AAA",
        toml={},
        run_command=Mock(return_value=(0, [])),
    )
    for key, value in overrides.items():
        setattr(mcu, key, value)

    # Like the real MPRemoteBoard.wait_for_restart: a successful probe marks the board connected again.
    restart = Mock(return_value=True)

    def wait_for_restart(*args: Any, **kwargs: Any) -> bool:
        ok = restart.return_value
        if ok:
            mcu.connected = True
        return ok

    restart.side_effect = wait_for_restart
    mcu.wait_for_restart = restart
    return mcu
