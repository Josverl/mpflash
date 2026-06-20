from pathlib import Path
from typing import List
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

# # module under test :
from mpflash import cli_main
from mpflash.common import DownloadParams
from mpflash.db.models import Firmware
from mpflash.flash.worklist import FlashTask
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
    m_mpr_connected = mocker.patch("mpflash.flash.worklist.MPRemoteBoard.connected_comports", return_value=fake.serialport)  # type: ignore

    m_connected_ports_boards = mocker.patch(
        "mpflash.cli_flash.connected_ports_boards",
        return_value=(["esp32"], ["ESP32_GENERIC"], [MPRemoteBoard("COM99")]),
        autospec=True,
    )

    m_flash_tasks = mocker.patch("mpflash.cli_flash.flash_tasks", return_value=None, autospec=True)
    m_ask_missing_params = mocker.patch(
        "mpflash.cli_flash.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    if "--board" not in args:
        m_connected_ports_boards.assert_called_once()

    m_ask_missing_params.assert_called_once()
    m_flash_tasks.assert_called_once()
    assert result.exit_code == ex_code
    # if "?" not in args:
    #     m_mpr_connected.assert_called_once()


# TODO : Add more tests scenarios for flash


@pytest.mark.parametrize(
    "id, serialports, ports, boards, variants",
    [
        ("one", ["COM99"], ["esp32"], ["ESP32_GENERIC"], []),
        ("multiple", ["COM99", "COM100"], ["esp32", "samd"], ["ESP32_GENERIC", "SEEED_WIO_TERMINAL"], []),
        ("None", [], [], [], []),
        ("linux", ["/dev/ttyusb0"], ["rp2"], ["ARDUINO_NANO_RP2040_CONNECT"], []),
    ],
)
def test_mpflash_connected_comports(
    id,
    serialports: List[str],
    ports: List[str],
    boards: List[str],
    variants: List[str],
    mocker: MockerFixture,
):
    # no boards specified - detect connected boards
    args = ["flash"]

    fakes = [fakeboard(port) for port in serialports]  # type: ignore

    m_connected_ports_boards = mocker.patch(
        "mpflash.connected.connected_ports_boards_variants",
        return_value=(ports, boards, variants, [MPRemoteBoard(p) for p in serialports]),
        autospec=True,
    )
    flashed = [MPRemoteBoard(p) for p in serialports] if serialports else None
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=flashed, autospec=True)
    mocker.patch("mpflash.list.show_mcus", autospec=True)
    m_ask_missing_params = mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )

    m_create_worklist = mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    if serialports:
        # TODO: Improve test logic for worklist creation
        # These assertions are broken since both mocks point to the same function
        # m_full_auto_worklist.assert_called_once()
        # m_manual_worklist.assert_not_called()
        # m_manual_worklist.assert_called_once()
        # m_single_auto_worklist.assert_not_called()
        pass

    m_connected_ports_boards.assert_called_once()
    m_ask_missing_params.assert_called_once()

    # test exit code (standalone mode)
    assert result
    if serialports:
        assert result.exit_code == 0
    else:
        assert result.exit_code == 2


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
        "mpflash.connected.connected_ports_boards_variants",
        return_value=(ports, boards, [], [MPRemoteBoard(p) for p in serialports]),
        autospec=True,
    )
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=None, autospec=True)  # type: ignore
    m_ask_missing_params = mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )

    m_create_worklist = mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[])  # type: ignore

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)
    assert result
    m_connected_ports_boards.assert_called_once()
    m_ask_missing_params.assert_called_once()

    if serialports:
        ## if no boards are responding , but there are serial port , then set serial --> ? and board to ? if not set
        assert m_ask_missing_params.call_args.args[0].serial == ["?"]
        assert m_ask_missing_params.call_args.args[0].boards == ["?"]


def test_mpflash_flash_no_matching_serial_ports_returns_usage_error(mocker: MockerFixture):
    """Show a user-friendly CLI error when no serial port matches the filter."""
    args = ["flash", "--board", "RPI_PICO2", "--bootloader", "none", "--serial", "COM8"]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    mocker.patch("mpflash.common.filtered_comports", return_value=[])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 2
    assert "No serial ports matched" in result.output


def test_mpflash_flash_with_explicit_uf2_volume(mocker: MockerFixture):
    """Use --volume path for UF2 board already in boot mode."""
    from pathlib import Path

    args = ["flash", "--board", "RPI_PICO2", "--serial", "COM8", "--volume", "D:\\"]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )

    board = MPRemoteBoard("COM99")
    board.port = "rp2"
    board.board_id = "RPI_PICO2"
    fw = Firmware(board_id="RPI_PICO2", version="1.27.0", port="rp2", firmware_file="fw.uf2")
    task = FlashTask(board=board, firmware=fw)

    m_create_worklist = mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=[board])
    mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.list.show_mcus")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    m_create_worklist.assert_called_once()
    # Paths are normalized to platform-native format via Path()
    expected_path = str(Path("D:\\"))
    assert m_create_worklist.call_args.kwargs["serial_ports"] == [expected_path]
    m_flash_tasks.assert_called_once()


def test_mpflash_flash_with_volume_rejects_non_uf2_ports(mocker: MockerFixture):
    """Reject --volume when the selected board does not support UF2 flashing."""
    args = ["flash", "--board", "ESP32_GENERIC", "--volume", "D:\\"]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )

    board = MPRemoteBoard("COM99")
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC"
    fw = Firmware(board_id="ESP32_GENERIC", version="1.27.0", port="esp32", firmware_file="fw.bin")
    task = FlashTask(board=board, firmware=fw)
    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 2


def test_mpflash_board_detection_respects_explicit_serial_filter(mocker: MockerFixture):
    args = ["flash", "--serial", "COM77"]

    board = MPRemoteBoard("COM77")
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC"
    fw = Firmware(board_id="ESP32_GENERIC", version="v1.28.0", port="esp32", firmware_file="esp32/fw.bin")
    task = FlashTask(board=board, firmware=fw)

    m_connected = mocker.patch(
        "mpflash.connected.connected_ports_boards_variants",
        return_value=(["esp32"], ["ESP32_GENERIC"], [], [board]),
        autospec=True,
    )
    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.flash.flash_tasks", return_value=[board])
    mocker.patch("mpflash.list.show_mcus")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code in (0, 1)
    assert m_connected.call_args.kwargs["include"] == ["COM77"]


def test_mpflash_board_detection_uses_ports_when_serial_wildcard(mocker: MockerFixture):
    args = ["flash", "--port", "rp2", "--serial", "*"]

    board = MPRemoteBoard("/dev/ttyUSB0")
    board.port = "rp2"
    board.board_id = "RPI_PICO2"
    fw = Firmware(board_id="RPI_PICO2", version="v1.28.0", port="rp2", firmware_file="rp2/fw.uf2")
    task = FlashTask(board=board, firmware=fw)

    m_connected = mocker.patch(
        "mpflash.connected.connected_ports_boards_variants",
        return_value=(["rp2"], ["RPI_PICO2"], [], [board]),
        autospec=True,
    )
    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.flash.flash_tasks", return_value=[board])
    mocker.patch("mpflash.list.show_mcus")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code in (0, 1)
    assert m_connected.call_args.kwargs["include"] == ["rp2"]


def test_mpflash_flash_with_build_unavailable_returns_error(mocker: MockerFixture):
    args = ["flash", "--board", "ESP8266_GENERIC", "--build"]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    m_is_available = mocker.patch("mpflash.build.is_build_available", return_value=False)
    m_reason = mocker.patch("mpflash.build.get_build_unavailable_reason", return_value="mpbuild not installed")
    m_create_worklist = mocker.patch("mpflash.flash.worklist.create_worklist")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    m_is_available.assert_called_once()
    m_reason.assert_called_once()
    m_create_worklist.assert_not_called()


def test_mpflash_flash_with_build_imports_firmware_and_flashes(mocker: MockerFixture):
    args = ["flash", "--board", "ESP8266_GENERIC", "--serial", "COM99", "--build", "--bootloader", "none"]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    m_clean_version = mocker.patch(
        "mpflash.cli_flash.clean_version",
        side_effect=lambda v: "v1.29.0-preview" if v == "preview" else v,
    )
    mocker.patch("mpflash.build.is_build_available", return_value=True)

    fw_paths = [Path("/tmp/ESP8266_GENERIC-v1.26.0.bin")]
    m_build = mocker.patch("mpflash.build.build_firmware", return_value=fw_paths)
    m_import = mocker.patch("mpflash.build.import_firmware_to_database", return_value=1)

    mocker.patch("mpflash.cli_flash.filtered_comports", return_value=["COM99"])

    board = MPRemoteBoard("COM99")
    board.port = "esp8266"
    board.board_id = "ESP8266_GENERIC"
    fw = Firmware(
        board_id="ESP8266_GENERIC",
        version="stable",
        port="esp8266",
        firmware_file="esp8266/ESP8266_GENERIC-v1.26.0.bin",
    )
    task = FlashTask(board=board, firmware=fw)

    m_create_worklist = mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.list.show_mcus")
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=[board])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    m_clean_version.assert_called_once_with("preview")
    m_build.assert_called_once()
    built_board, built_version = m_build.call_args.args
    assert built_board == "ESP8266_GENERIC"
    assert built_version == "v1.29.0-preview"
    assert m_build.call_args.kwargs["force"] is True
    assert m_build.call_args.kwargs["preferred_suffixes"] == {".bin"}
    m_import.assert_called_once_with(
        fw_paths,
        "ESP8266_GENERIC",
        built_version,
        port="esp8266",
    )
    assert "To flash this built firmware again without rebuilding:" in result.output
    assert "mpflash flash --board ESP8266_GENERIC --version v1.29.0-preview" in result.output
    m_create_worklist.assert_called_once()
    m_flash_tasks.assert_called_once()


def test_mpflash_flash_with_build_and_clean_runs_clean_before_build(mocker: MockerFixture):
    args = ["flash", "--board", "ESP8266_GENERIC", "--serial", "COM99", "--build", "--clean", "--bootloader", "none"]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    mocker.patch("mpflash.build.is_build_available", return_value=True)

    call_order = []

    def _clean_side_effect(*args, **kwargs):
        call_order.append("clean")

    m_clean = mocker.patch("mpflash.build.clean_firmware", side_effect=_clean_side_effect)
    fw_paths = [Path("/tmp/ESP8266_GENERIC-v1.26.0.bin")]

    def _build_side_effect(*args, **kwargs):
        call_order.append("build")
        return fw_paths

    m_build = mocker.patch("mpflash.build.build_firmware", side_effect=_build_side_effect)
    mocker.patch("mpflash.build.import_firmware_to_database", return_value=1)

    mocker.patch("mpflash.cli_flash.filtered_comports", return_value=["COM99"])

    board = MPRemoteBoard("COM99")
    board.port = "esp8266"
    board.board_id = "ESP8266_GENERIC"
    fw = Firmware(
        board_id="ESP8266_GENERIC",
        version="stable",
        port="esp8266",
        firmware_file="esp8266/ESP8266_GENERIC-v1.26.0.bin",
    )
    task = FlashTask(board=board, firmware=fw)

    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.list.show_mcus")
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=[board])

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    m_clean.assert_called_once_with("ESP8266_GENERIC")
    m_build.assert_called_once()
    assert m_build.call_args.kwargs["force"] is True
    assert call_order == ["clean", "build"]
    assert m_flash_tasks.called


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
    # Patch flash_tasks to simulate flashing
    m_flash_tasks = mocker.patch("mpflash.cli_flash.flash_tasks", return_value=None)
    # Patch ask_missing_params to avoid user input
    m_ask_missing_params = mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    # Patch connected_ports_boards to simulate a connected board
    m_connected_ports_boards = mocker.patch(
        "mpflash.cli_flash.connected_ports_boards",
        return_value=(["esp32"], ["ESP32_GENERIC"], [MPRemoteBoard("COM99")]),
        autospec=True,
    )

    runner = CliRunner()
    args = ["flash", "--board", "ESP32_GENERIC", "--version", "1.24.1"]
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    # download should be triggered (since firmware was missing)
    m_download.assert_called()
    # flash_tasks should be called to proceed with flashing
    m_flash_tasks.assert_called_once()
    # CLI should succeed
    assert result.exit_code == 0
