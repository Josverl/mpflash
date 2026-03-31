from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from mpflash.ask_input import _split_board_variant, ask_missing_params, filter_matching_boards
from mpflash.common import DownloadParams, FlashParams
from mpflash.config import MPFlashConfig
from pytest_mock import MockerFixture

pytestmark = [pytest.mark.mpflash]


def test_ask_missing_params_no_interactivity(mocker: MockerFixture):
    # Make sure that no prompts are called when interactive is False

    _config = MPFlashConfig()
    _config.interactive = False

    input = {
        "versions": ["?"],
        "boards": ["?"],
        "clean": True,
        "force": False,
    }
    params = DownloadParams(**input)
    mocker.patch("mpflash.ask_input.config", _config)
    result = ask_missing_params(params)
    # Should return original params without modification (no prompts called)
    assert result is params


@pytest.mark.parametrize(
    "id, download, input, serial_return, versions_return, port_boards_variant_return, check",
    [
        (
            "10 D -v ? -b ?",
            True,
            {
                "versions": ["?"],
                "boards": ["?"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "clean": True,
                "force": False,
            },
            None,  # ask_serialport not called for download
            ["1.14.0"],  # ask_mp_version return
            ("esp32", ["OTHER_BOARD"], ""),  # ask_port_board_variant return (port, boards, variant)
            {
                "versions": ["1.14.0"],
                "boards": ["OTHER_BOARD"],
            },
        ),
        (
            "11 D -v ? -b ? -b SEEED_WIO_TERMINAL",
            True,
            {
                "versions": ["?"],
                "boards": ["?", "SEEED_WIO_TERMINAL"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "clean": True,
                "force": False,
            },
            None,
            ["1.14.0"],
            ("esp32", ["OTHER_BOARD"], ""),
            {
                "versions": ["1.14.0"],
                "boards": ["OTHER_BOARD", "SEEED_WIO_TERMINAL"],
            },
        ),
        (
            "20 D select version",
            True,
            {
                "versions": ["?"],
                "boards": ["SEEED_WIO_TERMINAL"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "clean": True,
                "force": False,
            },
            None,
            ["1.22.0"],
            None,  # ask_port_board_variant not called (boards already set)
            {"versions": ["1.22.0"]},
        ),
        # versions as string
        (
            "21 D version string",
            True,
            {
                "versions": ["preview"],
                "boards": ["?"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "clean": True,
                "force": False,
            },
            None,
            None,  # ask_mp_version not called (versions already set)
            ("esp32", ["SEEED_WIO_TERMINAL"], ""),
            {"versions": ["preview"]},
        ),
        (
            "22 D -v preview -v ?",
            True,
            {
                "versions": ["preview", "?"],
                "boards": ["SEEED_WIO_TERMINAL"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "clean": True,
                "force": False,
            },
            None,
            "1.14.0",  # string return (not list)
            None,  # ask_port_board_variant not called
            {"versions": ["preview", "1.14.0"]},
        ),
        (
            "30 D no boards",
            True,
            {
                "versions": ["stable"],
                "boards": [],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "clean": True,
                "force": False,
            },
            None,
            None,  # ask_mp_version not called
            ("esp32", ["SEEED_WIO_TERMINAL", "FAKE_BOARD"], ""),
            {
                # "versions": ["stable"]
            },
        ),
        # flash — variant empty
        (
            "50 F -b ? -v preview",
            False,
            {
                "versions": ["preview"],
                "boards": ["?"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "serial": [],
                "erase": True,
                "bootloader": True,
                "cpu": "",
            },
            "COM4",
            None,  # ask_mp_version not called
            ("esp32", ["SEEED_WIO_TERMINAL"], ""),
            {},
        ),
        # flash — variant set
        (
            "51 F -b ? -v preview with variant",
            False,
            {
                "versions": ["preview"],
                "boards": ["?"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "serial": [],
                "erase": True,
                "bootloader": True,
                "cpu": "",
            },
            "COM4",
            None,
            ("esp32", ["ESP32_GENERIC"], "SPIRAM"),  # variant returned
            {"variant": "SPIRAM"},
        ),
        # Check that the port description is trimmed
        (
            "60 F -b ? -v preview",
            False,
            {
                "versions": ["preview"],
                "boards": ["?"],
                "fw_folder": Path("C:/Users/josverl/Downloads/firmware"),
                "serial": [],
                "erase": True,
                "bootloader": True,
                "cpu": "",
            },
            "COM4 Manufacturer Description",
            None,  # ask_mp_version not called
            ("esp32", ["SEEED_WIO_TERMINAL"], ""),
            {
                "serial": ["COM4"],
            },
        ),
    ],
)
@pytest.mark.xfail(reason="Cant get test to work in CI :-(")
def test_ask_missing_params_with_interactivity(
    id: str,
    download: bool,
    input: dict,
    serial_return,
    versions_return,
    port_boards_variant_return,
    check: dict,
    mocker: MockerFixture,
):
    if download:
        params = DownloadParams(**input)
    else:
        params = FlashParams(**input)

    # make sure we can be interactive during testing, even in CI
    _config = MPFlashConfig()
    _config.interactive = True
    mocker.patch("mpflash.ask_input.config", _config)

    # Mock each helper function individually
    m_serialport: Mock = mocker.patch("mpflash.ask_input.ask_serialport", return_value=serial_return)
    m_mp_version: Mock = mocker.patch("mpflash.ask_input.ask_mp_version", return_value=versions_return)
    if port_boards_variant_return is not None:
        m_port_board_variant: Mock = mocker.patch(
            "mpflash.ask_input.ask_port_board_variant",
            return_value=port_boards_variant_return,
        )
    else:
        m_port_board_variant = mocker.patch(
            "mpflash.ask_input.ask_port_board_variant",
            return_value=(None, None, None),
        )

    result = ask_missing_params(params)

    # Verify helpers were called as expected
    if not download and (not input.get("serial") or "?" in (input.get("serial") or [])):
        m_serialport.assert_called_once()
    else:
        m_serialport.assert_not_called()

    if input.get("versions") == [] or "?" in (input.get("versions") or []):
        m_mp_version.assert_called_once()

    boards_need_asking = not input.get("boards") or "?" in (input.get("boards") or [])
    if boards_need_asking and port_boards_variant_return is not None:
        m_port_board_variant.assert_called_once()
    elif not boards_need_asking:
        m_port_board_variant.assert_not_called()

    # explicit checks
    for key in check:
        if isinstance(check[key], list):
            assert getattr(result, key), f"{key} should be in result"
            assert sorted(getattr(result, key)) == sorted(check[key])
        else:
            assert getattr(result, key) == check[key]


# ---------------------------------------------------------------------------
# Unit tests for _split_board_variant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "board_id, expected_board, expected_variant",
    [
        ("ESP32_GENERIC-SPIRAM", "ESP32_GENERIC", "SPIRAM"),
        ("ESP32_GENERIC-OTA", "ESP32_GENERIC", "OTA"),
        ("PYBV10-dp-thread", "PYBV10", "dp-thread"),     # variant with hyphen
        ("ESP32_GENERIC", "ESP32_GENERIC", ""),            # no variant
        ("PICO_W", "PICO_W", ""),                          # underscores only
        ("ESP32_GENERIC_S3-SPIRAM_OCT", "ESP32_GENERIC_S3", "SPIRAM_OCT"),
    ],
)
def test_split_board_variant(board_id: str, expected_board: str, expected_variant: str):
    """Test that board_id is correctly split into base board and variant."""
    board, variant = _split_board_variant(board_id)
    assert board == expected_board
    assert variant == expected_variant

@pytest.mark.parametrize(
    "port, versions, expected_fallback",
    [
        ("rp2", ["stable"], True),  # Should fallback to previous stable versions
        ("rp2", ["preview"], True),  # Should fallback to preview and recent stable
        ("esp32", ["v1.26.1"], True),  # Should fallback for specific new version
        ("stm32", ["v1.20.0"], False),  # Should find boards (assuming this version exists in DB)
    ],
)
def test_filter_matching_boards_fallback(port: str, versions: list, expected_fallback: bool, mocker: MockerFixture, session_fx):
    """Test that filter_matching_boards falls back to previous versions when no boards found."""

    # Mock the dependencies
    mock_micropython_versions = mocker.patch("mpflash.ask_input.micropython_versions")
    mock_micropython_versions.return_value = [
        "v1.20.0",
        "v1.21.0",
        "v1.22.0",
        "v1.23.0",
        "v1.24.0",
        "v1.25.0",
        "v1.26.0",
        "v1.26.1",
        "v1.27.0-preview",
    ]

    mock_known_stored_boards = mocker.patch("mpflash.ask_input.known_stored_boards")

    if expected_fallback:
        # First call returns empty (simulating no boards for new version)
        # Second call returns some boards (simulating fallback success)
        mock_known_stored_boards.side_effect = [
            [],  # No boards found for requested version
            [("v1.25.0 PICO_W                          Raspberry Pi Pico W", "PICO_W")],  # Fallback boards
        ]
    else:
        # Single call returns boards (no fallback needed)
        mock_known_stored_boards.return_value = [("v1.20.0 PICO                            Raspberry Pi Pico", "PICO")]

    answers = {"port": port, "versions": versions}

    result = filter_matching_boards(answers)

    # Should always return some boards (either original or fallback)
    assert len(result) > 0
    assert all(isinstance(item, tuple) and len(item) == 2 for item in result)

    if expected_fallback:
        # Should have called known_stored_boards twice (original + fallback)
        assert mock_known_stored_boards.call_count == 2
        # First call with original versions
        first_call_versions = mock_known_stored_boards.call_args_list[0][0][1]
        # Second call should have different (fallback) versions
        second_call_versions = mock_known_stored_boards.call_args_list[1][0][1]
        assert first_call_versions != second_call_versions
    else:
        # Should have called known_stored_boards only once
        assert mock_known_stored_boards.call_count == 1


def test_filter_matching_boards_stable_version_mapping(mocker: MockerFixture):
    """Test that 'stable' is correctly mapped to the latest stable version."""

    mock_micropython_versions = mocker.patch("mpflash.ask_input.micropython_versions")
    mock_micropython_versions.return_value = ["v1.24.0", "v1.25.0", "v1.26.0", "v1.26.1", "v1.27.0-preview"]

    mock_known_stored_boards = mocker.patch("mpflash.ask_input.known_stored_boards")
    mock_known_stored_boards.return_value = [("v1.26.0 PICO                            Raspberry Pi Pico", "PICO")]

    answers = {"port": "rp2", "versions": ["stable"]}

    result = filter_matching_boards(answers)

    # Should call with the latest stable version (v1.26.1 - second to last in the list)
    mock_known_stored_boards.assert_called()
    called_versions = mock_known_stored_boards.call_args[0][1]
    assert "v1.26.1" in called_versions


def test_filter_matching_boards_preview_version_mapping(mocker: MockerFixture):
    """Test that 'preview' is correctly mapped to preview and stable versions."""

    mock_micropython_versions = mocker.patch("mpflash.ask_input.micropython_versions")
    mock_micropython_versions.return_value = ["v1.24.0", "v1.25.0", "v1.26.0", "v1.26.1", "v1.27.0-preview"]

    mock_known_stored_boards = mocker.patch("mpflash.ask_input.known_stored_boards")
    mock_known_stored_boards.return_value = [("v1.27.0-preview PICO                    Raspberry Pi Pico", "PICO")]

    answers = {"port": "rp2", "versions": ["preview"]}

    result = filter_matching_boards(answers)

    # Should call with both preview and latest stable
    mock_known_stored_boards.assert_called()
    called_versions = mock_known_stored_boards.call_args[0][1]
    assert "v1.27.0-preview" in called_versions  # latest preview
    assert "v1.26.1" in called_versions  # latest stable


def test_filter_matching_boards_no_fallback_success(mocker: MockerFixture):
    """Test behavior when both original and fallback fail to find boards."""

    mock_micropython_versions = mocker.patch("mpflash.ask_input.micropython_versions")
    mock_micropython_versions.return_value = ["v1.26.0", "v1.26.1", "v1.27.0-preview"]

    mock_known_stored_boards = mocker.patch("mpflash.ask_input.known_stored_boards")
    mock_known_stored_boards.return_value = []  # Always return empty

    answers = {"port": "unknown_port", "versions": ["v1.26.1"]}

    result = filter_matching_boards(answers)

    # Should return a "No boards found" message
    assert len(result) == 1
    assert "No unknown_port boards found" in result[0][0]
    assert result[0][1] == ""
