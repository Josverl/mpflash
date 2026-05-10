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
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=None, autospec=True)  # type: ignore
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


def test_mpflash_flash_direct_file_infers_esp32_board_variant(mocker: MockerFixture, tmp_path):
    """Flash directly from --file and infer esp32 board+variant from build path."""
    fw_path = tmp_path / "micropython" / "ports" / "esp32" / "build-ESP32_GENERIC-SPIRAM" / "micropython.bin"
    fw_path.parent.mkdir(parents=True, exist_ok=True)
    fw_path.write_bytes(b"firmware")
    args = ["flash", "--version", "1.27.0", "--serial", "COM8", "--file", str(fw_path)]

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    mocker.patch("mpflash.cli_flash.filtered_comports", return_value=["COM8"])
    board = MPRemoteBoard("COM8")
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC-SPIRAM"
    task = FlashTask(board=board, firmware=None)
    m_create_worklist = mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=[board])
    m_ensure = mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.list.show_mcus")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    assert m_create_worklist.call_args.kwargs["board_id"] == "ESP32_GENERIC-SPIRAM"
    assert m_create_worklist.call_args.kwargs["port"] == "esp32"
    flashed_task = m_flash_tasks.call_args.args[0][0]
    assert flashed_task.firmware.firmware_file == fw_path.as_posix()
    m_ensure.assert_not_called()


def test_mpflash_flash_direct_file_prompts_when_esp32_variant_unclear(mocker: MockerFixture, tmp_path):
    """If esp32 variant cannot be inferred from file path, ask for board selection."""
    fw_path = tmp_path / "micropython" / "ports" / "esp32" / "micropython.bin"
    fw_path.parent.mkdir(parents=True, exist_ok=True)
    fw_path.write_bytes(b"firmware")
    args = ["flash", "--version", "1.27.0", "--serial", "COM8", "--file", str(fw_path)]

    observed = {}

    def _fake_ask(params):
        observed["boards_before_prompt"] = list(params.boards)
        params.boards = ["ESP32_GENERIC"]
        params.variant = "SPIRAM"
        params.ports = ["esp32"]
        return params

    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=_fake_ask),
    )
    mocker.patch("mpflash.cli_flash.filtered_comports", return_value=["COM8"])
    board = MPRemoteBoard("COM8")
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC-SPIRAM"
    task = FlashTask(board=board, firmware=None)
    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    mocker.patch("mpflash.flash.flash_tasks", return_value=[board])
    mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.list.show_mcus")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    assert observed["boards_before_prompt"] == ["?"]


def test_mpflash_flash_direct_url_downloads_firmware(mocker: MockerFixture):
    """Download firmware via --url and flash directly without DB download step."""
    args = [
        "flash",
        "--version",
        "1.27.0",
        "--board",
        "ESP32_GENERIC",
        "--serial",
        "COM8",
        "--url",
        "https://example.com/micropython.bin",
    ]

    class _Response:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield b"1234"

    mocker.patch("mpflash.ask_input.ask_missing_params", Mock(side_effect=fake_ask_missing_params))
    mocker.patch("requests.get", return_value=_Response())
    mocker.patch("mpflash.cli_flash.filtered_comports", return_value=["COM8"])
    board = MPRemoteBoard("COM8")
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC"
    task = FlashTask(board=board, firmware=None)
    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", return_value=[board])
    m_ensure = mocker.patch("mpflash.download.jid.ensure_firmware_downloaded_tasks")
    mocker.patch("mpflash.list.show_mcus")

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 0
    flashed_firmware_path = Path(m_flash_tasks.call_args.args[0][0].firmware.firmware_file)
    assert flashed_firmware_path.name.startswith("mpflash-fw-")
    assert not flashed_firmware_path.exists()
    m_ensure.assert_not_called()


def test_mpflash_flash_direct_url_cleans_temp_file_on_flash_error(mocker: MockerFixture):
    """Cleanup temp URL firmware file even when flashing fails."""
    args = [
        "flash",
        "--version",
        "1.27.0",
        "--board",
        "ESP32_GENERIC",
        "--serial",
        "COM8",
        "--url",
        "https://example.com/micropython.bin",
    ]

    class _Response:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=0):
            yield b"1234"

    mocker.patch("mpflash.ask_input.ask_missing_params", Mock(side_effect=fake_ask_missing_params))
    mocker.patch("requests.get", return_value=_Response())
    mocker.patch("mpflash.cli_flash.filtered_comports", return_value=["COM8"])
    board = MPRemoteBoard("COM8")
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC"
    task = FlashTask(board=board, firmware=None)
    mocker.patch("mpflash.flash.worklist.create_worklist", return_value=[task])
    m_flash_tasks = mocker.patch("mpflash.flash.flash_tasks", side_effect=RuntimeError("boom"))

    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)

    assert result.exit_code == 1
    flashed_firmware_path = Path(m_flash_tasks.call_args.args[0][0].firmware.firmware_file)
    assert not flashed_firmware_path.exists()

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
