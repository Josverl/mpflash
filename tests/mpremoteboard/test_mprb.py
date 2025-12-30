import sys
from pathlib import Path
from typing import List, Optional

import pytest
from mock import MagicMock
from pytest_mock import MockerFixture

from mpflash.db.loader import HERE
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
def test_mpremoteboard_run(port, command, mocker: MockerFixture):
    # port = "COM20"

    m_run = mocker.patch("mpflash.mpremoteboard.run", return_value=(OK, ["output", "more output"]))

    mprb = MPRemoteBoard(port)
    assert not mprb.connected
    command = ["run", "mpy_fw_info.py"]
    result = mprb.run_command(command)  # type: ignore

    assert mprb.connected
    assert m_run.called
    assert m_run.call_count == 1

    # 1st command is python executable
    assert m_run.mock_calls[0].args[0][0] == sys.executable
    # should en in the command
    assert m_run.mock_calls[0].args[0][-2:] == command
    # if port specified should start with connectbut not otherwise
    assert ("connect" in m_run.mock_calls[0].args[0]) == (port != "")
    assert (port in m_run.mock_calls[0].args[0]) == (port != "")
    assert "resume" not in m_run.mock_calls[0].args[0]

    # run another command, and check for resume
    result = mprb.run_command(command)  # type: ignore
    assert "resume" in m_run.mock_calls[1].args[0]


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
        assert result == False
        return

    assert result == True
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
    mocker.patch("mpflash.mpboard_id.board_id.Session", session_fx)

    mprb = MPRemoteBoard("COM20")
    result = mprb.get_mcu_info()  # type: ignore

    assert m_run.called

    assert mprb.family == "micropython"
    assert mprb.version == "1.23.0-preview"
    assert mprb.build == "236"
    assert mprb.port == "esp32"
    assert mprb.cpu == "ESP32"
    assert mprb.arch == "xtensawin"
    assert mprb.mpy == "v6.2"
    assert mprb.description == "Generic ESP32 module with ESP32"
    assert mprb.board == "ESP32_GENERIC"
    assert mprb.variant == ""


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
