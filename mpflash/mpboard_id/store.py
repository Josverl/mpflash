import functools
import zipfile
from pathlib import Path
from typing import Final, List, Optional

import jsons

from mpflash.logger import log
from mpflash.mpboard_id.board import __Board

###############################################################################################
HERE: Final = Path(__file__).parent
###############################################################################################


def write_boardinfo_json(board_list: List[__Board], *, folder: Optional[Path] = None):
    """Writes the board information to a JSON file.

    Args:
        board_list (List[Board]): The list of Board objects.
        folder (Path): The folder where the compressed JSON file will be saved.
    """

    if not folder:
        folder = HERE
    # create a zip file with the json file
    with zipfile.ZipFile(folder / "board_info.zip", "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        # write the list to json file inside the zip
        with zipf.open("board_info.json", "w") as fp:
            fp.write(jsons.dumps(board_list, jdkwargs={"indent": 4}).encode())

