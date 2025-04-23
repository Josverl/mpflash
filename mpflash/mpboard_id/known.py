"""
KNOWN ports and boards are sourced from the micropython repo,
this info is stored in the board_info.json file
and is used to identify the board and port for flashing.
This module provides access to the board info and the known ports and boards."""

from functools import lru_cache
from typing import List, Optional, Tuple

from mpflash.db.boards import find_board_id, find_board_info
from mpflash.errors import MPFlashError
from mpflash.versions import clean_version
from mpflash.logger import log
from mpflash.db import query

from .board import Board



def get_known_ports(version:str = "" ) -> List[str]:
    version = clean_version(version) if version  else "%"
    qry = f"SELECT distinct port FROM boards WHERE version like '{version}' ORDER BY port;"
    rows = query(qry)
    ports = [row["port"] for row in rows]
    return ports


def get_known_boards_for_port(port: Optional[str] = "", versions: Optional[List[str]] = None) -> List[Board]:
    """
    Returns a list of boards for the given port and version(s)

    port: The Micropython port to filter for
    versions:  Optional, The Micropython versions to filter for (actual versions required)
    """
    versions = [ clean_version(v) for v in versions ] if versions else []
    # build query to get the boards for the given port and version(s)
    qry = "SELECT * FROM board_downloaded WHERE true"
    if versions:
        qry += f" AND version in {str(tuple(versions)).replace(',)', ')')}"
    if port:
        qry += f" AND port = '{port}'"
    qry += "ORDER BY port, board_id" 

    rows = query(qry)
    mp_boards = [Board.from_dict(dict(row)) for row in rows]
    return mp_boards


def known_stored_boards(port: str, versions: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """
    Returns a list of tuples with the description and board name for the given port and version

    port : str : The Micropython port to filter for
    versions : List[str] : The Micropython versions to filter for (actual versions required)
    """
    mp_boards = get_known_boards_for_port(port, versions)

    boards = set({(f"{board.version} {board.description}", board.board_id) for board in mp_boards})
    return sorted(list(boards))


@lru_cache(maxsize=20)
def find_known_board(board_id: str, version="") -> Board:
    """Find the board for the given BOARD_ID or 'board description' and return the board info as a Board object"""
    # Some functional overlap with:
    # mpboard_id\board_id.py _find_board_id_by_description
    # TODO: Refactor to search the SQLite DB instead of the JSON file
    board_ids = find_board_id(board_id=board_id, version=version or "%")
    boards = []
    for board_id in board_ids:
        # if we have a board_id, use it to find the board info
        boards += [Board.from_dict(dict(r)) for r in find_board_info(board_id=board_id)]

    if boards:
        return boards[0]
    raise MPFlashError(f"Board {board_id} not found")
