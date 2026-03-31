from sqlite3 import DatabaseError, OperationalError
from typing import Optional

import peewee
from loguru import logger as log

from .models import Metadata


def get_metadata() -> dict:
    """
    Get all metadata from the database.

    Returns:
        dict: Dictionary of metadata name-value pairs.
    """
    try:
        return {m.name: m.value for m in Metadata.select()}
    except (DatabaseError, OperationalError, peewee.OperationalError) as e:
        log.error(f"Error retrieving metadata: {e}")
        return {}


def set_metadata(metadata: dict):
    """
    Set metadata in the database.

    Args:
        metadata: Dictionary of metadata name-value pairs.
    """
    for name, value in metadata.items():
        Metadata.insert(name=name, value=value).on_conflict(
            conflict_target=[Metadata.name],
            update={Metadata.value: value},
        ).execute()


def get_metadata_value(name: str) -> Optional[str]:
    """
    Get metadata value by name.

    Args:
        name: Name of the metadata entry.

    Returns:
        Metadata value or None if not found.
    """
    try:
        row = Metadata.get_or_none(Metadata.name == name)
        return row.value if row else None
    except (DatabaseError, OperationalError, peewee.OperationalError):
        return None


def set_metadata_value(name: str, value: str):
    """
    Set metadata value by name.

    Args:
        name: Name of the metadata entry.
        value: Value to set.
    """
    Metadata.insert(name=name, value=value).on_conflict(
        conflict_target=[Metadata.name],
        update={Metadata.value: value},
    ).execute()
