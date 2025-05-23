from logging import log
from mpflash.common import Params
from mpflash.mpboard_id import find_known_board


def resolve_board_ids(params: Params):
    """Resolve board descriptions to board_id, and remove empty strings from list of boards"""
    for board_id in params.boards:
        if board_id == "":
            params.boards.remove(board_id)
            continue
        if " " in board_id:
            try:
                if info := find_known_board(board_id):
                    log.info(f"Resolved board description: {info.board_id}")
                    params.boards.remove(board_id)
                    params.boards.append(info.board_id)
            except Exception as e:
                log.warning(f"Unable to resolve board description: {e}")
