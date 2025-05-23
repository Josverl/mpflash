from typing import Dict, List, Optional

from loguru import logger as log


def alternate_board_names(board_id, port="") -> List[str]:
    more = [board_id]

    log.debug("try for renamed board_id")

    if board_id.startswith("PICO"):
        more.append(board_id.replace("PICO", "RPI_PICO"))
    elif board_id.startswith("RPI_"):
        more.append(board_id.replace("RPI_", ""))
    elif board_id.startswith("GENERIC"):
        if port:
            more.append(board_id.replace("GENERIC", f"{port.upper()}_GENERIC"))
        else:
            # just add both of them
            more.append(board_id.replace("GENERIC", f"ESP32_GENERIC"))
            more.append(board_id.replace("GENERIC", f"ESP8266_GENERIC"))
    elif board_id.startswith("ESP32_"):
        more.append(board_id.replace("ESP32_", ""))
    elif board_id.startswith("ESP8266_"):
        more.append(board_id.replace("ESP8266_", ""))

    # VARIANT
    variant_suffixes = ["SPIRAM", "THREAD"]
    for board in more:
        if any(suffix in board for suffix in variant_suffixes):
            for suffix in variant_suffixes:
                if board.endswith(f"_{suffix}"):
                    more.append(board.replace(f"_{suffix}", ""))
                    # more.append(board.replace(f"_{suffix}", f"-{suffix}"))
                    break  # first one found

    return more


def add_renamed_boards(boards: List[str]) -> List[str]:
    """
    Adds the renamed boards to the list of boards.

    Args:
        boards : The list of boards to add the renamed boards to.

    Returns:
        List[str]: The list of boards with the renamed boards added.
    """

    _boards = boards.copy()
    for board in boards:
        _boards.extend(alternate_board_names(board))
        if board != board.upper():
            _boards.extend(alternate_board_names(board.upper()))
    return _boards
