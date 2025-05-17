"""
KNOWN ports and boards are sourced from the micropython repo,
this info is stored in the board_info.json file
and is used to identify the board and port for flashing.
This module provides access to the board info and the known ports and boards."""

from functools import lru_cache
from typing import List, Optional, Tuple

from sqlalchemy import text

from mpflash.db.core import Session
from mpflash.db.models import Board
from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.versions import clean_version


def known_ports(version: str | None = None) -> list[str]:
    """Return a list of known ports for a given version."""
    version = clean_version(version) if version else "%%"
    with Session() as session:
        qry = text("SELECT distinct port FROM boards WHERE version like :version ORDER BY port;")
        ports = session.execute(qry, {"version": version}).columns("port").fetchall()
    return [row.port for row in ports]


def known_versions(port: str | None = None) -> list[str]:
    """Return a list of known versions for a given port."""
    port = port.strip() if port else "%%"
    with Session() as session:
        qry = text("SELECT distinct version FROM boards WHERE port like :port ORDER BY version;")
        versions = session.execute(qry, {"port": port}).columns("version").fetchall()
    return [row.version for row in versions]


def get_known_boards_for_port(port: str = "", versions: List[str] = []):
    """
    Returns a list of boards for the given port and version(s)

    port: The Micropython port to filter for
    versions:  Optional, The Micropython versions to filter for (actual versions required)
    """
    versions = [clean_version(v) for v in versions] if versions else []
    with Session() as session:
        qry = session.query(Board).filter(Board.port.like(port))
        if versions:
            qry = qry.filter(Board.version.in_(versions))
        boards = qry.all()
        return boards


def known_stored_boards(port: str, versions: List[str] = []) -> List[Tuple[str, str]]:
    """
    Returns a list of tuples with the description and board name for the given port and version

    port : str : The Micropython port to filter for
    versions : List[str] : The Micropython versions to filter for (actual versions required)
    """
    mp_boards = get_known_boards_for_port(port, versions)

    boards = set({(f"{board.version} {board.description}", board.board_id) for board in mp_boards})
    return sorted(list(boards))


def find_known_board(board_id: str, version="") -> Board:
    """Find the board for the given BOARD_ID or 'board description' and return the board info as a Board object"""
    with Session() as session:
        qry = session.query(Board).filter(Board.board_id == board_id)
        if version:
            qry = qry.filter(Board.version == version)
        board = qry.first()
        if not board:
            # if no board found, try to find it by description
            qry = session.query(Board).filter(Board.description == board_id)
            if version:
                qry = qry.filter(Board.version == version)
        if board:
            return board
    raise MPFlashError(f"Board {board_id} not found")
