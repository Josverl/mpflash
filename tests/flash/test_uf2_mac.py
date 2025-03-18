import pytest
from unittest import mock
from pathlib import Path
from mpflash.flash.uf2.macos import wait_for_UF2_macos

@pytest.fixture
def mock_volumes():
    with mock.patch("pathlib.Path.iterdir") as mock_iterdir:
        yield mock_iterdir


def test_wait_for_UF2_macos_timeout(mock_volumes):
    mock_volumes.return_value = []
    
    result = wait_for_UF2_macos("TEST_BOARD_ID", s_max=2)
    assert result is None

