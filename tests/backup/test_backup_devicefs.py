"""The mpremote-backed ``DeviceFs`` adapter, tested against a fake transport."""

import ast
import binascii
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
        self.exec_outputs = {}
        self.damaged_replies = 0
        self.no_crc32 = False
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
        for needle, output in self.exec_outputs.items():
            if needle in command:
                return output, b""
        if command.startswith("_rf("):
            return self.serve_chunk(command), b""
        return b"", b""

    def serve_chunk(self, command):
        """Answer ``_rf(path, offset, size)`` as the board does: base64, a dot and the CRC32."""
        path, offset, size = ast.literal_eval("(" + command[len("_rf(") : -1] + ")")
        data = self.files[path][offset : offset + size]
        reply = binascii.b2a_base64(data, newline=False) + (b".-" if self.no_crc32 else b".%08x" % binascii.crc32(data))
        if self.damaged_replies > 0:
            self.damaged_replies -= 1
            reply = reply[:-4]
        return reply

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

    assert fs.read_file("/a") == b"data"
    fs.write_file("/b", b"x")

    assert [c for c, _ in transport.execs if c.startswith("_rf(")] == ["_rf('/a', 0, 2048)"]
    assert transport.calls == [("write", "/b", 512)]


def test_a_small_file_is_read_in_a_single_round_trip():
    transport = FakeTransport(evals={MEM: 34_720})
    transport.files["/a"] = b"x" * 100

    assert adapter(transport).read_file("/a") == b"x" * 100

    assert len(transport.execs) == 2  # defining the helper once, then one request
    assert transport.calls == []  # mpremote's own byte-at-a-time reader is not used


@pytest.mark.parametrize("size", [0, 1, 2047, 2048, 2049, 4096, 5000])
def test_files_are_reassembled_from_chunks_whatever_their_size(size):
    transport = FakeTransport(evals={MEM: 34_720})
    data = bytes(i % 251 for i in range(size))
    transport.files["/f"] = data

    assert adapter(transport).read_file("/f") == data


def test_the_read_helper_is_installed_once_per_connection():
    transport = FakeTransport(evals={MEM: 34_720})
    transport.files["/a"] = b"1"
    transport.files["/b"] = b"2"
    fs = adapter(transport)

    fs.read_file("/a")
    fs.read_file("/b")

    assert sum("def _rf" in command for command, _ in transport.execs) == 1


def test_a_damaged_reply_is_requested_again():
    transport = FakeTransport(evals={MEM: 34_720})
    transport.files["/a"] = b"important"
    transport.damaged_replies = 2

    assert adapter(transport).read_file("/a") == b"important"


def test_a_file_that_keeps_arriving_damaged_is_an_error():
    transport = FakeTransport(evals={MEM: 34_720})
    transport.files["/a"] = b"important"
    transport.damaged_replies = 99

    with pytest.raises(MPFlashError, match=r"damaged data for /a at offset 0 3 times in a row"):
        adapter(transport).read_file("/a")


def test_firmware_without_the_read_helper_uses_mpremotes_reader():
    transport = FakeTransport(evals={MEM: 34_720}, exec_errors={"def _rf": b"AttributeError: no crc32"})
    transport.files["/a"] = b"data"

    assert adapter(transport).read_file("/a") == b"data"

    assert transport.calls == [("read", "/a", 512)]


def test_a_board_without_crc32_still_reads_files_and_leaves_checking_to_the_caller():
    transport = FakeTransport(evals={MEM: 34_720})
    transport.no_crc32 = True  # ESP8266: binascii has no crc32
    data = bytes(range(256)) * 5
    transport.files["/a"] = data

    assert adapter(transport).read_file("/a") == data


def test_unchecked_replies_are_only_accepted_when_the_caller_allows_them():
    reply = binascii.b2a_base64(b"hello", newline=False) + b".-"

    assert devicefs.decode_chunk(reply, None, allow_unchecked=True) == (b"hello", "")
    assert devicefs.decode_chunk(reply, None)[0] is None


def test_decode_chunk_accepts_any_length_when_none_is_expected():
    data = b"hello"
    reply = binascii.b2a_base64(data, newline=False) + b".%08x" % binascii.crc32(data)

    assert devicefs.decode_chunk(reply, None) == (data, "")
    assert devicefs.decode_chunk(reply, 5) == (data, "")
    assert devicefs.decode_chunk(reply, 6)[0] is None


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
    digest = hashlib.sha256(b"abc").hexdigest()
    transport = FakeTransport(evals={MEM: 0})
    transport.exec_outputs["_sh("] = digest.encode() + b"\r\n"

    assert adapter(transport).sha256("/big.bin", size_hint=1_000_000) == digest

    assert [timeout for command, timeout in transport.execs if command.startswith("_sh(")] == [10 + 1_000_000 / 20_000]


def test_the_hash_helper_is_installed_once_so_each_file_costs_one_round_trip():
    digest = hashlib.sha256(b"abc").hexdigest()
    transport = FakeTransport(evals={MEM: 0})
    transport.exec_outputs["_sh("] = digest.encode()
    fs = adapter(transport)

    fs.sha256("/a")
    fs.sha256("/b")
    fs.sha256("/c")

    assert sum("def _sh" in command for command, _ in transport.execs) == 1
    assert sum(command.startswith("_sh(") for command, _ in transport.execs) == 3


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
    monkeypatch.setattr(devicefs, "_bulk_transport_class", lambda: FakeSerialTransport)
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

    monkeypatch.setattr(devicefs, "_bulk_transport_class", lambda: refuse)

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


# ---------------------------------------------------------------------------
# bulk reading of command output
# ---------------------------------------------------------------------------


class FakeSerial:
    """A serial port that delivers prepared chunks and counts how it is read."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.pending = bytearray()
        self.read_sizes = []

    @property
    def in_waiting(self):
        if not self.pending and self.chunks:
            self.pending += self.chunks.pop(0)
        return len(self.pending)

    def read(self, count):
        data = bytes(self.pending[:count])
        del self.pending[:count]
        self.read_sizes.append(count)
        return data


def follow(chunks, timeout=1.0):
    leftover = bytearray()
    out, err = devicefs.follow_in_bulk(FakeSerial(chunks), timeout, TransportError, leftover)
    return out, err, bytes(leftover)


@pytest.mark.parametrize(
    "chunks, expected",
    [
        ([b"hello\x04\x04>"], (b"hello", b"", b">")),
        ([b"hello\x04", b"\x04"], (b"hello", b"", b"")),
        ([b"hel", b"lo\x04err", b"or\x04>"], (b"hello", b"error", b">")),
        ([b"\x04\x04"], (b"", b"", b"")),
        ([b"a", b"b", b"\x04", b"c", b"\x04", b">"], (b"ab", b"c", b"")),
        ([b"out\x04Traceback...\x04>"], (b"out", b"Traceback...", b">")),
    ],
)
def test_output_is_split_at_the_two_end_markers_wherever_the_chunks_fall(chunks, expected):
    assert follow(chunks) == expected


def test_binary_safe_apart_from_the_end_marker():
    payload = bytes(value for value in range(256) if value != 4) * 4

    out, err, _ = follow([payload[:100], payload[100:700], payload[700:] + b"\x04\x04"])

    assert out == payload and err == b""


def test_large_output_is_read_in_bulk_not_byte_by_byte():
    data = b"x" * (1024 * 1024)
    chunks = [data[i : i + 4096] for i in range(0, len(data), 4096)]
    chunks[-1] += b"\x04\x04"
    serial = FakeSerial(chunks)

    out, _ = devicefs.follow_in_bulk(serial, 1.0, TransportError, bytearray())

    assert out == data
    assert len(serial.read_sizes) == len(chunks)  # one read per chunk that arrived
    assert min(serial.read_sizes) > 1


@pytest.mark.parametrize("chunks, which", [([], "first"), ([b"partial output"], "first"), ([b"out\x04", b"err"], "second")])
def test_a_silent_board_times_out_and_says_which_marker_was_missing(chunks, which):
    with pytest.raises(TransportError, match=f"timeout waiting for the {which} end of output marker"):
        follow(chunks, timeout=0.05)


# ---------------------------------------------------------------------------
# the transport subclass
# ---------------------------------------------------------------------------


@pytest.fixture
def transport():
    from mpremote.transport_serial import SerialTransport

    cls = devicefs._bulk_transport_class()
    instance = cls.__new__(cls)  # no port is opened
    instance._leftover = bytearray()
    return instance, SerialTransport


def test_the_transport_is_mpremotes_serial_transport_with_bulk_reads(transport):
    instance, base = transport

    assert isinstance(instance, base) and devicefs._bulk_transport_class() is type(instance)


def test_a_prompt_read_past_the_output_is_handed_to_the_next_command(transport):
    instance, _ = transport
    instance.serial = FakeSerial([b"out\x04\x04>"])

    assert instance.follow(1.0) == (b"out", b"")
    assert instance.read_until(1, b">") == b">"  # returned without touching the port again
    assert instance._leftover == bytearray()


def test_read_until_continues_on_the_port_when_the_prompt_has_not_arrived(transport, monkeypatch):
    instance, base = transport
    monkeypatch.setattr(base, "read_until", lambda self, *args, **kwargs: b"zz>")

    assert instance.read_until(1, b">") == b"zz>"


def test_read_until_keeps_stray_bytes_read_past_the_output(transport, monkeypatch):
    instance, base = transport
    instance._leftover.extend(b"x")
    monkeypatch.setattr(base, "read_until", lambda self, *args, **kwargs: b"zz>")

    assert instance.read_until(1, b">") == b"xzz>"


def test_streaming_consumers_keep_mpremotes_own_follow(transport, monkeypatch):
    instance, base = transport
    monkeypatch.setattr(base, "follow", lambda self, timeout, data_consumer=None: (b"streamed", b""))

    assert instance.follow(1.0, data_consumer=lambda data: None) == (b"streamed", b"")
