from typing import List

import pytest
from click.testing import CliRunner
from mock import Mock
from pytest_mock import MockerFixture

# # module under test :
from mpflash import cli_main
from mpflash.common import DownloadParams
from mpflash.mpremoteboard import MPRemoteBoard

# mark all tests
pytestmark = pytest.mark.mpflash


##########################################################################################
def fakeboard(serialport="COM99"):
    fake = MPRemoteBoard(serialport)
    fake.connected = True
    fake.family = "micropython"
    fake.port = "esp32"
    fake.board_id = "ESP32_GENERIC"
    fake.version = "1.22.0"
    fake.cpu = "ESP32"
    return fake


def fake_ask_missing_params(params: DownloadParams) -> DownloadParams:
    # no input during tests
    return params


##########################################################################################
# flash


@pytest.mark.parametrize("serialport", ["COM99"])
@pytest.mark.parametrize(
    "id, ex_code, args",
    [
        ("10", 0, ["flash"]),
        ("20", 0, ["flash", "--version", "1.22.0"]),
        ("21", 0, ["flash", "--version", "stable"]),
        ("30", 0, ["flash", "--board", "ESP32_GENERIC"]),
        ("31", 0, ["flash", "--board", "?"]),
        ("40", 0, ["flash", "--bootloader", "none"]),
        # faulty
        # ("81", -1, ["flash", "--board", "RPI_PICO", "--board", "ESP32_GENERIC"]),
        # ("82", -1, ["flash", "--version", "preview", "--version", "1.22.0"]),
    ],
)
@pytest.mark.skip(reason="TODO: Test too complex to run reliablely")
def test_mpflash_flash(id, ex_code, args: List[str], mocker: MockerFixture, serialport: str, session_fx):
    # fake COM99 as connected board
    fake = fakeboard(serialport)

    m_mpr_connected = mocker.patch("mpflash.flash.worklist.MPRemoteBoard", return_value=fake)  # type: ignore
    m_mpr_connected = mocker.patch("mpflash.flash.worklist.MPRemoteBoard.connected_boards", return_value=fake.serialport)  # type: ignore
    mocker.patch("mpflash.flash.worklist.filter_boards", return_value=[MPRemoteBoard("COM99")], autospec=True)

    m_connected_ports_boards = mocker.patch(
        "mpflash.cli_flash.connected_ports_boards",
        return_value=(["esp32"], ["ESP32_GENERIC"], [MPRemoteBoard("COM99")]),
        autospec=True,
    )

    m_flash_list = mocker.patch("mpflash.cli_flash.flash_list", return_value=None, autospec=True)
    m_ask_missing_params = mocker.patch(
        "mpflash.cli_flash.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    mocker.patch("mpflash.download.Session", session_fx)
    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    if "--board" not in args:
        m_connected_ports_boards.assert_called_once()

    m_ask_missing_params.assert_called_once()
    m_flash_list.assert_called_once()
    assert result.exit_code == ex_code
    # if "?" not in args:
    #     m_mpr_connected.assert_called_once()


# TODO : Add more tests scenarios for flash


@pytest.mark.parametrize(
    "id, serialports, ports, boards",
    [
        ("one", ["COM99"], ["esp32"], ["ESP32_GENERIC"]),
        ("multiple", ["COM99", "COM100"], ["esp32", "samd"], ["ESP32_GENERIC", "SEEED_WIO_TERMINAL"]),
        ("None", [], [], []),
        ("linux", ["/dev/ttyusb0"], ["rp2"], ["ARDUINO_NANO_RP2040_CONNECT"]),
    ],
)
def test_mpflash_connected_boards(
    id,
    serialports: List[str],
    ports: List[str],
    boards: List[str],
    mocker: MockerFixture,
):
    # no boards specified - detect connected boards
    args = ["flash"]

    fakes = [fakeboard(port) for port in serialports]  # type: ignore

    m_connected_ports_boards = mocker.patch(
        "mpflash.cli_flash.connected_ports_boards",
        return_value=(ports, boards, [MPRemoteBoard(p) for p in serialports]),
        autospec=True,
    )
    m_flash_list = mocker.patch("mpflash.cli_flash.flash_list", return_value=None, autospec=True)  # type: ignore
    m_ask_missing_params = mocker.patch(
        "mpflash.cli_flash.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )

    m_full_auto_worklist = mocker.patch("mpflash.cli_flash.full_auto_worklist", return_value=[])
    m_manual_worklist = mocker.patch("mpflash.cli_flash.manual_worklist", return_value=[])
    m_single_auto_worklist = mocker.patch("mpflash.cli_flash.single_auto_worklist", return_value=[])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    if serialports:
        # TODO: Improve test logic for worklist creation
        # m_full_auto_worklist.assert_called_once()
        # m_manual_worklist.assert_not_called()
        # m_manual_worklist.assert_called_once()
        m_single_auto_worklist.assert_not_called()

    m_connected_ports_boards.assert_called_once()
    m_ask_missing_params.assert_called_once()

    # test exit code (standalone mode)
    assert result
    assert result.exit_code == 0


## if no boards are connected , but there are serial port , then set serial --> ? and board to ? if not set
@pytest.mark.parametrize(
    "id, serialports, ports, boards",
    [
        ("One", ["COM99"], [], []),
        ("None", [], [], []),
    ],
)
def test_mpflash_no_detected_boards(
    id,
    serialports: List[str],
    ports: List[str],
    boards: List[str],
    mocker: MockerFixture,
):
    # no boards specified - detect connected boards
    args = ["flash"]

    # fakes = [fakeboard(port) for port in serialports]

    m_connected_ports_boards = mocker.patch(
        "mpflash.cli_flash.connected_ports_boards",
        return_value=(ports, boards, [MPRemoteBoard(p) for p in serialports]),
        autospec=True,
    )
    m_flash_list = mocker.patch("mpflash.cli_flash.flash_list", return_value=None, autospec=True)  # type: ignore
    m_ask_missing_params = mocker.patch(
        "mpflash.cli_flash.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )

    m_full_auto_worklist = mocker.patch("mpflash.cli_flash.full_auto_worklist", return_value=[])  # type: ignore
    m_manual_worklist = mocker.patch("mpflash.cli_flash.manual_worklist", return_value=[])  # type: ignore
    m_single_auto_worklist = mocker.patch("mpflash.cli_flash.single_auto_worklist", return_value=[])  # type: ignore

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)
    assert result
    m_connected_ports_boards.assert_called_once()
    m_ask_missing_params.assert_called_once()

    if serialports:
        ## if no boards are responding , but there are serial port , then set serial --> ? and board to ? if not set
        assert m_ask_missing_params.call_args.args[0].serial == ["?"]
        assert m_ask_missing_params.call_args.args[0].boards == ["?"]


@pytest.mark.skip("TODO: Test Broken")
def test_flash_triggers_just_in_time_download(mocker: MockerFixture, session_fx):
    """
    If firmware is missing, ensure_firmware_downloaded triggers a download before flashing.
    """

    # Simulate no firmware found on first check, then present after download
    # Patch in both mpflash.downloaded and mpflash.cli_flash in case of direct import
    mocker.patch(
        "mpflash.downloaded.find_downloaded_firmware",
        side_effect=[[], [mocker.Mock()]],
    )
    # Do not patch ensure_firmware_downloaded, as it is not a top-level symbol
    # Patch download to simulate download action
    m_download = mocker.patch("mpflash.download.download", return_value=1)
    # Patch flash_list to simulate flashing
    m_flash_list = mocker.patch("mpflash.cli_flash.flash_list", return_value=None)
    # Patch ask_missing_params to avoid user input
    m_ask_missing_params = mocker.patch(
        "mpflash.cli_flash.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    # Patch connected_ports_boards to simulate a connected board
    m_connected_ports_boards = mocker.patch(
        "mpflash.cli_flash.connected_ports_boards",
        return_value=(["esp32"], ["ESP32_GENERIC"], [MPRemoteBoard("COM99")]),
        autospec=True,
    )
    mocker.patch("mpflash.download.Session", session_fx)
    mocker.patch("mpflash.downloaded.Session", session_fx)
    mocker.patch("mpflash.db.core.Session", session_fx)

    runner = CliRunner()
    args = ["flash", "--board", "ESP32_GENERIC", "--version", "1.24.1"]
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    # download should be triggered (since firmware was missing)
    m_download.assert_called()
    # flash_list should be called to proceed with flashing
    m_flash_list.assert_called_once()
    # CLI should succeed
    assert result.exit_code == 0
