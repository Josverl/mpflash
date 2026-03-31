"""
KNOWN ports and boards are sourced from the micropython repo,
this info is stored in the board_info.json file
and is used to identify the board and port for flashing.
This module provides access to the board info and the known ports and boards."""

from typing import List, Optional, Tuple

from mpflash.errors import MPFlashError
from mpflash.logger import log
from mpflash.versions import clean_version

from mpflash.db.models import Board, database


def known_ports(version: str = "") -> list[str]:
    """Return a list of known ports for a given version."""
    version = clean_version(version) if version else "%%"
    rows = database.execute_sql(
        "SELECT DISTINCT port FROM boards WHERE version LIKE ? ORDER BY port;",
        (version,),
    ).fetchall()
    return [row[0] for row in rows]


def known_versions(port: str = "") -> list[str]:
    """Return a list of known versions for a given port."""
    port = port.strip() if port else "%%"
    rows = database.execute_sql(
        "SELECT DISTINCT version FROM boards WHERE port LIKE ? ORDER BY version;",
        (port,),
    ).fetchall()
    return [row[0] for row in rows]


def get_known_boards_for_port(port: str = "", versions: List[str] = []):
    """
    Returns a list of boards for the given port and version(s)

    port: The Micropython port to filter for
    versions:  Optional, The Micropython versions to filter for (actual versions required)
    """
    versions = [clean_version(v) for v in versions] if versions else []
    qry = Board.select().where(Board.port**port)  # ** is LIKE in Peewee
    if versions:
        qry = qry.where(Board.version.in_(versions))
    return list(qry)


def known_stored_boards(port: str, versions: List[str] = []) -> List[Tuple[str, str]]:
    """
    Returns a list of tuples with the description and board name for the given port and version

    port : str : The Micropython port to filter for
    versions : List[str] : The Micropython versions to filter for (actual versions required)
    """
    mp_boards = get_known_boards_for_port(port, versions)

    boards = set({(f"{board.version} {board.board_id:<30} {board.description}", board.board_id) for board in mp_boards})
    return sorted(list(boards))


def known_board_variants_dict(port: str, versions: List[str] = []) -> dict:
    """
    Build a ``{board_id: variant_hint}`` dict for all boards matching port+versions.

    The dict is designed for use with ``richui.Richui().input(completion=dict)``.
    Keys are full board_ids in ``board[-variant]`` format (e.g. ``ESP32_GENERIC-SPIRAM``);
    values are the variant part shown as a hint (e.g. ``SPIRAM``), or an empty string
    for boards without a variant.

    Args:
        port: MicroPython port to filter for (e.g. ``esp32``).
        versions: Actual version strings to filter for (cleaned).

    Returns:
        Ordered dict mapping board_id → variant hint string.
    """
    mp_boards = get_known_boards_for_port(port, versions)
    seen: dict = {}
    for board in sorted(mp_boards, key=lambda b: b.board_id):
        if board.board_id not in seen:
            seen[board.board_id] = board.variant or ""
    return seen


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

    qry = Board.select().where(Board.board_id == lookup_id)
    if version:
        qry = qry.where(Board.version == version)
    candidates = list(qry)
    if candidates:
        if port:
            # Prefer the board whose port matches the user-specified port
            matching = [b for b in candidates if b.port == port]
            if matching:
                return matching[0]
            # No port match among candidates — fall through to alternate name lookup
        else:
            return candidates[0]

    # Try alternate names (e.g. GENERIC → ESP32_GENERIC when port="esp32")
    alt_names = alternate_board_names(lookup_id, port)
    for alt_id in alt_names[1:]:  # skip the first (already tried above)
        qry = Board.select().where(Board.board_id == alt_id)
        if port:
            qry = qry.where(Board.port == port)
        if version:
            qry = qry.where(Board.version == version)
        board = qry.first()
        if board:
            log.debug(f"Resolved board {board_id!r} → {alt_id!r} (port={board.port})")
            return board

    # Fall back to description search
    qry = Board.select().where(Board.description == lookup_id)
    if version:
        qry = qry.where(Board.version == version)
    if port:
        qry = qry.where(Board.port == port)
    board = qry.first()
    if board:
        return board

    # Last resort: return first candidate ignoring port mismatch
    if candidates:
        log.warning(f"Board {board_id!r} not found for port {port!r}; falling back to {candidates[0].port!r} board from earlier match")
        return candidates[0]

    raise MPFlashError(f"Board {board_id} not found")
