from pathlib import Path

import pytest

from mpflash.db.meta import get_metadata, get_metadata_value, set_metadata, set_metadata_value


def test_get_metadata(session_fx):
    """
    Test the get_metadata function.
    """
    # Prepare test data
    test_data = {
        "test_key_1": "test_value_1",
        "test_key_2": "test_value_2",
    }
    set_metadata(test_data)

    # Call the function
    result = get_metadata()

    # Check the result
    assert isinstance(result, dict)
    for key, value in test_data.items():
        assert result[key] == value


def test_get_metadata_value(session_fx):
    """
    Test the get_metadata_value function.
    """
    # Prepare test data
    test_data = {
        "test_key_1": "test_value_1",
        "test_key_3": "test_value_3",
    }
    for key, value in test_data.items():
        set_metadata_value(key, value)

    for key, value in test_data.items():
        # Check if the key exists in the database
        assert get_metadata_value(key) == value
