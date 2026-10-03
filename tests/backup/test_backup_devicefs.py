"""The mpremote-backed ``DeviceFs`` adapter, tested against a fake transport."""

import hashlib
from types import SimpleNamespace

import pytest
from mpremote.transport import TransportError

from mpflash.backup import devicefs
from mpflash.backup.devicefs import DirEntry, Mount, MpremoteDeviceFs, _chunk_size, open_device_fs
from mpflash.errors import MPFlashError


class FakeTransport:
    """Records calls and answers ``eval``/``exec_raw`` from canned tables."""

    def __init__(self, evals=None, exec_errors=None):
        self.evals = evals or {}
        self.exec_errors = exec_errors or {}
        self.execs = []
        self.files = {}
        self.calls = []

    def eval(self, expression):
        for needle, result in self.evals.items():
            if needle in expression:
                if isinstance(result, Exception):
                    raise result
                return result
        raise TransportError(f"unexpected eval {expression}")

    def exec_raw(self, command, timeout=10):
        self.execs.append((command, timeout))
        for needle, error in self.exec_errors.items():
            if needle in command:
                return b"", error
        return b"", b""

    def fs_listdir(self, path):
        return [SimpleNamespace(name="a.py", st_mode=0x8000), SimpleNamespace(name="lib", st_mode=0x4000)]

    def fs_readfile(self, path, chunk_size=256):
        self.calls.append(("read", path, chunk_size))
        return bytearray(self.files[path])

    def fs_writefile(self, path, data, chunk_size=256):
        self.calls.append(("write", path, chunk_size))
        self.files[path] = data

    def fs_mkdir(self, path):
        self.calls.append(("mkdir", path))

    def fs_rmfile(self, path):
        self.calls.append(("rmfile", path))

    def fs_rmdir(self, path):
        self.calls.append(("rmdir", path))


def adapter(transport):
    return MpremoteDeviceFs(transport, TransportError)


MEM = "mem_free"


@pytest.mark.parametrize(
    "free, expected",
    [(0, 128), (5_000, 128), (34_720, 512), (163_280, 2048), (10_000_000, 4096)],
)
def test_chunk_size_scales_with_free_memory(free, expected):
    assert _chunk_size(free) == expected


def test_transfers_use_a_chunk_matching_the_boards_memory():
    transport = FakeTransport(evals={MEM: 34_720})
    transport.files["/a"] = b"data"
    fs = adapter(transport)

    fs.read_file("/a")
    fs.write_file("/b", b"x")

    assert transport.calls == [("read", "/a", 512), ("write", "/b", 512)]


def test_unknown_memory_keeps_the_smallest_chunk():
    transport = FakeTransport(evals={MEM: TransportError("no gc")})

    adapter(transport).write_file("/b", b"x")

    assert transport.calls == [("write", "/b", 128)]


def test_mounts_strip_the_object_repr():
    transport = FakeTransport(evals={MEM: 0, "mount()": [("/rom", "<VfsRom>"), ("/", "<VfsLfs2>")]})

    assert adapter(transport).mounts() == [Mount("/rom", "VfsRom"), Mount("/", "VfsLfs2")]


@pytest.mark.parametrize("answer", [TransportError("no mount()"), []])
def test_mounts_fall_back_to_the_root_when_the_firmware_cannot_list_them(answer):
    transport = FakeTransport(evals={MEM: 0, "mount()": answer})

    assert adapter(transport).mounts() == [Mount("/", "")]


def test_listdir_reports_directories_from_the_mode_bits():
    assert adapter(FakeTransport(evals={MEM: 0})).listdir("/") == [DirEntry("a.py", False), DirEntry("lib", True)]


def test_mutations_are_forwarded():
    transport = FakeTransport(evals={MEM: 0})
    fs = adapter(transport)

    fs.mkdir("/d")
    fs.remove_file("/f")
    fs.remove_dir("/d")

    assert transport.calls == [("mkdir", "/d"), ("rmfile", "/f"), ("rmdir", "/d")]


def test_transport_errors_become_mpflash_errors_with_the_last_line():
    class Failing(FakeTransport):
        def fs_mkdir(self, path):
            raise TransportError("Traceback (most recent call last):\n  File x\nOSError: [Errno 28] ENOSPC")

    with pytest.raises(MPFlashError, match=r"OSError: \[Errno 28\] ENOSPC$"):
        adapter(Failing(evals={MEM: 0})).mkdir("/d")


def test_os_errors_become_mpflash_errors():
    class Failing(FakeTransport):
        def fs_rmfile(self, path):
            raise FileNotFoundError("gone")

    with pytest.raises(MPFlashError, match="Device filesystem error: gone"):
        adapter(Failing(evals={MEM: 0})).remove_file("/f")


def test_sha256_hashes_on_the_device_with_a_timeout_that_grows_with_the_file():
    digest = hashlib.sha256(b"abc").digest()
    transport = FakeTransport(evals={MEM: 0, "h.digest()": digest})

    assert adapter(transport).sha256("/big.bin", size_hint=1_000_000) == digest.hex()

    hashing = [timeout for command, timeout in transport.execs if "readinto" in command]
    assert hashing == [10 + 1_000_000 / 20_000]


def test_sha256_falls_back_to_host_hashing_without_hashlib():
    transport = FakeTransport(evals={MEM: 0}, exec_errors={"import hashlib": b"ImportError: no module named 'hashlib'"})
    transport.files["/a"] = b"abc"

    assert adapter(transport).sha256("/a") == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize(
    "answer, expected",
    [((4096, 4096, 512, 492, 492), 4096 * 512), ((0, 0, 0, 0, 0), None), (TransportError("no statvfs"), None)],
)
def test_capacity_is_total_filesystem_bytes_when_known(answer, expected):
    assert adapter(FakeTransport(evals={MEM: 0, "statvfs": answer})).capacity("/") == expected


# ---------------------------------------------------------------------------
# connection handling
# ---------------------------------------------------------------------------


class FakeSerialTransport(FakeTransport):
    instances = []

    def __init__(self, device, **kwargs):
        super().__init__(evals={MEM: 0})
        self.device = device
        self.raw_repl = []
        self.closed = False
        self.open_error = None
        self.enter_error = None
        FakeSerialTransport.instances.append(self)

    def enter_raw_repl(self, soft_reset=True):
        if self.enter_error:
            raise self.enter_error
        self.raw_repl.append(("enter", soft_reset))

    def exit_raw_repl(self):
        self.raw_repl.append(("exit",))

    def close(self):
        self.closed = True


@pytest.fixture
def serial(monkeypatch):
    FakeSerialTransport.instances = []
    monkeypatch.setattr("mpremote.transport_serial.SerialTransport", FakeSerialTransport)
    return FakeSerialTransport


@pytest.mark.parametrize("soft_reset", [True, False])
def test_connection_enters_and_leaves_the_raw_repl_and_closes_the_port(serial, soft_reset):
    with open_device_fs("COM9", soft_reset=soft_reset) as fs:
        assert isinstance(fs, MpremoteDeviceFs)

    (transport,) = serial.instances
    assert transport.device == "COM9"
    assert transport.raw_repl == [("enter", soft_reset), ("exit",)]
    assert transport.closed


def test_port_is_closed_when_the_work_inside_fails(serial):
    with pytest.raises(RuntimeError):
        with open_device_fs("COM9"):
            raise RuntimeError("boom")

    assert serial.instances[0].closed


def test_unopenable_port_is_reported(monkeypatch):
    def refuse(device, **kwargs):
        raise TransportError("failed to access COM9")

    monkeypatch.setattr("mpremote.transport_serial.SerialTransport", refuse)

    with pytest.raises(MPFlashError, match="Could not open COM9: failed to access COM9"):
        with open_device_fs("COM9"):
            pass


def test_unresponsive_board_is_reported_and_the_port_still_closed(serial, monkeypatch):
    original = serial.__init__

    def init(self, device, **kwargs):
        original(self, device, **kwargs)
        self.enter_error = TransportError("could not enter raw repl")

    monkeypatch.setattr(serial, "__init__", init)

    with pytest.raises(MPFlashError, match="Could not enter the MicroPython raw REPL on COM9"):
        with open_device_fs("COM9"):
            pass

    assert serial.instances[0].closed


def test_summary_helper_describes_mounts():
    assert devicefs.mount_table_summary([Mount("/", "VfsLfs2"), Mount("/x", "")]) == ("/ (VfsLfs2)", "/x (unknown filesystem)")
