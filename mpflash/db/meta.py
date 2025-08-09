from typing import Optional

from loguru import logger as log

from .core import DatabaseError, OperationalError, Session
from .models import Metadata


def get_metadata() -> dict:
    """
    Get all metadata from the database.

    Returns:
        dict: Dictionary of metadata name-value pairs.
    """
    try:
        with Session() as session:
            metadata = session.query(Metadata).all()
            return {m.name: m.value for m in metadata}
    except (DatabaseError, OperationalError) as e:
        log.error(f"Error retrieving metadata: {e}")
        return {}


def set_metadata(metadata: dict):
    """
    Set metadata in the database.
    Args:
        metadata (dict): Dictionary of metadata name-value pairs.
    Returns:
        None
    """
    with Session() as session:
        for name, value in metadata.items():
            existing_metadata = session.query(Metadata).filter(Metadata.name == name).first()
            if existing_metadata:
                existing_metadata.value = value
            else:
                new_metadata = Metadata(name=name, value=value)
                session.add(new_metadata)
        session.commit()


def get_metadata_value(name: str) -> Optional[str]:
    """
    Get metadata value by name.

    Args:
        session (Session): SQLAlchemy session.
        name (str): Name of the metadata.

    Returns:
        Optional[str]: Metadata value or None if not found.
    """
    with Session() as session:
        metadata = session.query(Metadata).filter(Metadata.name == name).first()
    return metadata.value if metadata else None


def set_metadata_value(name: str, value: str):
    """
    Set metadata value by name.

    Args:
        session (Session): SQLAlchemy session.
        name (str): Name of the metadata.
        value (str): Value to set.

    Returns:
        None
    """
    with Session() as session:
        metadata = session.query(Metadata).filter(Metadata.name == name).first()
        if metadata:
            metadata.value = value
        else:
            new_metadata = Metadata(name=name, value=value)
            session.add(new_metadata)
        session.commit()
