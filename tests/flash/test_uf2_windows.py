import pytest
from unittest import mock
from pathlib import Path
from mpflash.flash.uf2.windows import wait_for_UF2_windows


@pytest.fixture
def mock_psutil_disk_partitions():
    with mock.patch("mpflash.flash.uf2.windows.psutil.disk_partitions") as mock_disk_partitions:
        yield mock_disk_partitions


@pytest.fixture
def mock_get_board_id():
    with mock.patch("mpflash.flash.uf2.windows.get_board_id") as mock_get_board_id:
        yield mock_get_board_id


@pytest.fixture
def mock_time_sleep():
    with mock.patch("mpflash.flash.uf2.windows.time.sleep") as mock_sleep:
        yield mock_sleep


def test_wait_for_UF2_windows_success(mock_psutil_disk_partitions, mock_get_board_id, mock_time_sleep):
    mock_psutil_disk_partitions.return_value = [mock.Mock(device="D:\\")]
    mock_get_board_id.return_value = "TEST_BOARD_ID"
    with mock.patch("pathlib.Path.exists", return_value=True):
        result = wait_for_UF2_windows("TEST_BOARD_ID")
        assert result == Path("D:\\")


def test_wait_for_UF2_windows_timeout(mock_psutil_disk_partitions, mock_get_board_id, mock_time_sleep):
    mock_psutil_disk_partitions.return_value = []
    result = wait_for_UF2_windows("TEST_BOARD_ID", s_max=1)
    assert result is None


def test_wait_for_UF2_windows_oserror(mock_psutil_disk_partitions, mock_get_board_id, mock_time_sleep):
    mock_psutil_disk_partitions.return_value = [mock.Mock(device="D:\\")]
    mock_get_board_id.side_effect = OSError
    with mock.patch("pathlib.Path.exists", return_value=True):
        result = wait_for_UF2_windows("TEST_BOARD_ID")
        assert result is None
