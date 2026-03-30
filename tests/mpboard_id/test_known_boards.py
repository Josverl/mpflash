import pytest

from mpflash.db.models import Board
from mpflash.mpboard_id import find_known_board, known_ports, known_stored_boards

pytestmark = [pytest.mark.mpflash]


def test_get_known_ports(session_fx, mocker):
    mocker.patch("mpflash.mpboard_id.known.Session", session_fx)

    ports = known_ports()
    assert isinstance(ports, list)
    assert all(isinstance(port, str) for port in ports)


@pytest.mark.parametrize(
    "port, versions",
    [
        ("rp2", ["1.20.0"]),
        ("rp2", ["1.20.0", "1.17.3"]),
        ("rp2", ["preview"]),
        ("rp2", ["stable"]),
        ("rp2", None),
    ],
)
def test_known_stored_boards_basic(port, versions, session_fx, mocker):
    mocker.patch("mpflash.mpboard_id.known.Session", session_fx)
    l = known_stored_boards(port, versions)
    assert isinstance(l, list)
    assert all(isinstance(t, tuple) for t in l)
    assert all(isinstance(t[0], str) and isinstance(t[1], str) for t in l)
    # # TODO"check the version
    assert all("[stable]" not in t[0] for t in l)
    assert all("[preview]" not in t[0] for t in l)


def test_find_known_board(session_fx, mocker):
    mocker.patch("mpflash.mpboard_id.known.Session", session_fx)
    board = find_known_board("PYBV11")
    assert isinstance(board, Board)
    assert board.board_id == "PYBV11"
    assert board.port == "stm32"


def test_find_known_board_with_port_esp8266(session_fx, mocker):
    """GENERIC board looked up with port='esp8266' should return the esp8266 board.

    In the board DB, GENERIC (plain) was always an esp8266 board (v1.18-v1.20).
    """
    mocker.patch("mpflash.mpboard_id.known.Session", session_fx)
    board = find_known_board("GENERIC", port="esp8266")
    assert isinstance(board, Board)
    assert board.port == "esp8266"


def test_find_known_board_generic_prefers_esp32_when_port_esp32(session_fx, mocker):
    """GENERIC board looked up with port='esp32' should resolve to an esp32 board.

    In the board DB, GENERIC (plain) only exists as an esp8266 board (v1.18-v1.20).
    ESP32 boards in that era used GENERIC_SPIRAM, GENERIC_OTA, etc.
    From v1.21.0 onward they were renamed to ESP32_GENERIC.

    When a user specifies --board GENERIC --port esp32 (as in the old v1.10 era),
    find_known_board must fall back to the ESP32_GENERIC alternate name so the
    correct esp32 port/MCU info is used instead of the esp8266 GENERIC entry.
    """
    mocker.patch("mpflash.mpboard_id.known.Session", session_fx)
    # 'GENERIC' exists only as esp8266 in the DB; with port='esp32' the function
    # should fall back to 'ESP32_GENERIC' via alternate_board_names.
    board = find_known_board("GENERIC", port="esp32")
    assert isinstance(board, Board)
    assert board.port == "esp32", f"Expected esp32, got {board.port}"
