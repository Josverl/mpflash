"""
Access to the micropython port and board information that is stored in the board_info.json file 
that is included in the module.

"""

from functools import lru_cache
from typing import List, Optional, Tuple
import importlib
from mpflash.errors import MPFlashError
from .board import Board

from mpflash.versions import clean_version
from .known import get_known_ports, get_known_boards_for_port
from .known import known_stored_boards, find_known_board

