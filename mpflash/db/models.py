from pathlib import Path

import peewee

# Module-level database instance; will be initialised by core.py
database = peewee.SqliteDatabase(None)


class BaseModel(peewee.Model):
    """Base model that all models inherit from."""

    class Meta:
        database = database


class Metadata(BaseModel):
    """Configuration information."""

    name = peewee.CharField(primary_key=True)
    value = peewee.TextField(default="")

    class Meta:
        table_name = "metadata"

    def __repr__(self) -> str:
        return f"Config(name={self.name!r}, value={self.value!r})"


class Board(BaseModel):
    """All known Boards model for storing board information."""

    board_id = peewee.CharField(max_length=40)
    version = peewee.CharField(max_length=12)
    board_name = peewee.TextField(default="")
    mcu = peewee.TextField(default="")
    variant = peewee.TextField(default="")
    port = peewee.CharField(max_length=30, default="")
    path = peewee.TextField(default="")  # Path in micropython repo as_posix()
    description = peewee.TextField(default="")
    family = peewee.TextField(default="micropython")
    custom = peewee.BooleanField(default=False)  # True if this is a custom board

    class Meta:
        table_name = "boards"
        primary_key = peewee.CompositeKey("board_id", "version")
        indexes = (
            (("board_id", "version"), True),  # unique composite index
        )

    @property
    def board_key(self) -> str:
        """Composite key combining board_id and version."""
        return f"{self.board_id}_{self.version}"

    @property
    def firmwares(self):
        """Return all firmware records for this board."""
        return Firmware.select().where((Firmware.board_id == self.board_id) & (Firmware.version == self.version))

    def __repr__(self) -> str:
        return f"Board(board_id={self.board_id!r}, version={self.version!r}, board_name={self.board_name!r})"


class Firmware(BaseModel):
    """Firmware model for storing firmware information."""

    board_id = peewee.CharField(max_length=40)
    version = peewee.CharField(max_length=12)
    firmware_file = peewee.TextField(index=True)  # Path to the firmware file
    port = peewee.CharField(max_length=20, default="")  # duplicate of board.port
    description = peewee.TextField(default="")
    source = peewee.TextField(default="")
    build = peewee.IntegerField(default=0)  # Build number
    custom = peewee.BooleanField(default=False)  # True if this is a custom firmware
    custom_id = peewee.CharField(max_length=40, null=True, default=None)

    class Meta:
        table_name = "firmwares"
        primary_key = peewee.CompositeKey("board_id", "version", "firmware_file")

    @property
    def board(self):
        """Return the parent Board record."""
        return Board.get_or_none((Board.board_id == self.board_id) & (Board.version == self.version))

    @property
    def preview(self) -> bool:
        "Check if the firmware is a preview version."
        return "preview" in self.firmware_file

    @property
    def ext(self) -> str:
        "Get the file extension of the firmware file."
        return Path(self.firmware_file).suffix

    def __repr__(self) -> str:
        return f"Firmware(board_id={self.board_id!r}, version={self.version!r}, firmware_file={self.firmware_file!r})"
