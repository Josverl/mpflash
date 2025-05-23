from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FWInfo:
    """
    Downloaded Firmware information
    is somewhat related to the BOARD class in the mpboard_id module
    """

    port: str  # MicroPython port
    board: str  # MicroPython board
    filename: str = field(default="")  # relative filename of the firmware image
    url: str = field(default="")  # url or path to original firmware image
    variant: str = field(default="")  # MicroPython variant
    preview: bool = field(default=False)  # True if the firmware is a preview version
    version: str = field(default="")  # MicroPython version (NO v prefix)
    url: str = field(default="")  # url to the firmware image download folder
    build: str = field(default="0")  # The build = number of commits since the last release
    ext: str = field(default="")  # the file extension of the firmware
    family: str = field(default="micropython")  # The family of the firmware
    custom: bool = field(default=False)  # True if the firmware is a custom build
    description: str = field(default="")  # Description used by this firmware (custom only)
    mcu: str = field(default="")

    def to_dict(self) -> dict:
        """Convert the object to a dictionary"""
        return self.__dict__

    @classmethod
    def from_dict(cls, data: dict) -> "FWInfo":
        """Create a FWInfo object from a dictionary"""
        valid_keys = {field.name for field in FWInfo.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        # add missing keys
        if "ext" not in data:
            data["ext"] = Path(data["filename"]).suffix
        if "family" not in data:
            data["family"] = "micropython"
        return FWInfo(**filtered_data)        
