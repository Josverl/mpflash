from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import Index, String
from sqlalchemy.orm import (DeclarativeBase, Mapped, composite, mapped_column,
                            relationship)


class Base(DeclarativeBase):
    pass


class Metadata(Base):
    """
    Configuration information.
    """

    __tablename__ = "metadata"
    name: Mapped[str] = mapped_column(primary_key=True, unique=True)
    value: Mapped[str] = mapped_column()

    def __repr__(self) -> str:
        return f"Config(boards_version={self.name!r}, schema_version={self.value!r})"


class Board(Base):
    """
    All known Boards model for storing board information.
    """

    __tablename__ = "boards"
    __table_args__ = (sa.UniqueConstraint("board_id", "version"),)

    board_id: Mapped[str] = mapped_column(String(40), primary_key=True, unique=False)
    version: Mapped[str] = mapped_column(String(12), primary_key=True, unique=False)
    board_name: Mapped[str] = mapped_column()
    mcu: Mapped[str] = mapped_column()
    variant: Mapped[str] = mapped_column(default="")
    port: Mapped[str] = mapped_column(String(30))
    path: Mapped[str] = mapped_column(comment="Path in micropyton repo as_posix()")
    description: Mapped[str] = mapped_column()
    family: Mapped[str] = mapped_column(default="micropython")
    custom: Mapped[bool] = mapped_column(default=False, comment="True if this is a custom board")
    firmwares = relationship(
        "Firmware",
        back_populates="board",
        lazy="joined",
    )

    board_key = composite(lambda board_id, version: f"{board_id}_{version}", board_id, version)

    def __repr__(self) -> str:
        return f"Board(board_id={self.board_id!r}, version={self.version!r}, board_name={self.board_name!r})"


class Firmware(Base):
    """
    Firmware model for storing firmware information.
    """

    __tablename__ = "firmwares"
    __table_args__ = (
        sa.ForeignKeyConstraint(["board_id", "version"], ["boards.board_id", "boards.version"]),
        {"sqlite_autoincrement": False},
    )

    board_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[str] = mapped_column(String(12), primary_key=True)
    firmware_file: Mapped[str] = mapped_column(String, primary_key=True, index=True, comment="Path to the firmware file")
    # Relationship to Board
    board: Mapped["Board"] = relationship(
        "Board",
        back_populates="firmwares",
        lazy="joined",
        primaryjoin="and_(Firmware.board_id==Board.board_id, Firmware.version==Board.version)",
    )
    port: Mapped[str] = mapped_column(String(20), default="")  # duplicate of board.port
    description: Mapped[str] = mapped_column(default="")
    source: Mapped[str] = mapped_column()
    build: Mapped[int] = mapped_column(default=0, comment="Build number")
    custom: Mapped[bool] = mapped_column(default=False, comment="True if this is a custom firmware")
    custom_id: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)

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
