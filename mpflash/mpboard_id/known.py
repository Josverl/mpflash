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


def known_ports(version: str = "") -> list[str]:
    """Return a list of known ports for a given version."""
    version = clean_version(version) if version else "%%"
    with Session() as session:
        qry = text("SELECT distinct port FROM boards WHERE version like :version ORDER BY port;")
        ports = session.execute(qry, {"version": version}).columns("port").fetchall()
    return [row.port for row in ports]


def known_versions(port: str = "") -> list[str]:
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

    boards = set({(f"{board.version} {board.board_id:<30} {board.description}", board.board_id) for board in mp_boards})
    return sorted(list(boards))


def find_known_board(board_id: str, version="", port="") -> Board:
    """
    Find the board for the given BOARD_ID or 'board description'.
    If a port is provided, prefer boards matching that port.
    If the board_id is not found, it will try alternate names (e.g. GENERIC → ESP32_GENERIC).
    If the board_id contains an @, it will split it and use the first part as the board_id.

    Returns the board info as a Board object.
    """
    from mpflash.mpboard_id.alternate import alternate_board_names

    lookup_id = board_id.split("@")[0]
    with Session() as session:
        qry = session.query(Board).filter(Board.board_id == lookup_id)
        if version:
            qry = qry.filter(Board.version == version)
        candidates = qry.all()
        if candidates:
            if port:
                # Prefer the board whose port matches the user-specified port
                matching = [b for b in candidates if b.port == port]
                if matching:
                    return matching[0]
                # No port match among candidates - fall through to alternate name lookup
            else:
                return candidates[0]

        # Try alternate names (e.g. GENERIC → ESP32_GENERIC when port="esp32")
        alt_names = alternate_board_names(lookup_id, port)
        for alt_id in alt_names[1:]:  # skip the first (already tried above)
            qry = session.query(Board).filter(Board.board_id == alt_id)
            if port:
                qry = qry.filter(Board.port == port)
            if version:
                qry = qry.filter(Board.version == version)
            board = qry.first()
            if board:
                log.debug(f"Resolved board {board_id!r} → {alt_id!r} (port={board.port})")
                return board

        # Fall back to description search
        qry = session.query(Board).filter(Board.description == lookup_id)
        if version:
            qry = qry.filter(Board.version == version)
        if port:
            qry = qry.filter(Board.port == port)
        board = qry.first()
        if board:
            return board

        # Last resort: return first candidate ignoring port mismatch
        if candidates:
            log.warning(f"Board {board_id!r} not found for port {port!r}; falling back to {candidates[0].port!r} board from earlier match")
            return candidates[0]

    raise MPFlashError(f"Board {board_id} not found")
