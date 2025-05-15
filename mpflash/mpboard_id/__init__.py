"""
Access to the micropython port and board information that is stored in the board_info.json file 
that is included in the module.

"""
from mpflash.errors import MPFlashError
from mpflash.versions import clean_version

from .known import (find_known_board, get_known_boards_for_port, known_ports,
                    known_stored_boards)
