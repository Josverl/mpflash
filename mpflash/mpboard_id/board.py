from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


# - source : get_boardnames.py
@dataclass
class Board:
    """
    MicroPython Board definitions, parsed from the make and header files
    """

    port: str  # micropython port
    board_id: str  # BOARD_ID (Foldername) as used in the make files
    board_name: str  # Short board description
    description: str  # Long board description
    path: Union[Path, str]
    version: str = field(default="")  # version of MicroPython""
    # versions: List[str] = field(default=[])  # version of MicroPython""
    family: str = field(default="micropython")
    mcu_name: str = field(default="")
    cpu: str = field(default="")
    variant: str = field(default="")
    mcu: str = field(default="")

    def __post_init__(self):
        if not self.cpu:
            if " with " in self.description:
                self.cpu = self.description.rsplit(" with ")[-1]
            else:
                self.cpu = self.port

    @staticmethod
    def from_dict(data: dict) -> "Board":
        valid_keys = {field.name for field in Board.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return Board(**filtered_data)

    def to_dict(self) -> dict:
        return self.__dict__
