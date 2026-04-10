"""Access to MicroPython board metadata stored in the SQLite database.

This package exposes helpers to query known ports, boards, and variants.
"""
from mpflash.errors import MPFlashError
from mpflash.versions import clean_version

from .known import (find_known_board, get_known_boards_for_port, known_board_variants_dict,
                    known_ports, known_stored_boards)
from .resolve import resolve_board_ids
