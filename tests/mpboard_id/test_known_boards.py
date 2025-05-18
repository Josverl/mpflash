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
