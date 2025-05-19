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
    assert mprb.connected_boards() == expected


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


@pytest.mark.parametrize(
    "id, cmd, ret_code, exception",
    [
        (1, [sys.executable, "-m", "mpremote", "--help"], 0, None),
        (2, [sys.executable, str(HERE / "fake_output.py")], 0, None),
        (3, [sys.executable, str(HERE / "fake_slow_output.py")], 1, None),  # timeout
        (4, [sys.executable, str(HERE / "fake_reset.py")], 1, RuntimeError),
    ],
)
def test_runner_run(id, cmd: List[str], ret_code: int, exception: Optional[Exception]):
    # Test the run function with different commands
    # and check the return code and output

    if exception:
        with pytest.raises(exception):
            run(cmd, timeout=1, success_tags=["OK    :"], log_warnings=True)
        return
    ret, output = run(cmd, timeout=1, success_tags=["OK    :"], log_warnings=True)
    if id == 3:
        # timeout test behaves differently across platforms
        return
    assert ret == ret_code
    assert isinstance(output, List)
