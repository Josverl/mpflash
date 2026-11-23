import sys
from pathlib import Path
from typing import List, Optional

import pytest
from unittest.mock import MagicMock
from pytest_mock import MockerFixture
from serial.tools.list_ports_common import ListPortInfo

from mpflash.mpremoteboard import OK, MPRemoteBoard
from mpflash.mpremoteboard.runner import run

HERE = Path(__file__).parent.resolve()

pytestmark = [pytest.mark.mpflash]


def test_mpremoteboard_new():
    # Make sure that the prompt is not called when interactive is False
    mprb = MPRemoteBoard()
    assert mprb
    assert mprb.serialport == ""
    assert mprb.family == "unknown"


@pytest.mark.parametrize("serialport", ["COM40", "/dev/ttyACM0"])
def test_mpremoteboard_retains_pyserial_usb_descriptors(serialport: str, mocker: MockerFixture):
    port = MagicMock(
        device=serialport,
        vid=0x1D50,
        pid=0x6196,
        serial_number="ABC123",
        manufacturer="Black Magic Debug",
        product="Black Magic Probe",
        description="Black Magic Probe GDB Server (COM40)",
    )
    mocker.patch(
        "mpflash.mpremoteboard.serial.tools.list_ports.grep",
        return_value=[port],
    )

    mprb = MPRemoteBoard(serialport)

    assert mprb.vid == 0x1D50
    assert mprb.pid == 0x6196
    assert mprb.usb_manufacturer == "Black Magic Debug"
    assert mprb.usb_product == "Black Magic Probe"
    assert mprb.usb_description == "Black Magic Probe GDB Server (COM40)"
    assert mprb.serial_number == "ABC123"


def test_mpremoteboard_reads_usb_serial_number_of_posix_device(mocker: MockerFixture):
    # /dev/ttyACM0 is an absolute path but a serial port, not a UF2 volume.
    port = MagicMock(
        device="/dev/ttyACM0",
        vid=0x04B4,
        pid=0xF155,
        manufacturer="Cypress",
        product="KitProg3 CMSIS-DAP",
        description="KitProg3 CMSIS-DAP",
        serial_number="1D160D98012D2400",
    )
    grep = mocker.patch(
        "mpflash.mpremoteboard.serial.tools.list_ports.grep",
        return_value=[port],
    )

    mprb = MPRemoteBoard("/dev/ttyACM0")

    grep.assert_called_once_with("/dev/ttyACM0")
    assert (mprb.vid, mprb.pid) == (0x04B4, 0xF155)
    assert mprb.usb_serial_number == "1D160D98012D2400"


@pytest.mark.parametrize(
    "selected, other",
    [("COM8", "COM88"), ("/dev/ttyACM1", "/dev/ttyACM10"), ("/dev/tty.usb[1]", "/dev/ttyXusb1")],
)
def test_mpremoteboard_matches_exact_serial_device(mocker: MockerFixture, selected: str, other: str):
    target = ListPortInfo(selected)
    target.vid, target.pid, target.serial_number = 0x04B4, 0xF155, "TARGET"
    unrelated = ListPortInfo(other)
    unrelated.vid, unrelated.pid, unrelated.serial_number = 0x04B4, 0xF155, "OTHER"
    mocker.patch("serial.tools.list_ports.comports", return_value=[target, unrelated])

    board = MPRemoteBoard(selected)

    assert board.usb_serial_number == "TARGET"
    assert (board.vid, board.pid) == (0x04B4, 0xF155)


def test_mpremoteboard_does_not_use_a_similar_serial_device(mocker: MockerFixture):
    other = ListPortInfo("COM88")
    other.vid, other.pid, other.serial_number = 0x04B4, 0xF155, "OTHER"
    mocker.patch("serial.tools.list_ports.comports", return_value=[other])

    board = MPRemoteBoard("COM8")

    assert board.usb_serial_number == ""
    assert (board.vid, board.pid) == (0, 0)


def test_mpremoteboard_skips_usb_lookup_for_volume_directory(mocker: MockerFixture, tmp_path: Path):
    grep = mocker.patch("mpflash.mpremoteboard.serial.tools.list_ports.grep")

    mprb = MPRemoteBoard(str(tmp_path))

    grep.assert_not_called()
    assert (mprb.vid, mprb.pid) == (0, 0)
    assert mprb.usb_serial_number == ""


@pytest.mark.parametrize(
    "comports, expected",
    [
        ([MagicMock(device="COM1")], ["COM1"]),
        ([MagicMock(device="COM1"), MagicMock(device="COM2")], ["COM1", "COM2"]),
        ([MagicMock(device="COM2"), MagicMock(device="COM1")], ["COM1", "COM2"]),
        ([MagicMock(device="COM3"), MagicMock(device="COM25", description="fancy bluetooth")], ["COM3"]),
    ],
)
def test_mpremoteboard_list(expected, comports, mocker: MockerFixture):
    # Make sure that the prompt is not called when interactive is False
    mprb = MPRemoteBoard()
    # mock serial.tools.list_ports.comports()
    mocker.patch(
        "mpflash.mpremoteboard.serial.tools.list_ports.comports",
        return_value=comports,
    )
    assert mprb.connected_comports() == expected


@pytest.mark.parametrize(
    "port",
    [
        ("COM20"),
        ("AUTO"),
        (""),
    ],
)
@pytest.mark.parametrize(
    "command",
    [
        (["run", "mpy_fw_info.py"]),
        ("run mpy_fw_info.py"),
    ],
)
def test_mpremoteboard_run(port: str, command: str | List[str], mocker: MockerFixture):
    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output", "more output"]))

    mprb = MPRemoteBoard(port)
    assert not mprb.connected
    expected_command = command.split(" ") if isinstance(command, str) else command.copy()
    mprb.run_command(command)

    assert mprb.connected
    assert m_run.called
    assert m_run.call_count == 1

    # 1st command is python executable
    assert m_run.mock_calls[0].args[0][0] == sys.executable
    # should en in the command
    assert m_run.mock_calls[0].args[0][-2:] == expected_command
    # if port specified should start with connectbut not otherwise
    assert ("connect" in m_run.mock_calls[0].args[0]) == (port != "")
    assert (port in m_run.mock_calls[0].args[0]) == (port != "")
    assert "resume" not in m_run.mock_calls[0].args[0]
    assert "soft-reset" not in m_run.mock_calls[0].args[0]

    # Subsequent commands also preserve interpreter state by default.
    mprb.run_command(command)
    assert "resume" not in m_run.mock_calls[1].args[0]
    assert "soft-reset" not in m_run.mock_calls[1].args[0]
    assert command == (" ".join(expected_command) if isinstance(command, str) else expected_command)


def test_mpremoteboard_run_soft_reset_false(mocker: MockerFixture):
    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output"]))

    MPRemoteBoard("COM20").run_command(["exec", "pass"], soft_reset=False)

    assert "resume" not in m_run.call_args.args[0]
    assert "soft-reset" not in m_run.call_args.args[0]


def test_mpremoteboard_run_soft_reset_does_not_affect_next_command(mocker: MockerFixture):
    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output"]))
    board = MPRemoteBoard("COM20")
    command = ["exec", "pass"]

    board.run_command(command, soft_reset=True)
    board.run_command(command)

    assert "soft-reset" in m_run.call_args_list[0].args[0]
    assert "soft-reset" not in m_run.call_args_list[1].args[0]
    assert all("resume" not in call.args[0] for call in m_run.call_args_list)
    assert command == ["exec", "pass"]


def test_mpremoteboard_run_soft_reset(mocker: MockerFixture):
    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output"]))

    mprb = MPRemoteBoard("COM20")
    mprb.run_command(["exec", "import createstubs_db"], soft_reset=True)

    assert m_run.call_args.args[0] == [
        sys.executable,
        "-m",
        "mpremote",
        "connect",
        "COM20",
        "soft-reset",
        "exec",
        "import createstubs_db",
    ]


@pytest.mark.parametrize(
    ("resume", "expects_soft_reset"),
    [(None, False), (True, False), (False, True)],
)
def test_mpremoteboard_run_deprecated_resume(resume, expects_soft_reset, mocker: MockerFixture):
    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output"]))

    mprb = MPRemoteBoard("COM20")
    with pytest.warns(DeprecationWarning, match="resume is deprecated") as warning:
        mprb.run_command(["run", "mpy_fw_info.py"], resume=resume)

    command = m_run.call_args.args[0]
    assert ("soft-reset" in command) is expects_soft_reset
    assert "resume" not in command
    assert Path(warning[0].filename).resolve() == Path(__file__).resolve()


@pytest.mark.parametrize("soft_reset", [False, True])
def test_mpremoteboard_run_rejects_both_reset_interfaces(soft_reset, mocker: MockerFixture):
    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output"]))

    with pytest.raises(TypeError, match="cannot be used together"):
        MPRemoteBoard("COM20").run_command(["exec", "pass"], soft_reset=soft_reset, resume=True)

    m_run.assert_not_called()


@pytest.mark.parametrize(
    "port",
    [
        ("COM20"),
        ("AUTO"),
        (""),
    ],
)
def test_mpremoteboard_disconnect(port, mocker: MockerFixture):
    # sourcery skip: remove-redundant-if
    # port = "COM20"

    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output", "more output"]))
    m_log_error = mocker.patch("mpflash.mpremoteboard.log.error")

    mprb = MPRemoteBoard(port)
    mprb.connected = True
    result = mprb.disconnect()
    assert not mprb.connected

    if not port:
        assert not result
        return

    assert result
    assert m_run.called
    assert m_run.call_count == 1

    # 1st command is python executable
    assert m_run.mock_calls[0].args[0][0] == sys.executable
    assert "disconnect" in m_run.mock_calls[0].args[0]
    assert (port in m_run.mock_calls[0].args[0]) == (port != "")

    if port:
        # No error
        m_log_error.assert_not_called()
    else:
        # should show error if no port
        m_log_error.assert_called_once()


# TODO; Add test for different micrpython boards / versions / variants with and withouth sys.implementation._build


def test_mpremoteboard_info(mocker: MockerFixture, session_fx):
    output = [
        "{'port': 'esp32', 'build': '236', 'arch': 'xtensawin', 'family': 'micropython', 'board': 'Generic ESP32 module with ESP32','_build': '', 'cpu': 'ESP32', 'version': '1.23.0-preview', 'mpy': 'v6.2', 'ver': 'v1.23.0-preview-236'}"
    ]

    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(0, output))

    mprb = MPRemoteBoard("COM20")
    mprb.get_mcu_info()  # type: ignore

    assert m_run.called
    assert "soft-reset" in m_run.call_args_list[0].args[0]

    assert mprb.family == "micropython"
    assert mprb.version == "1.23.0-preview"
    assert mprb.build == "236"
    assert mprb.port == "esp32"
    assert mprb.sys_platform == "esp32"
    assert mprb.cpu == "ESP32"
    assert mprb.arch == "xtensawin"
    assert mprb.mpy == "v6.2"
    assert mprb.description == "Generic ESP32 module with ESP32"
    assert mprb.board == "ESP32_GENERIC"
    assert mprb.variant == ""


@pytest.mark.parametrize("soft_reset", [False, True])
def test_get_mcu_info_explicit_soft_reset(soft_reset: bool, mocker: MockerFixture):
    output = [
        "{'port': 'rp2', 'build': '', 'arch': 'armv6m', 'family': 'micropython', "
        "'board': 'RPI_PICO', 'board_id': 'RPI_PICO', 'cpu': 'RP2040', "
        "'version': '1.30.0-preview', 'mpy': 'v6.3', 'description': 'Raspberry Pi Pico'}"
    ]
    run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, output))
    mocker.patch.object(MPRemoteBoard, "get_board_info_toml_once")

    MPRemoteBoard("COM42").get_mcu_info(soft_reset=soft_reset)

    assert ("soft-reset" in run.call_args.args[0]) is soft_reset
    assert "resume" not in run.call_args.args[0]


@pytest.mark.parametrize(
    ("resume", "expected_soft_reset"),
    [(None, False), (True, False), (False, True)],
)
def test_get_mcu_info_deprecated_resume(resume, expected_soft_reset, mocker: MockerFixture):
    output = [
        "{'port': 'esp32', 'build': '', 'arch': 'xtensa', 'family': 'micropython', "
        "'board': 'ESP32_GENERIC', 'cpu': 'ESP32', 'version': '1.30.0-preview', "
        "'mpy': 'v6.3', 'description': 'Generic ESP32'}"
    ]
    run_command = mocker.patch.object(MPRemoteBoard, "run_command_once", return_value=(OK, output))
    mocker.patch.object(MPRemoteBoard, "get_board_info_toml_once")

    with pytest.warns(DeprecationWarning, match="resume is deprecated"):
        MPRemoteBoard("COM20").get_mcu_info(resume=resume)

    assert run_command.call_args.kwargs["soft_reset"] is expected_soft_reset
    assert "resume" not in run_command.call_args.kwargs


def test_get_mcu_info_rejects_both_reset_interfaces(mocker: MockerFixture):
    run_command = mocker.patch.object(MPRemoteBoard, "run_command")

    with pytest.raises(TypeError, match="cannot be used together"):
        MPRemoteBoard("COM20").get_mcu_info(soft_reset=False, resume=True)

    run_command.assert_not_called()


def test_mpremoteboard_info_resolves_reported_port(mocker: MockerFixture, session_fx):
    output = [
        "{'port': 'nrf52', 'sys_platform': 'nrf52', 'build': '', 'arch': "
        "'armv7emsp', 'family': 'micropython', 'board': 'SEEED_XIAO_NRF52', "
        "'board_id': 'SEEED_XIAO_NRF52', 'cpu': 'NRF52840', 'version': "
        "'1.28.0', 'mpy': 'v6.3', 'description': 'XIAO nRF52840 Sense'}"
    ]
    mocker.patch("mpflash.mpremoteboard.run", return_value=(0, output))
    mocker.patch.object(MPRemoteBoard, "get_board_info_toml")
    mocker.patch(
        "mpflash.mpremoteboard.best_matching_port",
        return_value="nrf",
    )

    mprb = MPRemoteBoard("COM8")
    mprb.get_mcu_info()

    assert mprb.port == "nrf"
    assert mprb.sys_platform == "nrf52"
    assert mprb.to_dict()["sys_platform"] == "nrf52"


def test_mpremoteboard_info_with_warning_prefix(mocker: MockerFixture, session_fx):
    """Board info dict is correctly parsed when a WARN line precedes it (Bug fix).

    mpy_fw_info.py emits 'WARN  : BOARD_ID not found' before the dict when
    the boardname.py file is absent.  The old code only checked result[0] and
    therefore missed the dict entirely.
    """
    info_dict = (
        "{'port': 'esp32', 'build': '', 'arch': 'rv32imc', 'family': 'micropython',"
        " 'board': '', 'board_id': '', 'variant': '', 'cpu': 'ESP32-C6',"
        " 'version': '1.27.0', 'mpy': 'v6.3', 'ver': '1.27.0',"
        " 'description': 'Custom ESP32-C6 board with ESP32-C6'}"
    )
    output = [
        "WARN  : BOARD_ID not found\n",
        info_dict + "\n",
    ]

    mocker.patch("mpflash.mpremoteboard.run", return_value=(0, output))
    # get_board_info_toml is a separate method; stub it out
    mocker.patch.object(MPRemoteBoard, "get_board_info_toml")

    mprb = MPRemoteBoard("COM15")
    mprb.get_mcu_info()

    # Core fields that were previously empty must now be populated
    assert mprb.family == "micropython"
    assert mprb.version == "1.27.0"
    assert mprb.port == "esp32"
    assert mprb.cpu == "ESP32-C6"
    assert mprb.description == "Custom ESP32-C6 board with ESP32-C6"
    assert mprb.connected is True
    # board_id should be a non-empty fallback, not blank
    assert mprb.board_id != ""


def test_mpremoteboard_info_unknown_board_id(mocker: MockerFixture, session_mem):
    """When board_id is empty and description has no DB match, fall back to UNKNOWN_BOARD.

    find_board_id_by_description raises MPFlashError for custom/unknown boards.
    The old code let that exception escape; the fix catches it and sets the
    board_id to UNKNOWN_BOARD so all other fields are still shown.

    session_mem provides an empty in-memory DB so find_board_id_by_description
    raises MPFlashError (no boards to match against), exercising the catch path.
    """
    info_dict = (
        "{'port': 'esp32', 'build': '', 'arch': 'rv32imc', 'family': 'micropython',"
        " 'board': '', 'board_id': '', 'variant': '', 'cpu': 'ESP32-C6',"
        " 'version': '1.27.0', 'mpy': 'v6.3', 'ver': '1.27.0',"
        " 'description': 'Custom ESP32-C6 board with ESP32-C6'}"
    )
    output = [
        "WARN  : BOARD_ID not found\n",
        info_dict + "\n",
    ]

    mocker.patch("mpflash.mpremoteboard.run", return_value=(0, output))
    mocker.patch.object(MPRemoteBoard, "get_board_info_toml")

    mprb = MPRemoteBoard("COM15")
    mprb.get_mcu_info()

    # Should not raise; all readable fields must be populated
    assert mprb.family == "micropython"
    assert mprb.version == "1.27.0"
    assert mprb.port == "esp32"
    assert mprb.cpu == "ESP32-C6"
    assert mprb.connected is True
    # board_id must be a non-empty fallback
    assert mprb.board_id != ""


def test_mpremoteboard_info_board_id_from_toml(mocker: MockerFixture, session_mem):
    """board_id from board_info.toml overrides the UNKNOWN_BOARD fallback.

    When the device has a board_info.toml with [mpflash].board_id set (written
    there by a previous custom-firmware flash), that value should be used so
    the board is identified correctly even without a DB match.
    """
    info_dict = (
        "{'port': 'esp32', 'build': '', 'arch': 'rv32imc', 'family': 'micropython',"
        " 'board': '', 'board_id': '', 'variant': '', 'cpu': 'ESP32-C6',"
        " 'version': '1.27.0', 'mpy': 'v6.3', 'ver': '1.27.0',"
        " 'description': 'Custom ESP32-C6 board with ESP32-C6'}"
    )
    output = [
        "WARN  : BOARD_ID not found\n",
        info_dict + "\n",
    ]

    mocker.patch("mpflash.mpremoteboard.run", return_value=(0, output))

    def _set_toml(self, timeout=1, *, soft_reset=False):
        self.toml = {"mpflash": {"board_id": "MY_CUSTOM_C6"}}

    mocker.patch.object(MPRemoteBoard, "get_board_info_toml_once", _set_toml)

    mprb = MPRemoteBoard("COM15")
    mprb.get_mcu_info()

    assert mprb.board_id == "MY_CUSTOM_C6"
    assert mprb.connected is True


def test_mpremoteboard_info_requires_payload(mocker: MockerFixture):
    """get_mcu_info must fail when no info dict is present in output.

    This prevents false-positive reconnect detection during reboot windows
    where mpremote can return rc=0/1 without a parsable payload.
    """
    mocker.patch("mpflash.mpremoteboard.run", return_value=(0, []))

    mprb = MPRemoteBoard("COM15")

    with pytest.raises(ConnectionError):
        mprb.get_mcu_info_once()

    assert mprb.connected is False


def test_refresh_serialport_follows_usb_serial_number(mocker: MockerFixture):
    board = MPRemoteBoard("/dev/ttyACM0")
    board.serial_number = "TARGET"
    target = ListPortInfo("/dev/ttyACM2")
    target.serial_number = "TARGET"
    other = ListPortInfo("/dev/ttyACM1")
    other.serial_number = "OTHER"
    mocker.patch("serial.tools.list_ports.comports", return_value=[other, target])

    assert board._refresh_serialport() is True
    assert board.serialport == "/dev/ttyACM2"


def test_refresh_serialport_refuses_ambiguous_vid_pid(mocker: MockerFixture):
    board = MPRemoteBoard("/dev/ttyACM0")
    board.vid, board.pid = 0x2E8A, 0x1002
    ports = [ListPortInfo("/dev/ttyACM1"), ListPortInfo("/dev/ttyACM2")]
    for port in ports:
        port.vid, port.pid = board.vid, board.pid
    mocker.patch("serial.tools.list_ports.comports", return_value=ports)

    assert board._refresh_serialport() is False
    assert board.serialport == "/dev/ttyACM0"


def test_wait_for_restart_uses_quiet_probe(mocker: MockerFixture):
    mprb = MPRemoteBoard("COM15")
    m_get = mocker.patch.object(
        MPRemoteBoard,
        "get_mcu_info_once",
        autospec=True,
        side_effect=[ConnectionError("not ready"), None],
    )
    mocker.patch("mpflash.mpremoteboard.time.sleep")

    restarted = mprb.wait_for_restart(timeout=3)

    assert m_get.call_count == 2
    assert m_get.call_args_list[0].kwargs.get("log_errors") is False
    assert m_get.call_args_list[1].kwargs.get("log_errors") is False
    # polling must not reset the board on every probe
    assert m_get.call_args_list[0].kwargs.get("soft_reset") is False
    assert restarted is True


def test_wait_for_restart_does_not_multiply_get_info_retries(
    mocker: MockerFixture,
):
    mprb = MPRemoteBoard("COM15")
    get_mcu_info = mocker.patch.object(
        MPRemoteBoard,
        "get_mcu_info_once",
        autospec=True,
        side_effect=ConnectionError("not ready"),
    )
    mocker.patch("mpflash.mpremoteboard.time.sleep")

    restarted = mprb.wait_for_restart(timeout=3)

    assert get_mcu_info.call_count == 3
    assert restarted is False


def test_wait_for_restart_reattaches_with_usbipd_on_wsl2(mocker: MockerFixture, monkeypatch):
    from mpflash.config import config

    mprb = MPRemoteBoard("/dev/ttyACM0")
    mprb.vid = 0x2E8A
    mprb.pid = 0x1002
    mprb.serial_number = "E46024C7434C552A"
    monkeypatch.setattr("mpflash.mpremoteboard.ON_WSL2", True)
    monkeypatch.setattr(config, "usbipd", True)
    mocker.patch.object(mprb, "_refresh_serialport", return_value=False)
    mocker.patch("mpflash.mpremoteboard.time.sleep")
    mocker.patch("mpflash.mpremoteboard.usbipd.find_usbipd", return_value="usbipd.exe")
    reattach = mocker.patch("mpflash.mpremoteboard.usbipd.reattach_usbipd_device", return_value=True)
    mocker.patch.object(MPRemoteBoard, "get_mcu_info_once", autospec=True)

    assert mprb.wait_for_restart(timeout=1) is True
    reattach.assert_called_once_with(
        vid=0x2E8A,
        pid=0x1002,
        serial_number="E46024C7434C552A",
        executable="usbipd.exe",
    )


def test_wait_for_restart_respects_no_usbipd(mocker: MockerFixture, monkeypatch):
    from mpflash.config import config

    mprb = MPRemoteBoard("/dev/ttyACM0")
    monkeypatch.setattr("mpflash.mpremoteboard.ON_WSL2", True)
    monkeypatch.setattr(config, "usbipd", False)
    find_usbipd = mocker.patch("mpflash.mpremoteboard.usbipd.find_usbipd")
    mocker.patch("mpflash.mpremoteboard.time.sleep")
    mocker.patch.object(MPRemoteBoard, "get_mcu_info_once", autospec=True)

    assert mprb.wait_for_restart(timeout=1) is True
    find_usbipd.assert_not_called()


def test_get_board_info_toml_missing_file_preserves_connected(mocker: MockerFixture):
    mprb = MPRemoteBoard("COM15")
    mprb.connected = True

    m_run = mocker.patch.object(mprb, "run_command_once", return_value=(1, []))

    mprb.get_board_info_toml()

    assert mprb.connected is True
    assert mprb.toml == {}
    assert m_run.call_args.kwargs.get("soft_reset") is True


def test_mpy_fw_info_keeps_description(monkeypatch):
    from mpflash.mpremoteboard import mpy_fw_info as mpy_info

    class FakeImplementation:
        def __init__(self):
            self._machine = "Test Board with MCU"
            self._build = "TEST-BOARD"
            self.version = (1, 26, 0, "")
            self._mpy = 0
            self.name = "MicroPython"

        def __getitem__(self, index):
            return ("MicroPython",)[index]

    monkeypatch.setattr(mpy_info.sys, "implementation", FakeImplementation())
    monkeypatch.setattr(mpy_info.sys, "platform", "esp32")

    def version_str(version: tuple) -> str:
        v_str = ".".join(str(n) for n in version[:3])
        if len(version) > 3 and version[3]:
            v_str += f"-{version[3]}"
        return v_str

    monkeypatch.setattr(mpy_info, "_version_str", version_str, raising=False)

    info = mpy_info._get_base_system_info()
    mpy_info._normalize_port_info(info)
    mpy_info._extract_version_info(info)
    mpy_info._extract_hardware_info(info)
    mpy_info._extract_build_info(info)
    mpy_info._detect_firmware_family(info)
    mpy_info._process_micropython_version(info)
    mpy_info._process_mpy_info(info)
    mpy_info._format_version_strings(info)

    assert info["description"] == "Test Board with MCU"
    assert info["board_id"] == "TEST-BOARD"
    assert info["board"] == "TEST"
    assert info["variant"] == "BOARD"


@pytest.mark.parametrize(
    "id, cmd, ret_code, exception",
    [
        (1, [sys.executable, "-m", "mpremote", "--help"], 0, None),
        (2, [sys.executable, str(HERE / "fake_output.py")], 0, None),
        (3, [sys.executable, str(HERE / "fake_slow_output.py")], 1, None),  # timeout
        (4, [sys.executable, str(HERE / "fake_reset.py")], 1, RuntimeError),
    ],
)
@pytest.mark.xfail(reason="Different error messages across platforms")
def test_runner_run(id, cmd: List[str], ret_code: int, exception: Optional[Exception]):
    # Test the run function with different commands
    # and check the return code and output

    if exception:
        with pytest.raises(exception):  # type: ignore
            run(cmd, timeout=1, success_tags=["OK    :"], log_warnings=True)
        return
    ret, output = run(cmd, timeout=1, success_tags=["OK    :"], log_warnings=True)
    if id == 3:
        # timeout test behaves differently across platforms
        return
    assert ret == ret_code
    assert isinstance(output, List)
