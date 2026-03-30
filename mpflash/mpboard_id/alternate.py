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
        # Determine the suffix after "GENERIC" (e.g. "_SPIRAM", "_OTA", "")
        suffix = board_id[len("GENERIC"):]
        if port:
            underscore_name = board_id.replace("GENERIC", f"{port.upper()}_GENERIC")
            more.append(underscore_name)
            # Also add the hyphen form: GENERIC_X → PORT_GENERIC-X
            # This handles the v1.20.0→v1.21.0 renaming where board variants switched from
            # underscore to hyphen (e.g. GENERIC_SPIRAM → ESP32_GENERIC-SPIRAM,
            # GENERIC_OTA → ESP32_GENERIC-OTA, GENERIC_D2WD → ESP32_GENERIC-D2WD).
            if suffix.startswith("_"):
                hyphen_name = f"{port.upper()}_GENERIC{suffix.replace('_', '-', 1)}"
                if hyphen_name not in more:
                    more.append(hyphen_name)
        else:
            # No port given – add both ESP32 and ESP8266 underscore and hyphen variants
            for prefix in ("ESP32", "ESP8266"):
                more.append(board_id.replace("GENERIC", f"{prefix}_GENERIC"))
                if suffix.startswith("_"):
                    more.append(f"{prefix}_GENERIC{suffix.replace('_', '-', 1)}")
    elif board_id.startswith("ESP32_"):
        more.append(board_id.replace("ESP32_", ""))
    elif board_id.startswith("ESP8266_"):
        more.append(board_id.replace("ESP8266_", ""))

    # VARIANT: strip known variant suffixes to also search for the base board
    variant_suffixes = ["SPIRAM", "THREAD"]
    for board in more:
        if any(suffix in board for suffix in variant_suffixes):
            for suffix in variant_suffixes:
                if board.endswith(f"_{suffix}"):
                    more.append(board.replace(f"_{suffix}", ""))
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
