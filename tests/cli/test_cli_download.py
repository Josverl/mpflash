from pathlib import Path
from typing import List

import pytest
from click.testing import CliRunner
from unittest.mock import Mock
from pytest_mock import MockerFixture

# # module under test :
from mpflash import cli_main
from mpflash.common import DownloadParams
from mpflash.mpremoteboard import MPRemoteBoard

# mark all tests
pytestmark = pytest.mark.mpflash


##########################################################################################
# download


@pytest.mark.parametrize(
    "id, ex_code, args",
    [
        ("10", 0, ["download"]),
        ("30", 0, ["download", "--version", "1.22.0"]),
        ("31", 0, ["download", "--version", "stable"]),
        ("32", 0, ["download", "--version", "stable", "--version", "1.22.0"]),
        ("40", 0, ["download", "--board", "ESP32_GENERIC"]),
        ("41", 0, ["download", "--board", "?"]),
        ("42", 0, ["download", "--board", "?", "--board", "ESP32_GENERIC"]),
        ("43", 0, ["download", "--board", "ESP32_GENERIC", "--board", "?"]),
        ("60", 0, ["download", "--no-clean"]),
        ("61", 0, ["download", "--clean"]),
        ("62", 0, ["download", "--force"]),
    ],
)
def test_mpflash_download(id, ex_code, args: List[str], mocker: MockerFixture, session_fx):
    def fake_ask_missing_params(params: DownloadParams) -> DownloadParams:
        if "?" in params.ports:
            params.ports = ["esp32"]
        if "?" in params.boards:
            params.ports = ["esp32"]
            params.boards = ["ESP32_GENERIC"]
        if "?" in params.versions:
            params.versions = ["1.22.0"]
        return params

    m_connected_ports_boards = mocker.patch(
        "mpflash.connected.connected_ports_boards_variants",
        return_value=(["esp32"], ["ESP32_GENERIC"], [], [MPRemoteBoard("COM99")]),
        autospec=True,
    )
    m_download = mocker.patch("mpflash.download.download", return_value=None, autospec=True)
    m_ask_missing_params = mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    runner = CliRunner()
    result = runner.invoke(cli_main.cli, args, standalone_mode=True)
    assert result.exit_code == ex_code
    if "--board" not in args:
        m_connected_ports_boards.assert_called_once()
    m_ask_missing_params.assert_called_once()
    m_download.assert_called_once()

    assert m_download.call_args.args[1], "one or more ports should be specified for download"

    if "--clean" in args:
        assert m_download.call_args.kwargs["clean"] == True, "clean should be True"
    if "--no-clean" in args:
        assert m_download.call_args.kwargs["clean"] == False, "clean should be False"
    else:
        assert m_download.call_args.kwargs["clean"] == True, "clean should be True"

    if "--force" in args:
        assert m_download.call_args.kwargs["force"] == True, "force should be True"
    else:
        assert m_download.call_args.kwargs["force"] == False, "force should be False"

    # destination should be None when --dir is not specified
    assert m_download.call_args.kwargs.get("destination") is None, "destination should be None when --dir is not specified"


def test_mpflash_download_dir_option(mocker: MockerFixture, session_fx, tmp_path: Path):
    """Test that global --dir sets the shared firmware folder for download."""
    from mpflash.config import config

    def fake_ask_missing_params(params: DownloadParams) -> DownloadParams:
        return params

    mocker.patch(
        "mpflash.connected.connected_ports_boards_variants",
        return_value=(["esp32"], ["ESP32_GENERIC"], [], [MPRemoteBoard("COM99")]),
        autospec=True,
    )
    m_download = mocker.patch("mpflash.download.download", return_value=1, autospec=True)
    mocker.patch(
        "mpflash.ask_input.ask_missing_params",
        Mock(side_effect=fake_ask_missing_params),
    )
    old_folder = config._firmware_folder
    runner = CliRunner()
    try:
        result = runner.invoke(
            cli_main.cli,
            ["--dir", str(tmp_path), "download", "--board", "ESP32_GENERIC", "--version", "1.22.0"],
            standalone_mode=True,
        )
        assert result.exit_code == 0
        m_download.assert_called_once()
        assert config.firmware_folder == tmp_path.resolve()
        assert m_download.call_args.kwargs.get("destination") is None
    finally:
        config._firmware_folder = old_folder
