import pytest

from mpflash.db.models import Board
from mpflash.mpboard_id import find_known_board, known_ports, known_stored_boards
from mpflash.mpboard_id.known import known_versions

pytestmark = [pytest.mark.mpflash]


def test_get_known_ports(session_fx):
    ports = known_ports()
    assert isinstance(ports, list)
    assert all(isinstance(port, str) for port in ports)


def test_known_versions(session_fx, mocker):
    """known_versions returns a list of version strings (covers lines 30-34)."""

    versions = known_versions("esp32")
    assert isinstance(versions, list)
    assert all(isinstance(v, str) for v in versions)


def test_known_versions_no_port(session_fx, mocker):
    """known_versions with no port returns all versions (covers the port='%%' branch)."""

    versions = known_versions()
    assert isinstance(versions, list)
    assert len(versions) > 0


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
def test_known_stored_boards_basic(port, versions, session_fx):
    l = known_stored_boards(port, versions)
    assert isinstance(l, list)
    assert all(isinstance(t, tuple) for t in l)
    assert all(isinstance(t[0], str) and isinstance(t[1], str) for t in l)
    # # TODO"check the version
    assert all("[stable]" not in t[0] for t in l)
    assert all("[preview]" not in t[0] for t in l)


def test_find_known_board(session_fx):
    board = find_known_board("PYBV11")
    assert isinstance(board, Board)
    assert board.board_id == "PYBV11"
    assert board.port == "stm32"


def test_find_known_board_with_port_esp8266(session_fx, mocker):
    """GENERIC board looked up with port='esp8266' should return the esp8266 board.

    In the board DB, GENERIC (plain) was always an esp8266 board (v1.18-v1.20).
    """

    board = find_known_board("GENERIC", port="esp8266")
    assert isinstance(board, Board)
    assert board.port == "esp8266"


def test_find_known_board_with_version(session_fx, mocker):
    """find_known_board with an exact version filter returns only that version's board."""

    board = find_known_board("PYBV11", version="v1.24.1")
    assert isinstance(board, Board)
    assert board.board_id == "PYBV11"
    assert board.version == "v1.24.1"


def test_find_known_board_alternate_name_with_version(session_fx, mocker):
    """Alternate-name lookup also respects the version filter (covers line 100)."""

    # GENERIC only exists in the DB for versions v1.18-v1.20 as esp8266.
    # With port='esp32' and a concrete version, the alternate-name path
    # (ESP32_GENERIC + version filter) must be exercised.
    board = find_known_board("GENERIC", port="esp32", version="v1.24.1")
    assert isinstance(board, Board)
    assert board.port == "esp32"


def test_find_known_board_alternate_name_no_port_with_version(session_fx, mocker):
    """Alternate-name loop without port but with version covers the 97->99 branch (if port: False)."""

    # No port given → the 'if port:' on line 97 is False, going directly to 'if version:' on line 99
    board = find_known_board("PICO", version="v1.24.1")
    assert isinstance(board, Board)
    assert board.board_id in ("RPI_PICO", "PICO")


def test_find_known_board_description_search_with_version(session_fx, mocker):
    """Description search with a version filter covers line 108-109."""

    # Pass an unknown board_id that matches a board description, with a specific version
    board = find_known_board("Generic ESP32 module with ESP32", version="v1.24.1")
    assert isinstance(board, Board)
    assert board.board_id == "ESP32_GENERIC"
    assert board.version == "v1.24.1"
    """find_known_board falls back to description search when board_id is not found (lines 107-114)."""

    # Pass the exact board description as the board_id to trigger the description-search fallback
    board = find_known_board("Generic ESP32 module with ESP32")
    assert isinstance(board, Board)
    assert board.board_id == "ESP32_GENERIC"


def test_find_known_board_by_description_with_port(session_fx, mocker):
    """Description search with a port filter returns the correct port-specific board (line 109-114)."""

    board = find_known_board("PYBv1.1 with STM32F405RG", port="stm32")
    assert isinstance(board, Board)
    assert board.port == "stm32"


def test_find_known_board_not_found_raises(session_fx, mocker):
    """find_known_board raises MPFlashError when no board can be found at all."""
    from mpflash.errors import MPFlashError

    with pytest.raises(MPFlashError):
        find_known_board("TOTALLY_UNKNOWN_BOARD_XYZ")


def test_find_known_board_last_resort_fallback(session_fx, mocker):
    """When board_id exists but its port doesn't match and no alternate resolves,
    find_known_board falls back to the first candidate (last-resort path, line 117-119)."""

    # GENERIC exists only as esp8266; requesting port='samd' has no alternate resolution,
    # so the last-resort candidate (esp8266) is returned.
    board = find_known_board("GENERIC", port="samd")
    assert isinstance(board, Board)
    # The board returned is the only candidate (esp8266 GENERIC)
    assert board.board_id == "GENERIC"
    """GENERIC board looked up with port='esp32' should resolve to an esp32 board.

    In the board DB, GENERIC (plain) only exists as an esp8266 board (v1.18-v1.20).
    ESP32 boards in that era used GENERIC_SPIRAM, GENERIC_OTA, etc.
    From v1.21.0 onward they were renamed to ESP32_GENERIC.

    When a user specifies --board GENERIC --port esp32 (as in the old v1.10 era),
    find_known_board must fall back to the ESP32_GENERIC alternate name so the
    correct esp32 port/MCU info is used instead of the esp8266 GENERIC entry.
    """

    # 'GENERIC' exists only as esp8266 in the DB; with port='esp32' the function
    # should fall back to 'ESP32_GENERIC' via alternate_board_names.
    board = find_known_board("GENERIC", port="esp32")
    assert isinstance(board, Board)
    assert board.port == "esp32", f"Expected esp32, got {board.port}"
